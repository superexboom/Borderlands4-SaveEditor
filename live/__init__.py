"""Live-mode bridge for sav_edit.

Connects the editor to the bl4_live mod running inside Borderlands 4 over
localhost TCP (127.0.0.1:28777). Read + write (apply) + spawn.

Usage (headless):
    from live.bridge import Bridge
    from live.adapter import fetch_live_yaml

    b = Bridge()
    if b.ping():
        yaml_like = fetch_live_yaml(b)   # feed into process_and_load_items(...)
        res = b.apply(idx, new_serial)   # identity overwrite; weapons reload fully on re-entry
        res = b.spawn(new_serial)        # game materializes one final serial
        res = b.spawn_many(serials)      # compact native batch delivery
        player = b.player()              # live name / character level / spec level
        res = b.runtime_action(action)   # bounded session-only runtime action
"""

from .bridge import Bridge, BridgeError
from .adapter import fetch_live_items, fetch_live_yaml, items_to_yaml

__all__ = [
    "Bridge",
    "BridgeError",
    "fetch_live_items",
    "fetch_live_yaml",
    "items_to_yaml",
]
