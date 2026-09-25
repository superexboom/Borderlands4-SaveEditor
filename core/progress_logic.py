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
