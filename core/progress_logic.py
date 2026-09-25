"""Read/write helpers behind the "Game Progress" page.

Pure functions over the decoded save dict (character or profile save) so the
view model, the character-page presets and tests share one implementation.
Display metadata comes from :mod:`core.progress_catalog`.
"""

from __future__ import annotations

import copy
import math
import re
from functools import lru_cache
from typing import Any

from . import bl4_functions as bl4f
from . import progress_catalog as cat
from .unlock_data import POSTGAME
from .unlock_logic import get_or_create_dict, is_profile_save

INT32_MAX = 2147483647
AMMO_KEYS = ("pistol", "smg", "assaultrifle", "shotgun", "sniper", "repairkit")
AMMO_LIMIT = 99999


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _state(data: dict[str, Any]) -> dict[str, Any]:
    state = data.get("state") if isinstance(data, dict) else None
    return state if isinstance(state, dict) else {}


def _get_path(data: Any, path: list[Any] | None) -> Any:
    node = data
    for key in path or []:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return None
    return node


def max_vault_hunter_level() -> int:
    return _int(POSTGAME.get("highest_unlocked_vault_hunter_level"), 7) or 7


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def read_overview(data: dict[str, Any]) -> dict[str, Any]:
    """Editable character-save basics shown on the overview tab."""
    state = _state(data)
    world = data.get("globals") if isinstance(data.get("globals"), dict) else {}
    paths = bl4f.find_currency_paths(data)
    ammo = state.get("ammo") if isinstance(state.get("ammo"), dict) else {}
    ammo_keys = [key for key in AMMO_KEYS if key in ammo] + [key for key in ammo if key not in AMMO_KEYS]
    return {
        "playtime_seconds": float(state.get("total_playtime") or 0.0),
        "last_played": _int(state.get("last_played_timestamp")),
        "cash": _int(_get_path(data, paths.get("cash"))),
        "eridium": _int(_get_path(data, paths.get("eridium"))),
        "ammo": {key: _int(ammo.get(key)) for key in ammo_keys},
        "uvh_level": _int(world.get("vault_hunter_level")),
        "uvh_highest": _int(world.get("highest_unlocked_vault_hunter_level")),
        "uvh_max": max_vault_hunter_level(),
        "true_mode": bool(state.get("true_mode")),
    }


def set_playtime(data: dict[str, Any], seconds: float) -> None:
    get_or_create_dict(data, "state")["total_playtime"] = max(0.0, round(float(seconds), 5))


def set_currency(data: dict[str, Any], key: str, value: int) -> bool:
    if key not in ("cash", "eridium"):
        return False
    path = bl4f.find_currency_paths(data).get(key)
    if not path:
        path = ["state", "currencies", key]
        get_or_create_dict(get_or_create_dict(data, "state"), "currencies")
    bl4f._set_by_path(data, path, min(max(int(value), 0), INT32_MAX))
    return True


def set_ammo(data: dict[str, Any], key: str, value: int) -> bool:
    ammo = get_or_create_dict(get_or_create_dict(data, "state"), "ammo")
    if key not in ammo and key not in AMMO_KEYS:
        return False
    ammo[key] = min(max(int(value), 0), AMMO_LIMIT)
    return True


def set_vault_hunter_levels(data: dict[str, Any], level: int, highest: int) -> None:
    """Current UVH level can never exceed the highest unlocked one."""
    world = get_or_create_dict(data, "globals")
    top = max_vault_hunter_level()
    highest = min(max(int(highest), 0), top)
    world["highest_unlocked_vault_hunter_level"] = highest
    world["vault_hunter_level"] = min(max(int(level), 0), highest)


# --------------------------------------------------------------------------- #
# Completion summary
# --------------------------------------------------------------------------- #
def _stat_value(stats: Any, stat_path: str) -> int:
    """Value of ``stats.a.b.c`` in the save; parent dicts count their leaves."""
    node = stats
    for key in stat_path.split(".")[1:]:
        if not isinstance(node, dict):
            return 0
        node = node.get(key)
        if node is None:
            return 0
    if isinstance(node, dict):
        return sum(1 for value in node.values() if _int(value) > 0)
    return _int(node)


def challenge_value(data: dict[str, Any], challenge: dict[str, Any]) -> int:
    stat = str(challenge.get("stat") or "")
    if not stat.startswith("stats."):
        return 0
    return _stat_value(data.get("stats"), stat)


def _collectible_root(stat: str) -> int:
    """Index of the ``*collectibles`` part of a stat path, or -1."""
    parts = stat.split(".")
    if not parts or parts[0] != "stats":
        return -1
    return next((index for index, part in enumerate(parts) if part.endswith("collectibles")), -1)


@lru_cache(maxsize=1)
def _item_collectible_stats() -> frozenset[str]:
    """Leaf stats below a ``*collectibles`` node (one collectible each).

    Echo logs nest one level deeper (``echologs_general.el_g_city.<item>``), so
    depth alone is not enough; aggregate challenges such as "all City echo
    logs" are excluded because another stat uses them as a prefix.
    """
    stats = {str(row.get("stat") or "") for row in cat.section("challenges").values()}
    candidates = {stat for stat in stats if (root := _collectible_root(stat)) >= 0
                  and len(stat.split(".")) - root >= 3}
    prefixes = {stat.rsplit(".", 1)[0] for stat in stats if "." in stat}
    return frozenset(stat for stat in candidates if stat not in prefixes)


