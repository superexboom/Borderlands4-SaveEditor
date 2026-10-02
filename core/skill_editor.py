"""Live skill tree editor: ``skill_snapshot`` -> editable state -> ``skill_apply`` payload.

The state covers the character's own point pools (``skill_graphs.SKILL_POOLS``):
skill trees and specializations, plus the activation graphs in those pools (action
skill choice, augments / capstones, specialization perks).  Graph roles come from
the progress_graph template each graph inherits from (core/data/skill_graphs.json):

- ``progress_graph_action_skills_template``: nodes 0-2 are the action skills (one is
  active), node 3 the class trait and 4 the shared skill (always on; never edited);
- ``progress_graph_askill_modifiers_template``: nodes 0-4 augments, 5-7 capstones
  (one of each per action skill).

The game validates points, tiers and prerequisites itself when the payload is
applied; ``skill_apply`` reports what did not take.  Bonus points (overlimit) cost
no pool points.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from . import resource_loader
from .skill_graphs import SKILL_POOLS, catalog, node_names

ACTION_TEMPLATE = "progress_graph_action_skills_template"
MODIFIER_TEMPLATE = "progress_graph_askill_modifiers_template"
ACTION_SKILL_COUNT = 3
AUGMENT_COUNT = 5
BONUS_MAX = 99
SPECIALIZATION_MAX = 100


def _ancestors(graph: str) -> list[str]:
    graphs, out, key = catalog(), [], str(graph or "").lower()
    while key and key not in out:
        out.append(key)
        key = str((graphs.get(key) or {}).get("parent") or "").lower()
    return out


def graph_kind(graph: str, graph_type: int) -> str:
    """``points`` | ``action_skills`` | ``modifiers`` | ``choices`` (other activation graphs)."""
    chain = _ancestors(graph)
    if ACTION_TEMPLATE in chain:
        return "action_skills"
    if MODIFIER_TEMPLATE in chain:
        return "modifiers"
    return "points" if int(graph_type) == 0 else "choices"


def _node_group(kind: str, index: int) -> str:
    if kind == "action_skills":
        return "action" if index < ACTION_SKILL_COUNT else ""
    if kind == "modifiers":
        return "augment" if index < AUGMENT_COUNT else "capstone"
    return ""


def build_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Editable state from a live ``skill_snapshot`` (the character's own pools only)."""
    acquired = list(snapshot.get("points_per_pool") or [])
    pools = {pool: int(acquired[i]) if i < len(acquired) else 0 for i, pool in enumerate(SKILL_POOLS)}
    graphs = []
    for graph in snapshot.get("graphs") or []:
        if graph.get("pool") not in SKILL_POOLS:
            continue
        name = str(graph.get("graph") or "")
        entry = catalog().get(name.lower()) or {}
        names = entry.get("nodes") or []
        kind = graph_kind(name, int(graph.get("type") or 0))
        nodes = []
        for row in graph.get("nodes") or []:
            index = int(row.get("i", -1))
            info = names[index] if 0 <= index < len(names) else {}
            limit = int(info.get("max") or 0)
            if kind == "points" and graph.get("pool") == "SpecializationTokenPool":
                limit = limit or SPECIALIZATION_MAX
            group = _node_group(kind, index)
            nodes.append({
                "i": index,
                "name": str(info.get("name") or f"#{index}"),
                "max": limit,
                "spent": int(row.get("spent") or 0),
                "bonus": int(row.get("bonus") or 0),
                "active": bool(row.get("active")),
                "level": int(row.get("level") or 0),
                "group": group,
                # trait / shared skill: always on, never part of a choice
                "fixed": kind == "action_skills" and not group,
            })
        graphs.append({"graph": name, "type": int(graph.get("type") or 0), "pool": graph.get("pool"),
                       "kind": kind, "nodes": nodes})
    return {"pools": pools, "graphs": graphs}


