"""Adapt live game items into the YAML-shaped dict sav_edit already consumes.

The editor derives everything from *path structure* + each item's `serial`:

    core/bl4_functions.py::_walk_for_serials  ->  finds any dict with a
        'serial' string starting with '@U'
    core/bl4_functions.py (process_and_load_items)  ->  reads container/slot
        from the path:
            'inventory' + 'backpack'  ->  container "Backpack"
            'equipped_inventory'      ->  container "Equipped"
            'lostloot'                ->  container "Lost Loot"
            a 'slot_<n>' path segment ->  slot key

So as long as we build:
    {'state': {'inventory': {'items': {'backpack': {
        'slot_0': {'serial': '@U...', 'flags': 0}, ...}}}}}
the existing pipeline treats it exactly like a decrypted save. No tab or codec
code changes are required.
"""

from __future__ import annotations

from typing import Any

from .bridge import Bridge


_CONTAINER_KEYS = {
    "BackpackItems": "backpack",
    "BankItems": "bank",
}


def _copy_live_identity(node: dict[str, Any], record: dict[str, Any]) -> None:
    """Keep the current-session item token beside the save-shaped serial."""
    for source, target in (
        ("handle", "_live_handle"),
        ("instance_id", "_live_instance_id"),
        ("stable_identity_supported", "_live_identity_supported"),
    ):
        value = record.get(source)
        if value is not None:
            node[target] = value


def patch_live_yaml_items(
    yaml_like: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    require_existing: bool,
    expected_serials: dict[tuple[str, int], str] | None = None,
) -> list[list[str]] | None:
    """Atomically patch verified live records into an existing save-shaped snapshot.

    ``None`` means the response cannot be safely reconciled with the snapshot;
    callers should perform one authoritative live refresh instead.
    """
    try:
        containers = yaml_like["state"]["inventory"]["items"]
    except (KeyError, TypeError):
        return None
    if not records:
        return None

    staged: list[tuple[dict[str, Any], str, str, dict[str, Any], list[str]]] = []
    seen: set[tuple[str, int]] = set()
    expected_serials = expected_serials or {}
    for record in records:
        container = str(record.get("container") or "")
        branch_name = _CONTAINER_KEYS.get(container)
        serial = record.get("serial")
        idx = record.get("idx", record.get("index"))
        if branch_name is None or not isinstance(serial, str) or not serial.startswith("@U"):
            return None
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
            return None
        identity = (container, idx)
        if identity in seen:
            return None
        seen.add(identity)

        branch = containers.get(branch_name)
        if not isinstance(branch, dict):
            return None
        slot = f"slot_{idx}"
        current = branch.get(slot)
        if require_existing:
            if not isinstance(current, dict):
                return None
            expected = expected_serials.get(identity)
            if expected and current.get("serial") != expected:
                return None
        elif current is not None:
            return None
        staged.append((
            branch, slot, serial, record,
            ["state", "inventory", "items", branch_name, slot],
        ))

    for branch, slot, serial, record, _path in staged:
        if require_existing:
            branch[slot]["serial"] = serial
            _copy_live_identity(branch[slot], record)
        else:
            branch[slot] = {"serial": serial, "flags": 0}
            _copy_live_identity(branch[slot], record)
    return [path for _branch, _slot, _serial, _record, path in staged]


def items_to_yaml(
    items: list[dict[str, Any]],
    player: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Wrap live item records in the save-shaped dict the editor expects.

    Backpack is authoritative. The player confirmed equipped items remain in the
    backpack, so backpack records map to the 'Backpack' container; only the
    bank goes to its own container. Nothing goes to 'equipped_inventory' --
    reading quick-slots is meaningless (per project owner) and risks making
    gear look unequipped.
    """
    backpack: dict[str, Any] = {}
    bank: dict[str, Any] = {}

    for rec in items:
        if not rec.get("ok") or not rec.get("serial"):
            continue
        container = rec.get("container", "BackpackItems")
        idx = int(rec.get("idx", 0))
        node = {"serial": rec["serial"], "flags": 0}
        _copy_live_identity(node, rec)
        if container == "BankItems":
            bank[f"slot_{idx}"] = node
        else:
            backpack[f"slot_{idx}"] = node

    state: dict[str, Any] = {
        "inventory": {
            "items": {
                "backpack": backpack,
                "bank": bank,
            },
        },
    }
    if player and player.get("ok"):
        state["char_name"] = str(player.get("name") or "")
        state["experience"] = [
            {
                "type": "Character",
                "level": int(player.get("level") or 0),
                "points": int(player.get("experience_points") or 0),
            },
            {
                "type": "Specialization",
                "level": int(player.get("specialization_level") or 0),
                "points": int(player.get("specialization_points") or 0),
            },
        ]
        state["live_runtime"] = True

    return {
        "state": state,
    }


def fetch_live_yaml(bridge: Bridge | None = None) -> dict[str, Any]:
    """Pull all items from the running game and return the save-shaped dict."""
    b = bridge or Bridge()
    items = b.read(container="All")
    try:
        player = b.player()
    except Exception:
        # Keep compatibility with an older live mod: inventory editing remains
        # usable, while generators fall back to their existing default level.
        player = None
    return items_to_yaml(items, player)


def fetch_live_items(bridge: Bridge | None = None) -> list[dict[str, Any]]:
    """Pull all items, returning the raw record list (serials + metadata)."""
    return (bridge or Bridge()).read(container="All")