def is_item_collectible(stat: str) -> bool:
    return stat in _item_collectible_stats()


def completion_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Counts for the overview tiles; totals come from the NCS catalog."""
    missions = cat.section("missions")
    # Same mission list as the missions tab (persisted, titled missions only).
    completed = {key for key in _mission_index() if mission_state(data, key) == "done"}
    main = [key for key, row in missions.items() if row.get("type") == "MainMission"]

    challenges = cat.section("challenges")
    item_collectibles = [row for row in challenges.values() if is_item_collectible(row.get("stat", ""))]
    collected = sum(1 for row in item_collectibles if challenge_value(data, row) >= max(row.get("goals") or [1]))

    menu = [challenges[key] for category in cat.catalog().get("challenge_categories") or []
            for key in category.get("challenges") or [] if key in challenges]
    menu_done = sum(1 for row in menu if row.get("goals") and challenge_value(data, row) >= max(row["goals"]))
    return {
        "missions_completed": len(completed),
        "missions_total": len(_mission_index()),
        "main_completed": sum(1 for key in main if key in completed),
        "main_total": len(main),
        "collectibles_collected": collected,
        "collectibles_total": len(item_collectibles),
        "challenges_completed": menu_done,
        "challenges_total": len(menu),
    }


def region_kills(data: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    regions = ((data.get("stats") or {}).get("regions") or {}) if isinstance(data.get("stats"), dict) else {}
    rows = []
    for key, value in (regions.items() if isinstance(regions, dict) else []):
        kills = _int((value or {}).get("region_kills")) if isinstance(value, dict) else 0
        rows.append({"key": str(key), "title": cat.region_title(key, lang), "kills": kills})
    rows.sort(key=lambda row: row["title"].casefold())
    return rows


def save_kind(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    return "profile" if is_profile_save(data) else "character"


# --------------------------------------------------------------------------- #
# Challenges & achievements
# --------------------------------------------------------------------------- #
ACHIEVEMENTS_CATEGORY = "achievements"
TOP_REGIONS = ("grasslands", "mountains", "shatteredlands", "city", "elpis")


def _stat_node(data: dict[str, Any], stat: str, create: bool = False) -> tuple[Any, str]:
    """(parent dict, leaf key) for ``stats.a.b.c``; parent is None if missing."""
    parts = stat.split(".")
    if len(parts) < 2 or parts[0] != "stats":
        return None, ""
    node = get_or_create_dict(data, "stats") if create else data.get("stats")
    for key in parts[1:-1]:
        if not isinstance(node, dict):
            return None, ""
        if create and not isinstance(node.get(key), dict):
            if node.get(key) is not None:
                return None, ""  # never replace a counter with a subtree
            node[key] = {}
        node = node.get(key)
    return (node if isinstance(node, dict) else None), parts[-1]


def set_stat_value(data: dict[str, Any], stat: str, value: int) -> bool:
    """Write one counter; zero removes the key (the game omits unset stats)."""
    value = max(0, int(value))
    parent, leaf = _stat_node(data, stat, create=value > 0)
    if parent is None:
        return value == 0
    if isinstance(parent.get(leaf), dict):
        return False  # aggregate node: edit its children instead
    if value == 0:
        parent.pop(leaf, None)
    else:
        parent[leaf] = min(value, INT32_MAX)
    return True


@lru_cache(maxsize=1)
def _challenge_children() -> dict[str, tuple[str, ...]]:
    children: dict[str, list[str]] = {}
    for key, row in cat.section("challenges").items():
        parent = row.get("parent")
        if parent:
            children.setdefault(parent, []).append(key)
    return {key: tuple(sorted(value)) for key, value in children.items()}


@lru_cache(maxsize=1)
def _achievement_keys() -> tuple[str, ...]:
    rows = cat.section("challenges")

    def is_achievement(row: dict[str, Any]) -> bool:
        parts = str(row.get("stat") or "").split(".")
        return len(parts) >= 3 and parts[1].endswith("achievements") and bool(row.get("title"))

    return tuple(sorted((key for key, row in rows.items() if is_achievement(row)),
                        key=lambda key: rows[key].get("stat", "")))


def challenge_category_keys() -> list[tuple[str, Any, list[str]]]:
    """(id, title, challenge keys) for the in-game menu plus an Achievements group."""
    rows = cat.section("challenges")
    out = [(str(category.get("id") or ""), category.get("title"),
            [key for key in category.get("challenges") or [] if key in rows])
           for category in cat.catalog().get("challenge_categories") or []]
    out.append((ACHIEVEMENTS_CATEGORY, None, list(_achievement_keys())))
    return out


def challenge_state(data: dict[str, Any], key: str) -> dict[str, Any]:
    row = cat.section("challenges").get(key) or {}
    goals = [int(goal) for goal in row.get("goals") or [] if int(goal) > 0]
    children = _challenge_children().get(key, ())
    if children:
        value = sum(1 for child in children if challenge_state(data, child)["done"])
        goal = len(children)
    else:
        value = challenge_value(data, row)
        goal = max(goals) if goals else 0
    return {"value": value, "goal": goal, "goals": goals, "aggregate": bool(children),
            "done": goal > 0 and value >= goal}


def set_challenge_value(data: dict[str, Any], key: str, value: int) -> bool:
    row = cat.section("challenges").get(key) or {}
    if _challenge_children().get(key):
        return False
    return set_stat_value(data, str(row.get("stat") or ""), value)


def complete_challenge(data: dict[str, Any], key: str, done: bool = True, _seen: set | None = None) -> int:
    """Complete (or reset) one challenge; aggregates recurse into their children."""
    seen = _seen if _seen is not None else set()
    if key in seen:
        return 0
    seen.add(key)
    row = cat.section("challenges").get(key) or {}
    children = _challenge_children().get(key, ())
    if children:
        return sum(complete_challenge(data, child, done, seen) for child in children)
    state = challenge_state(data, key)
    if done and (state["goal"] <= 0 or state["value"] >= state["goal"]):
        return 0
    if not done and state["value"] == 0:
        return 0
    return int(set_stat_value(data, str(row.get("stat") or ""), state["goal"] if done else 0))


# --------------------------------------------------------------------------- #
# Collectibles
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _collectible_index() -> dict[str, Any]:
    """Static structure: category -> group -> items (with location/echo data)."""
    challenges = cat.section("challenges")
    by_stat = {row.get("stat"): key for key, row in challenges.items() if row.get("stat")}
    locations_by_challenge: dict[str, dict[str, Any]] = {}
    for location_id, location in cat.section("locations").items():
        if location.get("challenge"):
            locations_by_challenge.setdefault(location["challenge"], dict(location, id=location_id))
    echo_titles = {row.get("challenge"): row.get("title")
                   for row in cat.section("echo_logs").values() if row.get("challenge")}
    categories: dict[str, dict[str, Any]] = {}
    for stat in sorted(_item_collectible_stats()):
        key = by_stat.get(stat)
        if not key:
            continue
        parts = stat.split(".")
        root = _collectible_root(stat)
        category = ".".join(parts[:root + 2])
        group = ".".join(parts[:-1])
        location = locations_by_challenge.get(key)
        entry = categories.setdefault(category, {"stat": category, "groups": {}, "type": ""})
        if location and not entry["type"]:
            entry["type"] = location.get("type") or ""
        entry["groups"].setdefault(group, []).append({
            "stat": stat,
            "challenge": key,
            "goal": max(challenges[key].get("goals") or [1]),
            "location": location,
            "echo_title": echo_titles.get(key),
        })
    return categories


def _region_token(*names: str) -> str:
    for name in names:
        for token in str(name).lower().replace(".", "_").split("_"):
            if token in TOP_REGIONS:
                return token
    return ""


def _trailing_number(name: str) -> str:
    """Item ordinal from a key: trailing digits, else a one-letter token (``vaultkey_a_x`` -> A)."""
    digits = ""
    for char in reversed(str(name)):
        if not char.isdigit():
            break
        digits = char + digits
    if digits:
        return str(int(digits))
    letter = next((token for token in str(name).split("_")[1:] if len(token) == 1 and token.isalpha()), "")
    return letter.upper()


def collectible_area(stat: str) -> str:
    """DLC codename from a stat path (``cowbell_openworld`` -> ``cowbell``); base game is ""."""
    parts = stat.split(".")
    area = parts[1] if len(parts) > 1 else ""
    return "" if area == "openworld" else area.split("_", 1)[0]


def area_title(area: str, lang: str) -> str:
    if not area:
        return cat.region_title("kairosgeneric", lang)
    return cat.text((cat.catalog().get("areas") or {}).get(area), lang, area.capitalize())


def collectible_category_title(category: str, lang: str, overrides: dict[str, str] | None = None) -> str:
    """Kind name; per-region categories (``vaultkey_grasslands``) get the region appended."""
    leaf = category.rsplit(".", 1)[-1]
    region = _region_token(leaf)
    kind = _collectible_kind_title(category, lang, overrides)
    return f"{kind} · {cat.region_title(region, lang)}" if region else kind


def _collectible_kind_title(category: str, lang: str, overrides: dict[str, str] | None = None) -> str:
    leaf = category.rsplit(".", 1)[-1]
    if overrides and overrides.get(leaf):
        return str(overrides[leaf])
    entry = _collectible_index().get(category) or {}
    type_row = cat.section("location_types").get(entry.get("type") or "") or {}
    title = cat.text(type_row.get("title"), lang)
    if title:
        return title
    parent = next((row for row in cat.section("challenges").values() if row.get("stat") == category), {})
    return cat.text(parent.get("title"), lang, category.rsplit(".", 1)[-1]).strip()


def _item_collected(data: dict[str, Any], item: dict[str, Any]) -> bool:
    return challenge_value(data, cat.section("challenges")[item["challenge"]]) >= item["goal"]


def collectible_categories(data: dict[str, Any], lang: str,
                           overrides: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows = []
    for category, entry in _collectible_index().items():
        items = [item for group in entry["groups"].values() for item in group]
        area = collectible_area(category)
        rows.append({"key": category, "title": collectible_category_title(category, lang, overrides),
                     "area_key": area, "area": area_title(area, lang),
                     "done": sum(1 for item in items if _item_collected(data, item)),
                     "total": len(items)})
    rows.sort(key=lambda row: (row["area_key"] != "", row["area_key"], row["title"].casefold()))
    return rows


def collectible_items(data: dict[str, Any], category: str, lang: str,
                      overrides: dict[str, str] | None = None) -> list[dict[str, Any]]:
    entry = _collectible_index().get(category) or {}
    kind = _collectible_kind_title(category, lang, overrides)
    rows = []
    for group, items in entry.get("groups", {}).items():
        group_region = _region_token(group.rsplit(".", 1)[-1])
        for item in items:
            leaf = item["stat"].rsplit(".", 1)[-1]
            region = _region_token(leaf) or group_region
            region_title = cat.region_title(region, lang) if region else ""
            location = item.get("location") or {}
            title = cat.text(item.get("echo_title"), lang) or cat.text(location.get("title"), lang)
            if not title:
                number = _trailing_number(leaf)
                title = " · ".join(part for part in (kind, region_title) if part) + (f" #{number}" if number else "")
            rows.append({
                "stat": item["stat"],
                "title": title,
                "group": region_title or group.rsplit(".", 1)[-1],
                "collected": _item_collected(data, item),
                "map": location.get("map") or "",
                "x": location.get("x", 0.0),
                "y": location.get("y", 0.0),
                "has_location": bool(location),
            })
    return rows


def set_collected(data: dict[str, Any], stat: str, collected: bool) -> bool:
    if not is_item_collectible(stat):
        return False
    return set_stat_value(data, stat, 1 if collected else 0)


_MAP_REGIONS = {"World_P": "kairosgeneric", "Elpis_P": "elpis", "UpperCity_P": "city_upper"}


def map_title(world: str, lang: str, templates: dict[str, str] | None = None) -> str:
    """Readable map name: base maps use region titles, DLC maps their area name.

    ``templates`` may provide ``fortress``/``vault`` patterns such as
    ``"{region} Fortress"`` for the per-region base-game maps, and explicit
    per-map names (``World_P`` style keys) for everything else.
    """
    templates = templates or {}
    if templates.get(world):
        return str(templates[world])
    if world in _MAP_REGIONS:
        return cat.region_title(_MAP_REGIONS[world], lang)
    stem = world[:-2] if world.endswith("_P") else world
    kind, _, rest = stem.partition("_")
    region = _region_token(rest)
    if kind.lower() in ("fortress", "vault") and region and templates.get(kind.lower()):
        return str(templates[kind.lower()]).format(region=cat.region_title(region, lang))
    area = stem.split("_", 1)[0].lower()
    if area in (cat.catalog().get("areas") or {}) and "_" not in stem:
        return area_title(area, lang)
    places = _fast_travel_titles(world, lang)
    return " · ".join(places[:2]) if places else stem.replace("_", " ")


def _fast_travel_titles(world: str, lang: str) -> list[str]:
    """Localized fast-travel station names of a map (sub-maps have no region title)."""
    names: list[str] = []
    for location in cat.section("locations").values():
        if location.get("map") == world and location.get("type") == "discoverylocation_menuio_fasttravel":
            name = _place_title(location, lang)
            if name and name not in names:
                names.append(name)
    return sorted(names)


def _place_title(location: dict[str, Any], lang: str) -> str:
    """Location display name on one line (station names embed ``<br>``)."""
    return " ".join(cat.text(location.get("title"), lang).replace("<br>", " ").split())


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
LAYER_GROUPS = ("collectible", "menuio", "activity", "secondary", "miscellaneous")
DEFAULT_LAYERS_ON = ("collectible",)
DEFAULT_TYPES_ON = ("discoverylocation_menuio_fasttravel",)


def layer_group(type_key: str) -> str:
    """Top-level group of a discovery location type (collectible, menuio...)."""
    lowered = str(type_key).lower()
    for group in LAYER_GROUPS:
        if f"_{group}" in lowered:
            return group
    return "miscellaneous"


def default_layer_visible(type_key: str) -> bool:
    return layer_group(type_key) in DEFAULT_LAYERS_ON or type_key in DEFAULT_TYPES_ON


# Placeholder discovery types that the game never draws on its own map.
HIDDEN_TYPES = frozenset({"discoverynothing", "discoverylocation_activity_hidden"})


@lru_cache(maxsize=1)
def _layer_keys() -> dict[str, str]:
    """Location type -> layer key: variants sharing an English name form one layer.

    ``…_Underground``/``…_SendOnly``/the five bounty-pack travel stations would
    otherwise show up as duplicate layers; the English name keeps the key stable
    across UI languages (layer toggles are persisted by key).
    """
    buckets: dict[str, list[str]] = {}
    for type_key, row in cat.section("location_types").items():
        buckets.setdefault(cat.text(row.get("title"), "en-US") or type_key, []).append(type_key)
    return {member: min(members, key=lambda key: (len(key), key))
            for members in buckets.values() for member in members}


def layer_key(type_key: str) -> str:
    return _layer_keys().get(type_key, type_key)


def _type_title(type_key: str, lang: str) -> str:
    row = cat.section("location_types").get(type_key) or {}
    title = cat.text(row.get("title"), lang)
    if title:
        return title
    name = str(row.get("name") or type_key)
    return name.replace("DiscoveryLocation_", "").replace("_", " ")


def map_list(data: dict[str, Any], lang: str, templates: dict[str, str] | None = None,
             track: bool = True) -> list[dict[str, Any]]:
    """Maps that have artwork, with collectible progress for challenge-driven points.

    ``track=False`` (live mode: the snapshot holds no progress stats) leaves the
    progress counts at zero instead of reporting everything as missing.
    """
    challenges = cat.section("challenges")
    counts: dict[str, list[int]] = {}
    for location in cat.section("locations").values():
        world = location.get("map") or ""
        entry = counts.setdefault(world, [0, 0, 0])
        entry[0] += 1
        if location.get("challenge") in challenges and cat.project(world, location["x"], location["y"]):
            entry[2] += 1
            if track and challenge_state(data, location["challenge"])["done"]:
                entry[1] += 1
    rows = []
    for world, info in (cat.maps().get("maps") or {}).items():
        total, done, driven = counts.get(world, [0, 0, 0])
        rows.append({"key": world, "title": map_title(world, lang, templates), "points": total,
                     "done": done, "total": driven if track else 0, "area_key": world_area(world),
                     "_order": driven})
    # Same order with or without tracking (live mode keeps the offline ordering).
    rows.sort(key=lambda row: (row["key"] != "World_P", row["area_key"] != "", -row["_order"], row["title"]))
    for row in rows:
        del row["_order"]
    return rows


def world_area(world: str) -> str:
    stem = world[:-2] if world.endswith("_P") else world
    area = stem.split("_", 1)[0].lower()
    return area if area in (cat.catalog().get("areas") or {}) else ""


def map_markers(data: dict[str, Any], world: str, lang: str,
                overrides: dict[str, str] | None = None, track: bool = True) -> list[dict[str, Any]]:
    """Every discovery point of ``world`` that lands on the map artwork.

    ``track=False`` reports every point as untracked (``done`` None); used in
    live mode where the collected state is not readable.
    """
    challenges = cat.section("challenges")
    types = cat.section("location_types")
    titles: dict[str, str] = {}
    for category, entry in _collectible_index().items():
        if any((item.get("location") or {}).get("map") == world
               for group in entry["groups"].values() for item in group):
            for row in collectible_items(data, category, lang, overrides):
                titles[row["stat"]] = row["title"]
    markers = []
    for location_id, location in cat.section("locations").items():
        if location.get("map") != world or location.get("type") in HIDDEN_TYPES:
            continue
        uv = cat.project(world, location["x"], location["y"])
        if not uv:
            continue
        raw_type = location.get("type") or ""
        type_key = layer_key(raw_type)
        # Keep the variant's own icon (bounty-pack stations etc.), falling back to the layer's.
        type_row = types.get(raw_type) or {}
        layer_row = types.get(type_key) or {}
        icon = type_row.get("icon") or layer_row.get("icon") or ""
        icon_done = type_row.get("icon_done") or layer_row.get("icon_done") or ""
        challenge = location.get("challenge") or ""
        row = challenges.get(challenge) or {}
        stat = str(row.get("stat") or "")
        done = challenge_state(data, challenge)["done"] if row and track else None
        title = titles.get(stat) or _place_title(location, lang) or _type_title(type_key, lang)
        markers.append({
            "id": location_id,
            "u": uv[0],
            "v": uv[1],
            "x": location["x"],
            "y": location["y"],
            "z": location.get("z", 0.0),
            "type": type_key,
            "type_title": _type_title(type_key, lang),
            "group": layer_group(type_key),
            "title": title,
            "stat": stat if is_item_collectible(stat) else "",
            "challenge": challenge,
            "done": done,
            "icon": icon or icon_done,
            "icon_done": icon_done or icon,
        })
    return markers


# --------------------------------------------------------------------------- #
# Live teleport (bl4_live ``teleport_position`` runtime action)
# --------------------------------------------------------------------------- #
# Discovery points are the object's own actor location (a wall symbol, a crate);
# lift the target a little so the pawn is not placed inside the floor. The game
# side (K2_TeleportTo) still resolves collisions and reports failure.
TELEPORT_Z_LIFT = 100.0


def teleport_target(location_id: str, lift: float = TELEPORT_Z_LIFT) -> dict[str, Any] | None:
    """Payload for ``teleport_position``: the location's map and world position."""
    location = cat.section("locations").get(str(location_id or ""))
    if not location or not location.get("map"):
        return None
    return {"map": str(location["map"]), "x": float(location["x"]), "y": float(location["y"]),
            "z": float(location.get("z", 0.0)) + float(lift)}


