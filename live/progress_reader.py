"""Read the running game's progress into a save-shaped snapshot (bl4_live progress probe).

Two passes over ``progress_facts``: missions/stats/globals from the catalog,
then the objectives of the missions that turned out to be in progress. The
mod caps each request at a few milliseconds of game-thread time.
"""

from __future__ import annotations

import time
from typing import Any

from core import progress_logic as logic

from .bridge import Bridge


def read_live_progress(bridge: Bridge) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    snapshot: dict[str, Any] = {}
    # Which progress_* actions this mod build offers (writes are newer than reads).
    caps = bridge.runtime_action("progress_capabilities")
    actions = [str(action) for action in caps.get("actions") or []] if caps.get("ok") else []
    plan = logic.live_fact_plan()
    values, meta = bridge.progress_facts([address for address, _path, _kind in plan])
    written = logic.apply_live_facts(snapshot, plan, values)
    objectives = logic.live_objective_plan(snapshot)
    if objectives:
        more, second = bridge.progress_facts([address for address, _path, _kind in objectives])
        written += logic.apply_live_facts(snapshot, objectives, more)
        meta["requests"] += second["requests"]
        meta["game_ms"] += second["game_ms"]
    meta.update({
        "facts": len(plan) + len(objectives),
        "set": written,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "game_ms": round(meta["game_ms"], 1),
        "read_at": time.time(),
        "actions": actions,
    })
    return snapshot, meta
