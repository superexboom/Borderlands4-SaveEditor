"""Account progress kept in the profile save (``domains.local``).

- SDU upgrades: ``progression_shared.graphs[name=sdu_upgrades].nodes`` store one
  ``{name, points_spent}`` per bought level; tokens live in
  ``progression_shared.point_pools.echotokenprogresspoints``.
- Vault powers: graph ``vaultpower_vaultreward_upgrades`` stores nodes by alias
  with ``is_activated``.
- Unlock ledgers: ``unlockables.<ledger>.entries`` (account-wide challenge
  completions, DLC shared progress and cosmetics).

Definitions come from the NCS catalog (``progress_graphs``, challenge
``account_unlock``) plus the editor's shipped ledger lists.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from . import progress_catalog as cat
from .unlock_data import CHARACTER_CLASSES, UNLOCKABLES
from .unlock_logic import (ensure_legacy_unlock_data, get_or_create_dict, get_or_create_list,
                           get_profile_local, is_profile_save)

SDU_GRAPH = "sdu_upgrades"
SDU_GROUP_DEF = "Oak2_GlobalProgressGraph_Group"
SDU_POOL = "echotokenprogresspoints"
VAULT_POWER_GRAPH = "vaultpower_vaultreward_upgrades"

# Ledger display order; challenge-backed ledgers first, cosmetics after.
SHARED_LEDGERS = ("echo_upgrade_challenges", "echo_log_challenges", "vault_object_challenges",
                  "sharedprogress_cowbell", "sharedprogress_harmonica", "sharedprogress_cello",
                  "sharedprogress_tuba")
COSMETIC_LEDGERS = ("unlockable_darksiren", "unlockable_paladin", "unlockable_gravitar", "unlockable_exosoldier",
                    "unlockable_robodealer", "unlockable_corpohacker", "unlockable_echo4",
                    "unlockable_weapons", "unlockable_vehicles", "unlockable_hoverdrives")


def _local(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict) or not is_profile_save(data):
        return {}
    local = (data.get("domains") or {}).get("local")
    return local if isinstance(local, dict) else {}


# --------------------------------------------------------------------------- #
# Ledgers
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _ledger_catalog() -> dict[str, tuple[str, ...]]:
    """ledger -> every known entry (canonical spelling), shipped lists + challenge unlocks."""
    ensure_legacy_unlock_data()
    merged: dict[str, dict[str, str]] = {}
    for ledger, value in UNLOCKABLES.items():
        entries = value.get("entries") if isinstance(value, dict) else value
        for entry in entries or []:
            if isinstance(entry, str) and "." in entry:
                merged.setdefault(ledger.lower(), {}).setdefault(entry.lower(), entry)
    for challenge in cat.section("challenges").values():
        entry = str(challenge.get("account_unlock") or "")
        if "." in entry:
            merged.setdefault(entry.split(".", 1)[0].lower(), {}).setdefault(entry.lower(), entry)
    return {ledger: tuple(sorted(rows.values(), key=str.lower)) for ledger, rows in merged.items()}


@lru_cache(maxsize=1)
def _entry_challenges() -> dict[str, str]:
    """lower-case ledger entry -> challenge key that grants it."""
    out: dict[str, str] = {}
    for key, challenge in cat.section("challenges").items():
        entry = str(challenge.get("account_unlock") or "").lower()
        if entry:
            out.setdefault(entry, key)
    return out


def ledger_keys() -> list[str]:
    known = _ledger_catalog()
    return [ledger for ledger in SHARED_LEDGERS + COSMETIC_LEDGERS if known.get(ledger)]


def unlocked_entries(data: dict[str, Any], ledger: str) -> set[str]:
    section = (_local(data).get("unlockables") or {}).get(ledger)
    entries = section.get("entries") if isinstance(section, dict) else None
    return {str(entry).lower() for entry in entries or [] if isinstance(entry, str)}


def ledger_counts(data: dict[str, Any], ledger: str) -> tuple[int, int]:
    entries = _ledger_catalog().get(ledger, ())
    unlocked = unlocked_entries(data, ledger)
    return sum(1 for entry in entries if entry.lower() in unlocked), len(entries)


_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def _words(text: str) -> str:
    return " ".join(_WORDS.findall(text.replace("_", " "))) or text


def cosmetic_kind(entry: str) -> str:
    """Skin / Head / Body / Attachment / Mat / Shiny / vehicle / manufacturer (hover drives)."""
    name = entry.split(".", 1)[-1]
    match = re.match(r"([A-Za-z]+)", name)
    kind = match.group(1) if match else name
    if entry.lower().startswith("unlockable_vehicles.") and kind not in ("Mat",):
        return "Vehicle"
    return kind


def cosmetic_title(entry: str) -> str:
    """Readable name from the unlockable key (the game ships no NCS names for cosmetics)."""
    name = entry.split(".", 1)[-1]
    match = re.fullmatch(r"([A-Za-z]+?)(\d+)(?:_(.+))?", name)
    if match and match.group(1) in ("Skin", "Head", "Body", "Attachment", "Mat"):
        tail = f" · {_words(match.group(3))}" if match.group(3) else ""
        return f"{match.group(1)} {match.group(2)}{tail}"
    if name.startswith("Shiny_"):
        return _words(name[len("Shiny_"):])
    return _words(name)


_PLACE_TOKENS = {"city", "grasslands", "mountains", "shatteredlands", "elpis", "gra", "mou", "sha", "cit",
                 "mtn", "elp", "parent", "kairos", "global"}


def _stem(name: str) -> tuple[str, str]:
    """``Activity_AugerMines_City_1`` -> (``Activity_AugerMines``, ``City 1``)."""
    tokens = name.split("_")
    cut = next((index for index, token in enumerate(tokens)
                if index and (token.isdigit() or token.lower() in _PLACE_TOKENS)), len(tokens))
    stem = "_".join(tokens[:cut])
    tail = " ".join(tokens[cut:])
    match = re.fullmatch(r"(.*?[A-Za-z])(\d+)", stem)
    if match and not tail:  # Collectible_DahlCaches3
        stem, tail = match.group(1), match.group(2)
    return stem, tail


def ledger_rows(data: dict[str, Any], ledger: str, lang: str) -> list[dict[str, Any]]:
    unlocked = unlocked_entries(data, ledger)
    challenges = cat.section("challenges")
    by_entry = _entry_challenges()
    entries = _ledger_catalog().get(ledger, ())
    cosmetic = ledger in COSMETIC_LEDGERS
    # Group titles: the "<stem>_Parent" entry's challenge when the ledger has one.
    group_titles: dict[str, str] = {}
    if not cosmetic:
        for entry in entries:
            name = entry.split(".", 1)[-1]
            if name.lower().endswith("_parent"):
                challenge = challenges.get(by_entry.get(entry.lower(), "")) or {}
                group_titles[_stem(name)[0].lower()] = cat.text(challenge.get("title"), lang)
    rows = []
    for entry in entries:
        name = entry.split(".", 1)[-1]
        challenge_key = by_entry.get(entry.lower(), "")
        challenge = challenges.get(challenge_key) or {}
        title = cat.text(challenge.get("title"), lang) if challenge else ""
        if cosmetic:
            group, tail = cosmetic_kind(entry), ""
            title = title or cosmetic_title(entry)
        else:
            stem, tail = _stem(name)
            group = group_titles.get(stem.lower()) or _words(re.sub(r"^(Collectible|Collect|Activity)_", "", stem))
            title = title or _words(name)
        rows.append({"entry": entry, "title": title, "tail": tail, "group": group,
                     "named": bool(challenge_key and title), "unlocked": entry.lower() in unlocked,
                     "challenge": challenge_key, "hint": cat.text(challenge.get("desc"), lang) if challenge else ""})
    if not cosmetic:
        # A derived group name gives way to the one challenge title all its entries share ("Arjay Log").
        shared: dict[str, set[str]] = {}
        for row in rows:
            shared.setdefault(row["group"], set()).add(row["title"] if row["named"] else "")
        for row in rows:
            titles = shared[row["group"]]
            if len(titles) == 1 and "" not in titles and row["group"] not in group_titles.values():
                row["group"] = next(iter(titles))
    # Several entries share one challenge title (all Arjay logs are "Arjay Log"): add the place/number.
    seen: dict[str, int] = {}
    for row in rows:
        seen[row["title"]] = seen.get(row["title"], 0) + 1
    for row in rows:
        if seen[row["title"]] > 1 and row["tail"]:
            row["title"] = f"{row['title']} · {row['tail']}"
    rows.sort(key=lambda row: (row["group"], row["entry"].lower()))
    return rows


def set_entries(data: dict[str, Any], ledger: str, entries: list[str], unlocked: bool) -> int:
    """Add or remove ledger entries (case-insensitive, canonical spelling kept)."""
    if not is_profile_save(data):
        return 0
    section = get_or_create_dict(get_or_create_dict(get_profile_local(data), "unlockables"), ledger)
    current = {str(entry).lower(): entry for entry in get_or_create_list(section, "entries") if isinstance(entry, str)}
    before = len(current)
    for entry in entries:
        if unlocked:
            current.setdefault(entry.lower(), entry)
        else:
            current.pop(entry.lower(), None)
    section["entries"] = sorted(current.values(), key=str.lower)
    return abs(len(current) - before)


def set_ledger(data: dict[str, Any], ledger: str, unlocked: bool) -> int:
    return set_entries(data, ledger, list(_ledger_catalog().get(ledger, ())), unlocked)


# --------------------------------------------------------------------------- #
# Progress graphs (SDU, vault powers)
# --------------------------------------------------------------------------- #
def _graphs_node(data: dict[str, Any], create: bool = False) -> dict[str, Any]:
    local = get_profile_local(data) if create else _local(data)
    progression = get_or_create_dict(local, "progression_shared") if create else (local.get("progression_shared") or {})
    return progression if isinstance(progression, dict) else {}


def _graph(data: dict[str, Any], name: str, group_def: str = "", create: bool = False) -> dict[str, Any] | None:
    progression = _graphs_node(data, create)
    graphs = get_or_create_list(progression, "graphs") if create else (progression.get("graphs") or [])
    for graph in graphs:
        if isinstance(graph, dict) and graph.get("name") == name:
            return graph
    if not create:
        return None
    graph = {"name": name, "group_def_name": group_def, "nodes": []}
    graphs.append(graph)
    return graph


def sdu_groups() -> list[dict[str, Any]]:
    return list(((cat.catalog().get("progress_graphs") or {}).get(SDU_GRAPH) or {}).get("groups") or [])


def sdu_points(data: dict[str, Any]) -> dict[str, int]:
    pools = _graphs_node(data).get("point_pools") or {}
    pool = int(pools.get(SDU_POOL) or 0) if isinstance(pools, dict) else 0
    graph = _graph(data, SDU_GRAPH) or {}
    spent = sum(int((node or {}).get("points_spent") or 0) for node in graph.get("nodes") or [] if isinstance(node, dict))
    total = sum(node["cost"] for group in sdu_groups() for node in group["nodes"])
    return {"pool": pool, "spent": spent, "available": pool - spent, "max_cost": total}


def sdu_rows(data: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    bought = {str(node.get("name")) for node in (_graph(data, SDU_GRAPH) or {}).get("nodes") or []
              if isinstance(node, dict)}
    rows = []
    for group in sdu_groups():
        level = 0
        for node in group["nodes"]:  # levels are bought in order
            if node["key"] not in bought:
                break
            level += 1
        amount = sum(node["amount"] for node in group["nodes"][:level])
        full = sum(node["amount"] for node in group["nodes"])
        effect = cat.text(group.get("effect"), lang)
        rows.append({
            "key": group["key"], "title": cat.text(group.get("title"), lang, group["key"]),
            "level": level, "max": len(group["nodes"]),
            "spent": sum(node["cost"] for node in group["nodes"][:level]),
            "cost": sum(node["cost"] for node in group["nodes"]),
            "next_cost": group["nodes"][level]["cost"] if level < len(group["nodes"]) else 0,
            "effect": effect.replace("{0}", f"{amount:g}") if effect else "",
            "effect_max": effect.replace("{0}", f"{full:g}") if effect else "",
        })
    return rows


def set_sdu_level(data: dict[str, Any], group_key: str, level: int) -> bool:
    """Own the first ``level`` nodes of one SDU line; the token pool grows to cover the total spent."""
    group = next((row for row in sdu_groups() if row["key"] == group_key), None)
    if group is None or not is_profile_save(data):
        return False
    level = max(0, min(int(level), len(group["nodes"])))
    graph = _graph(data, SDU_GRAPH, SDU_GROUP_DEF, create=True)
    members = {node["key"] for node in group["nodes"]}
    others = [node for node in graph.get("nodes") or [] if isinstance(node, dict) and node.get("name") not in members]
    owned = [{"name": node["key"], "points_spent": node["cost"]} for node in group["nodes"][:level]]
    graph["nodes"] = others + owned
    pools = get_or_create_dict(_graphs_node(data, create=True), "point_pools")
    spent = sum(int(node.get("points_spent") or 0) for node in graph["nodes"])
    pools[SDU_POOL] = max(int(pools.get(SDU_POOL) or 0), spent)
    return True


def set_all_sdu(data: dict[str, Any], maxed: bool) -> int:
    return sum(set_sdu_level(data, group["key"], len(group["nodes"]) if maxed else 0) for group in sdu_groups())


def vault_power_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = ((cat.catalog().get("progress_graphs") or {}).get(VAULT_POWER_GRAPH) or {}).get("nodes") or []
    saved = {str(node.get("name")): bool(node.get("is_activated"))
             for node in (_graph(data, VAULT_POWER_GRAPH) or {}).get("nodes") or [] if isinstance(node, dict)}
    return [{"key": node["key"], "alias": node["alias"], "cost": node["cost"],
             "activated": saved.get(node["alias"], False)} for node in nodes]


def set_vault_power(data: dict[str, Any], alias: str, activated: bool) -> bool:
    if not is_profile_save(data) or alias not in {row["alias"] for row in vault_power_rows(data)}:
        return False
    graph = _graph(data, VAULT_POWER_GRAPH, "progress_group_gravitar", create=True)
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict) and node.get("name") != alias]
    if activated:
        nodes.append({"name": alias, "is_activated": True})
    order = [row["alias"] for row in vault_power_rows(data)]
    graph["nodes"] = sorted(nodes, key=lambda node: order.index(node["name"]) if node["name"] in order else 99)
    return True


def character_name(ledger: str) -> str:
    token = ledger.split("_", 1)[-1]
    return next((info["name"] for name, info in CHARACTER_CLASSES.items() if name.lower() == token), "")
