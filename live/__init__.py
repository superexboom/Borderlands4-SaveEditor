"""Live-mode bridge for sav_edit.

Connects the editor to the bl4_live mod running inside Borderlands 4.
Read-only for now -- no writes until the write semantics are validated.

Usage (headless):
    from live.bridge import Bridge
    from live.adapter import fetch_live_yaml

    b = Bridge()
    if b.ping():
        yaml_like = fetch_live_yaml(b)
        # feed yaml_like into core.bl4_functions.process_and_load_items(...)
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