def same_map(first: Any, second: Any) -> bool:
    """Runtime world names and catalog map names compare case-insensitively."""
    return bool(str(first or "").strip()) and str(first).strip().casefold() == str(second or "").strip().casefold()


def live_player_marker(position: dict[str, Any] | None, world: str) -> dict[str, Any]:
    """Project the live player position (runtime ``state.position``) onto ``world``.

    Returns ``available`` (a usable position was reported), ``map`` and, when
    the player stands on ``world`` inside its artwork, ``on_map`` with ``u``/``v``
    and a screen ``heading`` in degrees (0 = right, clockwise) derived from yaw.
    """
    position = position if isinstance(position, dict) else {}
    player_map = str(position.get("map") or "").strip()
    available = bool(position.get("available", True)) and bool(player_map) and all(
        isinstance(position.get(key), (int, float)) for key in ("x", "y", "z"))
    row: dict[str, Any] = {"available": available, "map": player_map, "on_map": False,
                           "u": 0.0, "v": 0.0, "heading": 0.0}
    if not available:
        return row
    row.update({key: float(position[key]) for key in ("x", "y", "z")})
    if not same_map(player_map, world):
        return row
    uv = cat.project(world, row["x"], row["y"])
    if not uv:
        return row
    row.update({"on_map": True, "u": uv[0], "v": uv[1]})
    yaw = position.get("yaw")
    if isinstance(yaw, (int, float)):
        radians = math.radians(float(yaw))
        ahead = cat.project(world, row["x"] + 100.0 * math.cos(radians), row["y"] + 100.0 * math.sin(radians))
        if ahead:
            row["heading"] = math.degrees(math.atan2(ahead[1] - uv[1], ahead[0] - uv[0]))
    return row


