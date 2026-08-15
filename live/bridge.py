"""Live bridge client for sav_edit.

Talks to the bl4_live mod inside Borderlands 4 over localhost TCP.
Length-prefixed JSON: [4-byte big-endian length][utf-8 json body].

This module is deliberately dependency-free and PyQt-free so it can be used
from a worker thread without touching the GUI thread.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

HOST = "127.0.0.1"
PORT = 28777
DEFAULT_TIMEOUT = 10.0


class BridgeError(RuntimeError):
    pass


class Bridge:
    """One-shot request/response client. A new connection per call keeps the
    game-side handler simple; the handshake cost is negligible on localhost."""

    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout

    # ---- transport -----------------------------------------------------
    def _roundtrip(self, req: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        body = json.dumps(req, ensure_ascii=False).encode("utf-8")
        to = self.timeout if timeout is None else timeout
        with socket.create_connection((self.host, self.port), timeout=to) as conn:
            conn.settimeout(to)
            conn.sendall(struct.pack(">I", len(body)) + body)
            hdr = self._recv(conn, 4)
            if not hdr:
                raise BridgeError("no response header")
            (n,) = struct.unpack(">I", hdr)
            if not (0 < n <= 1 << 24):
                raise BridgeError(f"bad response length {n}")
            payload = self._recv(conn, n)
            if payload is None:
                raise BridgeError("response truncated")
            resp = json.loads(payload.decode("utf-8"))
            if not isinstance(resp, dict):
                raise BridgeError("response not a JSON object")
            return resp

    @staticmethod
    def _recv(conn: socket.socket, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    # ---- API -----------------------------------------------------------
    def ping(self) -> bool:
        try:
            return bool(self._roundtrip({"id": 1, "op": "ping"}, timeout=3).get("pong"))
        except (OSError, BridgeError, ValueError):
            return False

    def info(self) -> dict[str, Any]:
        return self._roundtrip({"id": 1, "op": "info"}, timeout=5)

    def player(self) -> dict[str, Any]:
        """Read the active character's lightweight runtime identity/levels."""
        resp = self._roundtrip({"id": 1, "op": "player"}, timeout=5)
        if not resp.get("ok"):
            raise BridgeError(str(resp.get("error", "player read failed")))
        return resp

    def runtime_action(self, action: str, **params: Any) -> dict[str, Any]:
        """Run one bounded gameplay convenience action exposed by the SDK mod."""
        action = str(action or "").strip()
        req = {"id": 1, "op": "runtime", "action": action}
        req.update(params)
        resp = self._roundtrip(
            req,
            timeout=(90 if action == "apply_loadout"
                     else 30 if action in {"rebuild_item_cache", "publish_backpack_item"}
                     else 15 if action == "claim_lost_loot" else 5),
        )
        if "ok" not in resp:
            raise BridgeError("malformed runtime response")
        return resp

    def loadout_capabilities(self) -> dict[str, Any]:
        """Report whether the current live player exposes the safe loadout read chain."""
        return self.runtime_action("loadout_capabilities")

    def loadout_snapshot(self) -> dict[str, Any]:
        """Read equipped slots joined to their current backpack items and actors."""
        return self.runtime_action("loadout_snapshot")

    def loadout_recovery(self) -> dict[str, Any]:
        """Read the backend's unresolved loadout transaction journal, if any."""
        return self.runtime_action("loadout_recovery")

    def clear_loadout_recovery(
        self, *, epoch: str, snapshot_hash: str,
    ) -> dict[str, Any]:
        """Acknowledge a reviewed recovery journal against one fresh snapshot."""
        return self.runtime_action(
            "clear_loadout_recovery",
            acknowledge=True,
            epoch=str(epoch or ""),
            snapshot_hash=str(snapshot_hash or ""),
        )

    def apply_loadout(
        self,
        *,
        epoch: str,
        snapshot_hash: str,
        entries: list[dict[str, Any]],
        active_weapon_slot: int | None = None,
    ) -> dict[str, Any]:
        """Apply a preset against one fresh, optimistic-concurrency snapshot."""
        params: dict[str, Any] = {
            "epoch": str(epoch or ""),
            "snapshot_hash": str(snapshot_hash or ""),
            "entries": list(entries or []),
        }
        if active_weapon_slot is not None:
            params["active_weapon_slot"] = int(active_weapon_slot)
        return self.runtime_action("apply_loadout", **params)

    def resolve_live_item(self, **criteria: Any) -> dict[str, Any]:
        """Resolve one current-session inventory item; duplicates remain ambiguous."""
        return self.runtime_action("resolve_live_item", **criteria)

    def probe_item_runtime_cache(self, **criteria: Any) -> dict[str, Any]:
        """Compare a container identity with its equipped runtime actor, without writes."""
        return self.runtime_action("probe_item_runtime_cache", **criteria)

    def rebuild_item_cache(
        self, *, handle: int, serial_sha256: str, instance_id: int,
        epoch: str, player_state: str, active_weapon_slot: int | None,
    ) -> dict[str, Any]:
        """Round-trip one equipped item through a compatible donor to rebuild its actor cache."""
        params: dict[str, Any] = {
            "handle": int(handle),
            "serial_sha256": str(serial_sha256 or ""),
            "instance_id": int(instance_id),
            "epoch": str(epoch or ""),
            "player_state": str(player_state or ""),
        }
        if active_weapon_slot is not None:
            params["active_weapon_slot"] = int(active_weapon_slot)
        return self.runtime_action("rebuild_item_cache", **params)

    def publish_backpack_item(
        self, *, handle: int, serial_sha256: str, instance_id: int,
        epoch: str, player_state: str,
    ) -> dict[str, Any]:
        """Publish one unequipped backpack identity through the native inventory path."""
        return self.runtime_action(
            "publish_backpack_item",
            handle=int(handle),
            serial_sha256=str(serial_sha256 or ""),
            instance_id=int(instance_id),
            epoch=str(epoch or ""),
            player_state=str(player_state or ""),
        )

    def list(self) -> dict[str, Any]:
        return self._roundtrip({"id": 1, "op": "list"}, timeout=5)

    def read(self, container: str = "All", offset: int = 0, count: int = 4096,
             timeout: float | None = None) -> list[dict[str, Any]]:
        """Fetch items (serials + geometry). Backpack-first by server design."""
        resp = self._roundtrip(
            {"id": 1, "op": "read", "container": container, "offset": offset, "count": count},
            timeout=timeout or 30,
        )
        if not resp.get("ok"):
            raise BridgeError(str(resp.get("error", "read failed")))
        return list(resp.get("items", []))

    def apply(self, idx: int, serial: str, container: str = "BackpackItems",
              expect_old: str | None = None, *, expect_handle: int | None = None,
              expect_instance_id: int | None = None) -> dict[str, Any]:
        """
        Persistent overwrite: rewrite identity part pointers + serial text.
        Inventory thumbnails may update immediately, but weapon actors and card
        caches can require a main-menu reload. The response reports verification
        of the stored identity, not a claim that every derived runtime object rebuilt.
        """
        req: dict[str, Any] = {"id": 1, "op": "apply", "container": container,
                               "idx": idx, "serial": serial}
        if expect_old is not None:
            req["expect_old"] = expect_old
        if (expect_handle is None) != (expect_instance_id is None):
            raise BridgeError("stable item identity requires both handle and instance_id")
        if expect_handle is not None and expect_instance_id is not None:
            req["expect_handle"] = int(expect_handle)
            req["expect_instance_id"] = int(expect_instance_id)
        resp = self._roundtrip(req, timeout=30)
        if "ok" not in resp:
            raise BridgeError("malformed apply response")
        if resp.get("ok") and not (resp.get("verify_serial") and resp.get("verify_parts")):
            resp["ok"] = False
            resp.setdefault("error", "apply was not verified by the live inventory")
        return resp

    def spawn(self, serial: str, container: str = "BackpackItems") -> dict[str, Any]:
        """Ask the game to materialize one NEW item from its final serial."""
        resp = self._roundtrip(
            {"id": 1, "op": "spawn", "container": container, "serial": serial},
            timeout=30,
        )
        if "ok" not in resp:
            raise BridgeError("malformed spawn response")
        if resp.get("ok") and not (
            resp.get("verify_serial")
            and resp.get("verify_parts")
            and isinstance(resp.get("new_index"), int)
            and int(resp.get("after_count", 0)) > int(resp.get("before_count", 0))
        ):
            resp["ok"] = False
            resp.setdefault("error", "spawn was not verified by the live backpack")
        return resp

    def spawn_many(self, serials: list[str], container: str = "BackpackItems") -> dict[str, Any]:
        """Materialize a small batch in one native delivery transaction."""
        values = [str(value or "").strip() for value in serials if str(value or "").strip()]
        resp = self._roundtrip(
            {"id": 1, "op": "spawn_many", "container": container, "serials": values},
            timeout=45,
        )
        if "ok" not in resp:
            raise BridgeError("malformed spawn_many response")
        if resp.get("ok") and not (
            int(resp.get("added_count", 0)) == len(values)
            and resp.get("verify_serial")
            and resp.get("verify_parts")
            and int(resp.get("after_count", 0))
                >= int(resp.get("before_count", 0)) + len(values)
        ):
            resp["ok"] = False
            resp.setdefault("error", "batch materialization was not verified by the live backpack")
        return resp

    def available(self) -> bool:
        """Quick connect check -- is the game bridge up?"""
        try:
            with socket.create_connection((self.host, self.port), timeout=1.5):
                return True
        except OSError:
            return False
