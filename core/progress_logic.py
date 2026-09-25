"""Read/write helpers behind the "Game Progress" page.

Pure functions over the decoded save dict (character or profile save) so the
view model, the character-page presets and tests share one implementation.
Display metadata comes from :mod:`core.progress_catalog`.
"""

from __future__ import annotations

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
    local_sets = ((data.get("missions") or {}).get("local_sets") or {}) if isinstance(data.get("missions"), dict) else {}
    completed = set()
    for mission_set in local_sets.values():
        for key, mission in ((mission_set or {}).get("missions") or {}).items():
            if str((mission or {}).get("status") or "").lower() == "completed":
                completed.add(str(key).lower())
    main = [key for key, row in missions.items() if row.get("type") == "MainMission"]

    challenges = cat.section("challenges")
    item_collectibles = [row for row in challenges.values() if is_item_collectible(row.get("stat", ""))]
    collected = sum(1 for row in item_collectibles if challenge_value(data, row) >= max(row.get("goals") or [1]))

    menu = [challenges[key] for category in cat.catalog().get("challenge_categories") or []
            for key in category.get("challenges") or [] if key in challenges]
    menu_done = sum(1 for row in menu if row.get("goals") and challenge_value(data, row) >= max(row["goals"]))
    return {
        "missions_completed": len(completed),
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


def map_title(world: str, lang: str) -> str:
    """Readable map name: base maps use region titles, DLC maps their area name."""
    if world in _MAP_REGIONS:
        return cat.region_title(_MAP_REGIONS[world], lang)
    stem = world[:-2] if world.endswith("_P") else world
    area = stem.split("_", 1)[0].lower()
    if area in (cat.catalog().get("areas") or {}) and "_" not in stem:
        return area_title(area, lang)
    return stem.replace("_", " ")