# --------------------------------------------------------------------------- #
# Missions
# --------------------------------------------------------------------------- #
# Save layout: missions.local_sets.<set>.{status, missions.<mission>.{status,
# final, objectives, cursorposition, state}}. A finished mission is
# ``status: completed`` (+ the endstate facts the game recorded in ``final``);
# an absent entry means "not started". Contracts, events and dynamic events
# have no mission set and are never persisted, so they are not listed.
MISSION_KIND_ORDER = ("main", "side", "micro", "activity")
_MISSION_KINDS = {
    "MainMission": "main", "DLC_MainStory": "main",
    "SideMission": "side", "DLC_SideMission": "side", "FactionMission": "side",
    "MicroMission": "micro", "DLC_MicroMission": "micro",
}
_TRANSIENT_MISSION_TYPES = frozenset({"Contract", "Event", "DynamicEvent", "", "Test"})
# Set-key tokens -> content area (catalog ``areas`` keys; "extra" = bounty packs,
# raids, takedowns and other add-ons without an area of their own).
_MISSION_AREA_TOKENS = (("_cowbell", "cowbell"), ("_dlc1", "cowbell"), ("_harmonica", "harmonica"),
                        ("_dlc2", "harmonica"), ("_cello", "cello"), ("_banjo", "banjo"))
