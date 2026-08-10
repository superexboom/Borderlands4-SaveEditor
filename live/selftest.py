"""Standalone verification for the live bridge -- does NOT touch the editor GUI.

Run from the project root:
    python -m live.selftest

It connects to the in-game bl4_live server, pulls the backpack, wraps it in the
save-shaped dict, and runs it through the REAL editor pipeline
(process_and_load_items) to prove the integration is seamless.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# project root on sys.path so `core` / `live` import cleanly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from live.bridge import Bridge, BridgeError  # noqa: E402
from live.adapter import fetch_live_yaml  # noqa: E402


def main() -> int:
    b = Bridge()
    print(f"[1] ping {b.host}:{b.port} ...", end=" ", flush=True)
    if not b.ping():
        print("NO RESPONSE")
        print("    -> start the game, load a save, and ensure bl4_live is loaded")
        return 1
    print("OK")

    print("[2] info ...", end=" ", flush=True)
    try:
        info = b.info()
        print("OK", info)
    except BridgeError as e:
        print("FAILED:", e)
        return 1

    print("[3] list ...", end=" ", flush=True)
    try:
        lst = b.list()
        for c in lst.get("containers", []):
            print(f"     {c['container']}: {c['slots']} slots")
    except BridgeError as e:
        print("FAILED:", e)
        return 1

    print("[4] read all items ...", end=" ", flush=True)
    t0 = time.perf_counter()
    try:
        yaml_like = fetch_live_yaml(b)
    except BridgeError as e:
        print("FAILED:", e)
        return 1
    dt = time.perf_counter() - t0
    inv = yaml_like["state"]["inventory"]["items"]
    n_bp = len(inv["backpack"])
    n_bank = len(inv["bank"])
    print(f"OK  backpack={n_bp} bank={n_bank}  ({dt*1000:.0f} ms)")

    print("[5] feed into editor pipeline (process_and_load_items) ...", end=" ", flush=True)
    t0 = time.perf_counter()
    import core.bl4_functions as f  # noqa: E402
    items = f.process_and_load_items(yaml_like)
    dt = time.perf_counter() - t0
    print(f"OK  {len(items)} items  ({dt*1000:.0f} ms)")

    print()
    print("sample (first 6):")
    for it in items[:6]:
        print(f"   [{it.get('container'):<9}] {str(it.get('slot')):<8} "
              f"{str(it.get('name'))[:24]:<26} {str(it.get('manufacturer_en') or it.get('manufacturer')):<10} "
              f"lvl={it.get('level')} {it.get('rarity')}")

    # sanity: container classification must work
    containers = {it.get("container") for it in items}
    print()
    print("containers seen:", sorted(c for c in containers if c))
    if not containers or containers == {"Unknown"}:
        print("!! WARNING: container classification failed -- check path shape")
        return 1

    print()
    print("SELF-TEST PASSED: live game items flow through the editor pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
