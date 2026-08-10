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


def items_to_yaml(items: list[dict[str, Any]]) -> dict[str, Any]:
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
        if container == "BankItems":
            bank[f"slot_{idx}"] = node
        else:
            backpack[f"slot_{idx}"] = node

    return {
        "state": {
            "inventory": {
                "items": {
                    "backpack": backpack,
                    "bank": bank,
                },
            },
        },
    }


def fetch_live_yaml(bridge: Bridge | None = None) -> dict[str, Any]:
    """Pull all items from the running game and return the save-shaped dict."""
    b = bridge or Bridge()
    items = b.read(container="All")
    return items_to_yaml(items)


def fetch_live_items(bridge: Bridge | None = None) -> list[dict[str, Any]]:
    """Pull all items, returning the raw record list (serials + metadata)."""
    return (bridge or Bridge()).read(container="All")