_EXTRA_MISSION_TOKENS = ("_dlc", "_raid", "_pearlgen", "_mandolin", "circleofslaughter", "replaychallenge")
MISSION_AREA_ORDER = ("", "cowbell", "harmonica", "cello", "banjo", "extra")


def mission_kind(mission_type: str) -> str:
    return _MISSION_KINDS.get(str(mission_type or ""), "activity")


def mission_area(set_key: str) -> str:
    key = str(set_key or "").lower()
    for token, area in _MISSION_AREA_TOKENS:
        if token in key:
            return area
    return "extra" if any(token in key for token in _EXTRA_MISSION_TOKENS) else ""


@lru_cache(maxsize=1)
def _mission_index() -> dict[str, dict[str, Any]]:
    """Listed missions (persisted kinds with a title) in story/set order."""
    sets = cat.section("mission_sets")
    order: dict[str, int] = {}

    def visit(set_key: str, trail: tuple[str, ...] = ()) -> int:
        if set_key in order:
            return order[set_key]
        if set_key in trail:
            return 0
        requires = (sets.get(set_key) or {}).get("requires") or []
        depth = 1 + max((visit(parent, trail + (set_key,)) for parent in requires if parent in sets), default=-1)
        order[set_key] = depth
        return depth

    rows: dict[str, dict[str, Any]] = {}
    for key, row in cat.section("missions").items():
        set_key = row.get("set") or ""
        title = cat.text(row.get("title"), "en-US")
        # Invisible helper missions (intros, "_INVIS" kickoffs) carry their internal name as title.
        internal = bool(re.fullmatch(r"[A-Za-z0-9_]+", title)) and "_" in title
        if (not set_key or row.get("type") in _TRANSIENT_MISSION_TYPES or "template" in key
                or "repeatable" in key or not title or internal):
            continue
        members = (sets.get(set_key) or {}).get("missions") or []
        rows[key] = {
            "set": set_key,
            "kind": mission_kind(row.get("type")),
            "area": mission_area(set_key),
            "sort": (visit(set_key), set_key, members.index(key) if key in members else 99, key),
        }
    return dict(sorted(rows.items(), key=lambda item: item[1]["sort"]))