def _node(state: dict[str, Any], graph: str, index: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for entry in state.get("graphs") or []:
        if entry["graph"] == graph:
            for node in entry["nodes"]:
                if node["i"] == index:
                    return entry, node
    return None


def set_spent(state: dict[str, Any], graph: str, index: int, value: int) -> bool:
    found = _node(state, graph, index)
    if found is None or found[0]["type"] != 0:
        return False
    node = found[1]
    value = max(0, min(int(node["max"]), int(value)))
    changed = value != node["spent"]
    node["spent"] = value
    return changed


def set_bonus(state: dict[str, Any], graph: str, index: int, value: int) -> bool:
    found = _node(state, graph, index)
    if found is None or found[0]["type"] != 0:
        return False
    node = found[1]
    value = max(0, min(BONUS_MAX, int(value)))
    changed = value != node["bonus"]
    node["bonus"] = value
    return changed


def set_active(state: dict[str, Any], graph: str, index: int, on: bool) -> bool:
    """Toggle an activation node; turning one on turns the rest of its group off.

    The equipped action skill can only be switched, never left empty.
    """
    found = _node(state, graph, index)
    if found is None or found[0]["type"] != 1 or found[1]["fixed"]:
        return False
    entry, node = found
    if not on and node["group"] == "action":
        return False
    if bool(on) == node["active"]:
        return False
    node["active"] = bool(on)
    if on and node["group"]:
        for other in entry["nodes"]:
            if other is not node and other["group"] == node["group"]:
                other["active"] = False
    return True


def bonus_invested(state: dict[str, Any], value: int) -> int:
    """Set the bonus of every skill-tree node that has points (character pool); returns the count."""
    count = 0
    for entry in state.get("graphs") or []:
        if entry["kind"] != "points" or entry["pool"] != SKILL_POOLS[0]:
            continue
        for node in entry["nodes"]:
            if node["spent"] > 0:
                set_bonus(state, entry["graph"], node["i"], value)
                count += 1
    return count


def clear_bonus(state: dict[str, Any]) -> None:
    for entry in state.get("graphs") or []:
        for node in entry["nodes"]:
            node["bonus"] = 0


def max_trees(state: dict[str, Any]) -> None:
    """Every skill-tree node at its maximum (the game stops at the pool / tier limits)."""
    for entry in state.get("graphs") or []:
        if entry["kind"] == "points" and entry["pool"] == SKILL_POOLS[0]:
            for node in entry["nodes"]:
                node["spent"] = node["max"]


def clear_points(state: dict[str, Any], pool: str = SKILL_POOLS[0]) -> None:
    for entry in state.get("graphs") or []:
        if entry["type"] == 0 and entry["pool"] == pool:
            for node in entry["nodes"]:
                node["spent"] = 0


def pool_usage(state: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """pool -> (points spent in the state, points the character has)."""
    usage = {}
    for pool, total in (state.get("pools") or {}).items():
        spent = sum(node["spent"] for entry in state.get("graphs") or []
                    if entry["type"] == 0 and entry["pool"] == pool for node in entry["nodes"])
        usage[pool] = (spent, int(total))
    return usage


def apply_payload(state: dict[str, Any]) -> dict[str, Any]:
    """``skill_apply`` params that rebuild exactly this state (every node, bonus included)."""
    graphs = [{"graph": entry["graph"],
               "nodes": [{"i": node["i"], "spent": node["spent"], "active": node["active"],
                          "level": node["level"], "bonus": node["bonus"]} for node in entry["nodes"]]}
              for entry in state.get("graphs") or []]
    return {"graphs": graphs, "reset_pools": list(SKILL_POOLS), "bonus": True}


def differs(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    return apply_payload(a or {}) != apply_payload(b or {})


def clone(state: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(state)


@lru_cache(maxsize=1)
def layout() -> dict[str, Any]:
    """core/data/skill_layout.json (pipeline ``export-skill-layout``): the game's skill screens."""
    data = resource_loader.load_json_resource("core/data/skill_layout.json")
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _layout_cells() -> dict[tuple[str, int], dict[str, Any]]:
    cells: dict[tuple[str, int], dict[str, Any]] = {}

    def add(cell: dict[str, Any]) -> None:
        if cell.get("graph") and int(cell.get("index", -1)) >= 0:
            cells.setdefault((cell["graph"].casefold(), int(cell["index"])), cell)

    for entry in (layout().get("classes") or {}).values():
        for tree in entry.get("trees") or []:
            add(tree.get("action") or {})
            for segment in tree.get("segments") or []:
                for row in segment.get("rows") or []:
                    for cell in row:
                        add(cell)
    for tree in (layout().get("specializations") or {}).get("trees") or []:
        add(tree)
        for skill in tree.get("skills") or []:
            add(skill)
    return cells


def node_text(graph: str, node: str | int) -> tuple[dict[str, str], dict[str, str]]:
    """Localized (name, description) of a node, by index or by its save name; ({}, {}) if unknown."""
    if isinstance(node, str):
        names = [name.casefold() for name in node_names(graph)]
        if node.casefold() not in names:
            return {}, {}
        node = names.index(node.casefold())
    cell = _layout_cells().get((str(graph or "").casefold(), int(node))) or {}
    return dict(cell.get("name") or {}), dict(cell.get("desc") or {})
