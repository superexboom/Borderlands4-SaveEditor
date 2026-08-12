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
        req = {"id": 1, "op": "runtime", "action": str(action or "").strip()}
        req.update(params)
        resp = self._roundtrip(
            req,
            timeout=5,
        )
        if "ok" not in resp:
            raise BridgeError("malformed runtime response")
        return resp

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
              expect_old: str | None = None) -> dict[str, Any]:
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
            and resp.get("verify_level")
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
            and resp.get("verify_level")
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