def _mission_templates() -> dict[str, Any]:
    from .unlock_data import MISSIONSETS
    from .unlock_logic import ensure_legacy_unlock_data

    ensure_legacy_unlock_data()
    return MISSIONSETS


def _local_sets(data: dict[str, Any], create: bool = False) -> dict[str, Any]:
    if create:
        return get_or_create_dict(get_or_create_dict(data, "missions"), "local_sets")
    missions = data.get("missions") if isinstance(data, dict) else None
    sets = missions.get("local_sets") if isinstance(missions, dict) else None
    return sets if isinstance(sets, dict) else {}


def _mission_node(data: dict[str, Any], mission_key: str) -> dict[str, Any] | None:
    info = _mission_index().get(mission_key) or {}
    set_node = _local_sets(data).get(info.get("set", ""))
    missions = set_node.get("missions") if isinstance(set_node, dict) else None
    node = missions.get(mission_key) if isinstance(missions, dict) else None
    return node if isinstance(node, dict) else None


_GAME_MARKUP = re.compile(r"\[/?boldtext\]", re.IGNORECASE)


def game_text(text: Any) -> str:
    """Game UI text without its markup: ``[newline]`` becomes a line break."""
    value = _GAME_MARKUP.sub("", str(text or "")).replace("[newline]", "\n")
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _objective_state(status: Any) -> str:
    text = str(status or "").lower()
    if text.startswith("completed"):
        return "done"
    if text.startswith("deactivated"):
        return "skipped"
    if text.startswith("active"):
        return "active"
    return "pending"


