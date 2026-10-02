"""Skill graph names <-> live node indices (core/data/skill_graphs.json, from the pipeline).

Saves store skills as ``progression.graphs[] = {name, nodes: [{name, points_spent | is_activated}]}``;
the live mod's ``skill_snapshot`` / ``skill_apply`` address nodes by index.  Node names
compare case-insensitively (they are FNames: saves write "HUNTER" for "Hunter").
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from . import resource_loader

# Point pools of character skill trees and specializations (SDU / vault powers are account-wide).
SKILL_POOLS = ("CharacterProgressPoints", "SpecializationTokenPool")


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    data = resource_loader.load_json_resource("core/data/skill_graphs.json")
    return data.get("graphs", {}) if isinstance(data, dict) else {}


def node_names(graph: str) -> list[str]:
    entry = catalog().get(str(graph or "").lower()) or {}
    return [str(node.get("name") or "") for node in entry.get("nodes") or []]


def snapshot_to_save_graphs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Live ``skill_snapshot`` -> save-format skill graphs (only nodes with points / activation)."""
    out = []
    for graph in snapshot.get("graphs") or []:
        if graph.get("pool") not in SKILL_POOLS:
            continue
        names = node_names(graph.get("graph"))
        nodes = []
        for row in graph.get("nodes") or []:
            index = int(row.get("i", -1))
            if not 0 <= index < len(names):
                continue
            node = {"name": names[index]}
            if row.get("spent"):
                node["points_spent"] = int(row["spent"])
            if graph.get("type") == 1 and row.get("active"):
                node["is_activated"] = True
            if row.get("bonus"):
                node["bonus_points"] = int(row["bonus"])
            if len(node) > 1:
                nodes.append(node)
        out.append({"name": graph.get("graph"), "nodes": nodes})
    return out


def save_graphs_to_apply(skill_graphs: list[dict[str, Any]], *, bonus: bool = False) -> tuple[dict[str, Any], list[str]]:
    """Save-format skill graphs -> ``skill_apply`` payload, plus the names that did not resolve."""
    graphs, unknown = [], []
    for graph in skill_graphs or []:
        name = str(graph.get("name") or "")
        names = [value.lower() for value in node_names(name)]
        if not names:
            unknown.append(name)
            continue
        nodes = []
        for node in graph.get("nodes") or []:
            key = str(node.get("name") or "").lower()
            if key not in names:
                unknown.append(f"{name}/{node.get('name')}")
                continue
            row = {"i": names.index(key), "spent": int(node.get("points_spent") or 0),
                   "active": bool(node.get("is_activated"))}
            if bonus:
                row["bonus"] = int(node.get("bonus_points") or 0)
            nodes.append(row)
        if bonus:
            # exact rebuild: nodes the save does not list have no points and no bonus
            listed = {row["i"] for row in nodes}
            nodes += [{"i": i, "spent": 0, "active": False, "bonus": 0}
                      for i in range(len(names)) if i not in listed]
        graphs.append({"graph": name, "nodes": nodes})
    payload = {"graphs": graphs, "reset_pools": list(SKILL_POOLS)}
    if bonus:
        payload["bonus"] = True
    return payload, unknown