def mission_state(data: dict[str, Any], mission_key: str) -> str:
    """``done`` / ``active`` / ``none`` for one listed mission."""
    node = _mission_node(data, mission_key)
    if node is None:
        return "none"
    return "done" if str(node.get("status") or "").lower() == "completed" else "active"


def mission_objectives(data: dict[str, Any], mission_key: str, lang: str) -> list[dict[str, Any]]:
    """Visible objectives with their saved state (only meaningful while active)."""
    row = cat.section("missions").get(mission_key) or {}
    node = _mission_node(data, mission_key) or {}
    saved = node.get("objectives") if isinstance(node.get("objectives"), dict) else {}
    finished = str(node.get("status") or "").lower() == "completed"
    out = []
    for objective in row.get("objectives") or []:
        text = game_text(cat.text(objective.get("text"), lang))
        if not text:
            continue
        entry = saved.get(objective.get("id")) or {}
        out.append({"id": objective.get("id"), "text": text, "child": bool(objective.get("parent")),
                    "state": "done" if finished else _objective_state(entry.get("status"))})
    return out


def mission_categories(data: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    """Area x kind categories (``<area>:<kind>``) with completion counts."""
    counts: dict[str, list[int]] = {}
    for key, info in _mission_index().items():
        entry = counts.setdefault(f"{info['area']}:{info['kind']}", [0, 0])
        entry[1] += 1
        entry[0] += int(mission_state(data, key) == "done")
    rows = []
    for category, (done, total) in counts.items():
        area, kind = category.split(":", 1)
        rows.append({"key": category, "area_key": area, "kind": kind, "done": done, "total": total})
    rows.sort(key=lambda row: (MISSION_AREA_ORDER.index(row["area_key"]) if row["area_key"] in MISSION_AREA_ORDER else 99,
                               MISSION_KIND_ORDER.index(row["kind"])))
    return rows


def missions_in_category(category: str) -> list[str]:
    area, _, kind = str(category).partition(":")
    return [key for key, info in _mission_index().items() if info["area"] == area and info["kind"] == kind]


def mission_template(mission_key: str) -> dict[str, Any] | None:
    """Completed state captured from a real save, when the editor ships one."""
    info = _mission_index().get(mission_key) or {}
    template = ((_mission_templates().get(info.get("set", "")) or {}).get("missions") or {}).get(mission_key)
    return template if isinstance(template, dict) else None


def _set_members(set_key: str) -> list[str]:
    template = _mission_templates().get(set_key)
    if isinstance(template, dict) and isinstance(template.get("missions"), dict):
        return list(template["missions"])
    return [key for key, info in _mission_index().items() if info["set"] == set_key]


def _mark_set_if_finished(local_sets: dict[str, Any], set_key: str) -> None:
    node = local_sets.get(set_key)
    if not isinstance(node, dict):
        return
    missions = node.get("missions") if isinstance(node.get("missions"), dict) else {}
    members = _set_members(set_key)
    if not members or not all(str((missions.get(key) or {}).get("status") or "").lower() == "completed"
                              for key in members):
        return
    template = _mission_templates().get(set_key)
    if isinstance(template, dict):
        status = template.get("status")
    else:
        # Activity and micro containers carry no set status in real saves.
        status = None if ("zoneactivity" in set_key or set_key.startswith("missionset_micro_")) else "completed"
    if status:
        node["status"] = status


def complete_mission(data: dict[str, Any], mission_key: str) -> bool:
    """Write the finished state (captured template, else the minimal ``completed``)."""
    info = _mission_index().get(mission_key)
    if not info or mission_state(data, mission_key) == "done":
        return False
    local_sets = _local_sets(data, create=True)
    set_node = local_sets.get(info["set"])
    if not isinstance(set_node, dict):
        set_node = local_sets[info["set"]] = {}
    missions = get_or_create_dict(set_node, "missions")
    template = mission_template(mission_key)
    if template:
        missions[mission_key] = copy.deepcopy(template)
    else:
        # No captured template: keep the facts the game already recorded for an
        # active mission (choices such as "deactivated" branches) and drop only
        # the in-progress bookkeeping (objectives, cursor, entry point).
        previous = missions.get(mission_key) if isinstance(missions.get(mission_key), dict) else {}
        state: dict[str, Any] = {"status": "completed"}
        for field in ("ui_flags", "final"):
            if field in previous:
                state[field] = copy.deepcopy(previous[field])
        missions[mission_key] = state
    tracked = (data.get("missions") or {}).get("tracked_missions")
    if isinstance(tracked, list) and mission_key in tracked:
        data["missions"]["tracked_missions"] = [key for key in tracked if key != mission_key] or ["none"]
    _mark_set_if_finished(local_sets, info["set"])
    return True


def reset_mission(data: dict[str, Any], mission_key: str, allow_main: bool = False) -> bool:
    """Forget one mission so the game offers it again (main story only on request)."""
    info = _mission_index().get(mission_key)
    if not info or (info["kind"] == "main" and not allow_main) or mission_state(data, mission_key) == "none":
        return False
    local_sets = _local_sets(data)
    set_node = local_sets.get(info["set"])
    missions = set_node.get("missions") if isinstance(set_node, dict) else None
    if not isinstance(missions, dict) or mission_key not in missions:
        return False
    del missions[mission_key]
    set_node.pop("status", None)
    if not missions:
        del local_sets[info["set"]]
    return True


def main_prerequisites(mission_key: str) -> list[str]:
    """Earlier main missions of the same story line (``requires`` chain, story order)."""
    info = _mission_index().get(mission_key)
    if not info or info["kind"] != "main":
        return []
    sets = cat.section("mission_sets")
    needed: set[str] = set()
    stack = list((sets.get(info["set"]) or {}).get("requires") or [])
    while stack:
        set_key = stack.pop()
        if set_key in needed:
            continue
        needed.add(set_key)
        stack.extend((sets.get(set_key) or {}).get("requires") or [])
    earlier_in_set = [key for key, row in _mission_index().items()
                      if row["set"] == info["set"] and row["sort"] < info["sort"]]
    return [key for key, row in _mission_index().items()
            if row["kind"] == "main" and row["set"] in needed] + earlier_in_set


def complete_main_through(data: dict[str, Any], mission_key: str) -> int:
    """Complete a main mission together with every earlier main mission it depends on."""
    changed = sum(complete_mission(data, key) for key in main_prerequisites(mission_key))
    return changed + int(complete_mission(data, mission_key))


# --------------------------------------------------------------------------- #
# Live progress (bl4_live ``progress_facts``)
# --------------------------------------------------------------------------- #
# The game keeps progress in its fact store under the same names the save uses:
#   save missions.local_sets.<set>.status                          <-> missions.<set>.status
#   save missions.local_sets.<set>.missions.<m>.status             <-> missions.<set>.<m>.status
#   save ....missions.<m>.objectives.<o>.status                    <-> missions.<set>.<m>.<o>.status
#   save stats.<path>                                               <-> stats.<path>
#   save globals.<key>                                              <-> global.<key>
# A live read builds a save-shaped snapshot so the offline views work unchanged.
LIVE_GLOBALS = ("vault_hunter_level", "highest_unlocked_vault_hunter_level")


@lru_cache(maxsize=1)
def live_fact_plan() -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """(fact address, save path, value kind) for every listed mission and tracked stat."""
    plan: list[tuple[str, tuple[str, ...], str]] = []
    sets: set[str] = set()
    for key, info in _mission_index().items():
        sets.add(info["set"])
        plan.append((f"missions.{info['set']}.{key}.status",
                     ("missions", "local_sets", info["set"], "missions", key, "status"), "name"))
    for set_key in sorted(sets):
        plan.append((f"missions.{set_key}.status", ("missions", "local_sets", set_key, "status"), "name"))
    stats = {str(row.get("stat") or "") for row in cat.section("challenges").values()}
    stats |= set(_item_collectible_stats())
    stats = {stat for stat in stats if stat.startswith("stats.") and stat.count(".") >= 1}
    # Parent nodes report aggregates; the views count leaves themselves, like with a save.
    leaves = {stat for stat in stats if not any(other.startswith(stat + ".") for other in stats)}
    for stat in sorted(leaves):
        plan.append((stat, tuple(stat.split(".")), "int"))
    for key in LIVE_GLOBALS:
        plan.append((f"global.{key}", ("globals", key), "int"))
    return tuple(plan)


def live_objective_plan(snapshot: dict[str, Any]) -> list[tuple[str, tuple[str, ...], str]]:
    """Second pass: objective states of the missions the live read found in progress."""
    plan = []
    for key, info in _mission_index().items():
        if mission_state(snapshot, key) != "active":
            continue
        for objective in (cat.section("missions").get(key) or {}).get("objectives") or []:
            obj = str(objective.get("id") or "")
            if obj:
                plan.append((f"missions.{info['set']}.{key}.{obj}.status",
                             ("missions", "local_sets", info["set"], "missions", key, "objectives", obj, "status"),
                             "name"))
    return plan


def apply_live_facts(snapshot: dict[str, Any], plan: Any, values: list[Any]) -> int:
    """Write ``progress_facts`` values into a save-shaped dict; unset facts stay absent."""
    written = 0
    for (_address, path, kind), value in zip(plan, values):
        if not value:
            continue
        name, number = str(value[0]), int(value[1])
        node = snapshot
        for key in path[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = node[key] = {}
            node = child
        node[path[-1]] = name if kind == "name" else number
        written += 1
    return written
