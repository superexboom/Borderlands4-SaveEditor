"""Progress readers for BL4Live (missions, challenges, facts) plus one writer.

Installed into the running ``bl4_live`` module by its bootstrap (cold start) or
``pyexec bl4_progress_install.py`` (running game). It only wraps
``_runtime_action`` to answer ``progress_*`` actions and forwards everything
else unchanged.

Rules, matching the rest of BL4Live:
- Readers only, no hooks. The single write (``progress_increment_challenges``)
  goes through the game's own challenge increment, the same call gameplay makes
  when an item is picked up; nothing pokes facts or save data directly.
- No UObject wrapper survives a request (map/menu transitions invalidate them);
  only plain strings/numbers are cached.
- Every action is on demand; nothing polls. Results report ``elapsed_ms`` so
  the cost stays visible.
- Discovery helpers (class/function/object listing, property inspection,
  const/pure getter calls, self reload) exist for development only and are
  refused unless ``progress_dev.flag`` sits next to this file. Self reload
  re-imports this module from disk; it never executes code sent over the bridge.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any

REVISION = "progress-probe-20260925.6"

DEV_FLAG = Path(__file__).with_name("progress_dev.flag")

# UFunction / property flags (UE5)
FUNC_STATIC = 0x00002000
FUNC_BLUEPRINT_PURE = 0x10000000
FUNC_CONST = 0x40000000
CPF_PARM = 0x0000000000000080
CPF_OUT_PARM = 0x0000000000000100
CPF_RETURN_PARM = 0x0000000000000400
_GETTER_PREFIXES = ("Get", "Is", "Has", "Can", "Find", "Num", "Count", "Lookup", "Query", "Read")
_MUTATOR_PREFIXES = ("Write", "Set", "Add", "Remove", "Clear", "Reset", "Complete", "Grant", "Give", "Unlock",
                     "Start", "Stop", "Fail", "Activate", "Deactivate", "Increment", "Decrement", "Apply")

# Plain-string caches (never UObjects).
_CACHE: dict[str, Any] = {}

RELEASE_ACTIONS = ("progress_capabilities", "progress_facts", "progress_increment_challenges")
DEV_ACTIONS = ("progress_reload", "progress_classes", "progress_functions", "progress_find_functions",
               "progress_objects", "progress_inspect", "progress_call", "progress_handle")


def dev_enabled() -> bool:
    return DEV_FLAG.exists()


# --------------------------------------------------------------------------- #
# install / dispatch
# --------------------------------------------------------------------------- #
def install(m: Any) -> None:
    """Wrap ``m._runtime_action`` once (re-installing replaces the old wrapper)."""
    current = m._runtime_action
    base = getattr(current, "_progress_base", current)

    def action(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        key = str(name or "").strip().lower()
        if key.startswith("progress_"):
            return dispatch(m, key, params or {})
        return base(name, params)

    action._progress_base = base  # type: ignore[attr-defined]
    m._runtime_action = action
    m._progress_probe_revision = REVISION
    _CACHE.clear()


def dispatch(m: Any, key: str, params: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if key not in RELEASE_ACTIONS + DEV_ACTIONS:
            result = {"ok": False, "error": f"unknown progress action: {key}"}
        elif key in DEV_ACTIONS and not dev_enabled():
            result = {"ok": False, "error": "development action disabled (progress_dev.flag missing)"}
        else:
            result = _HANDLERS[key](m, params)
    except Exception as exc:  # a reader must never take the bridge down
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result.setdefault("action", key)
    result["revision"] = REVISION
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sdk():
    import unrealsdk  # noqa: PLC0415 - only importable inside the game
    return unrealsdk


def _path(obj: Any) -> str:
    try:
        return f"{obj.Class.Name}'{obj._path_name()}'"
    except Exception:
        return str(obj)[:200]


def _type_name(prop: Any) -> str:
    kind = getattr(getattr(prop, "Class", None), "Name", "") or type(prop).__name__
    for attr in ("Struct", "PropertyClass", "Enum"):
        inner = getattr(prop, attr, None)
        if inner is not None:
            return f"{kind}<{getattr(inner, 'Name', inner)}>"
    inner = getattr(prop, "Inner", None)
    if inner is not None:
        return f"{kind}[{_type_name(inner)}]"
    return kind


def summarize(value: Any, depth: int = 1, limit: int = 8) -> Any:
    """JSON-safe, bounded view of an Unreal value."""
    from unrealsdk.unreal import UObject, WrappedArray, WrappedStruct  # noqa: PLC0415

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:300]
    if isinstance(value, UObject):
        return {"object": _path(value)}
    if isinstance(value, WrappedArray):
        count = len(value)
        items = [summarize(value[i], depth - 1, limit) for i in range(min(count, limit))] if depth > 0 else []
        return {"len": count, "items": items}
    if isinstance(value, WrappedStruct):
        out: dict[str, Any] = {"struct": value._type.Name}
        if depth > 0:
            for prop in value._type._properties():
                try:
                    out[prop.Name] = summarize(value._get_field(prop), depth - 1, limit)
                except Exception as exc:
                    out[prop.Name] = f"<{type(exc).__name__}>"
        return out
    if isinstance(value, (tuple, list)):
        return [summarize(item, depth, limit) for item in list(value)[:limit]]
    return str(value)[:300]


def resolve_target(m: Any, spec: Any) -> Any:
    """player_state / player_controller / pawn / world / game_state /
    class_default:<Class> / <Class>'<path>' (exact object)."""
    text = str(spec or "player_state").strip()
    if text == "player_state":
        return m.GAME.player_state
    if text == "player_controller":
        return m._player_controller()
    if text == "pawn":
        return m._runtime_pawn()
    if text in ("world", "game_state"):
        controller = m._player_controller()
        world = m._get_field(controller, "World") if controller is not None else None
        return world if text == "world" else m._get_field(world, "GameState")
    if text.startswith("class_default:"):
        return _sdk().find_class(text.split(":", 1)[1]).ClassDefaultObject
    if "'" in text:
        cls, _, rest = text.partition("'")
        return _sdk().find_object(cls, rest.rstrip("'"))
    raise ValueError(f"unknown target {text!r}")


def _function_row(func: Any) -> dict[str, Any]:
    params = []
    for prop in func._properties():
        flags = int(prop.PropertyFlags)
        if not flags & CPF_PARM:
            continue
        role = "return" if flags & CPF_RETURN_PARM else ("out" if flags & CPF_OUT_PARM else "in")
        params.append({"name": prop.Name, "type": _type_name(prop), "role": role})
    flags = int(func.FunctionFlags)
    return {"name": func.Name, "flags": hex(flags), "static": bool(flags & FUNC_STATIC),
            "pure": bool(flags & (FUNC_BLUEPRINT_PURE | FUNC_CONST)), "params": params}


# --------------------------------------------------------------------------- #
# release actions
# --------------------------------------------------------------------------- #
def _capabilities(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "dev": dev_enabled(),
            "actions": list(RELEASE_ACTIONS + (DEV_ACTIONS if dev_enabled() else ())),
            "player_state": m.GAME.player_state is not None}


MAX_FACTS_PER_REQUEST = 4000
MAX_ADDRESS_LENGTH = 256
DEFAULT_BUDGET_MS = 6.0
MAX_BUDGET_MS = 25.0


def _facts(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Read fact values by address (``missions.<set>.<mission>.status``, ``stats....``).

    Values mirror the save file: ``None`` when the fact is unset, otherwise
    ``[name, int]`` (``["completed", 1]``, ``["1", 1]``, ``["B", 1]``). Reading
    stops once ``budget_ms`` is spent so a long list never stalls a frame; the
    caller continues from ``next``.
    """
    addresses = params.get("addresses")
    if not isinstance(addresses, list) or len(addresses) > MAX_FACTS_PER_REQUEST:
        return {"ok": False, "error": f"addresses must be a list of at most {MAX_FACTS_PER_REQUEST} strings"}
    if not all(isinstance(item, str) and 0 < len(item) <= MAX_ADDRESS_LENGTH for item in addresses):
        return {"ok": False, "error": "every address must be a non-empty string"}
    controller = m._player_controller()
    if controller is None:
        return {"ok": False, "error": "no active player"}
    start = max(0, int(params.get("start") or 0))
    budget = min(float(params.get("budget_ms") or DEFAULT_BUDGET_MS), MAX_BUDGET_MS) / 1000.0
    read = _sdk().find_class("FactsBlueprintLibrary").ClassDefaultObject.ReadFact
    values: list[Any] = []
    began = time.perf_counter()
    index = start
    while index < len(addresses):
        _ret, as_name, as_int, _as_bool = read(controller, addresses[index], "", 0, False)
        name = str(as_name)
        values.append(None if name == "None" and not as_int else [name, int(as_int)])
        index += 1
        if time.perf_counter() - began >= budget:
            break
    return {"ok": True, "start": start, "values": values,
            "next": index if index < len(addresses) else None, "total": len(addresses)}


MAX_CHALLENGES_PER_REQUEST = 64
MAX_CHALLENGE_INCREMENT = 10000


def _challenge_api() -> tuple[Any, Any]:
    """(library CDO, GameDataHandleProperty for challenge params)."""
    cls = _sdk().find_class("OakChallengeBlueprintLibrary")
    func = cls._find("GetChallengeProgressForPlayer")
    return cls.ClassDefaultObject, next(p for p in func._properties() if p.Name == "challenge")


def _increment_challenges(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Credit challenges through the game's own ``IncrementChallengeForPlayer``.

    This is the path gameplay uses when an item is picked up, so the game
    handles completion, rewards, the notification and saving. Already-complete
    challenges are left alone. The backing stat fact changes at once but the
    challenge itself is evaluated on a later tick, so rows only say ``sent``;
    callers confirm by re-reading facts afterwards.
    """
    rows_in = params.get("challenges")
    if not isinstance(rows_in, list) or not 0 < len(rows_in) <= MAX_CHALLENGES_PER_REQUEST:
        return {"ok": False, "error": f"challenges must be a list of 1..{MAX_CHALLENGES_PER_REQUEST} entries"}
    wanted = []
    for row in rows_in:
        name = str((row or {}).get("name") or "") if isinstance(row, dict) else ""
        if not (3 <= len(name) <= 96 and name.replace("_", "").isalnum() and name.isascii()):
            return {"ok": False, "error": f"invalid challenge name {name!r}"}
        amount = row.get("amount", 1)
        if not isinstance(amount, int) or isinstance(amount, bool):
            return {"ok": False, "error": "amount must be an integer"}
        if not 0 < amount <= MAX_CHALLENGE_INCREMENT:
            return {"ok": False, "error": f"amount must be 1..{MAX_CHALLENGE_INCREMENT}"}
        wanted.append((name, amount))
    controller = m._player_controller()
    if controller is None:
        return {"ok": False, "error": "no active player"}
    library, prop = _challenge_api()
    results = []
    for name, amount in wanted:
        handle = _data_handle(prop, name)
        before = int(library.GetChallengeProgressForPlayer(controller, handle))
        if library.IsChallengeCompleteForPlayer(controller, handle):
            results.append({"name": name, "status": "already", "before": before})
            continue
        library.IncrementChallengeForPlayer(controller, controller, handle, amount)
        results.append({"name": name, "status": "sent", "before": before})
    return {"ok": True, "results": results}


# --------------------------------------------------------------------------- #
# development actions
# --------------------------------------------------------------------------- #
def _reload(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    fresh = importlib.reload(sys.modules[__name__])
    fresh.install(m)
    return {"ok": True, "installed": fresh.REVISION}


def _names(kind: str) -> list[tuple[str, str]]:
    """(lower name, path) of every loaded UClass / UFunction; built once per probe revision."""
    key = f"names:{kind}"
    if key not in _CACHE:
        rows = []
        for obj in _sdk().find_all(kind, False):
            try:
                path = obj._path_name()
            except Exception:
                continue
            rows.append((path.rsplit(".", 1)[-1].rsplit(":", 1)[-1].lower(), path))
        _CACHE[key] = rows
    return _CACHE[key]


def _classes(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    needle = str(params.get("pattern") or "").lower()
    limit = int(params.get("limit") or 200)
    rows = [path for name, path in _names("Class") if needle in name]
    return {"ok": True, "count": len(rows), "classes": rows[:limit]}


def _functions(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    cls = _sdk().find_class(str(params["class"]))
    needle = str(params.get("pattern") or "").lower()
    rows = [_function_row(field) for field in cls._fields()
            if getattr(field.Class, "Name", "") == "Function" and needle in field.Name.lower()]
    props = [{"name": prop.Name, "type": _type_name(prop)} for prop in cls._properties()] \
        if params.get("properties") else []
    return {"ok": True, "class": _path(cls), "functions": rows[: int(params.get("limit") or 300)],
            "properties": props}


def _find_functions(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    needle = str(params.get("pattern") or "").lower()
    if len(needle) < 3:
        return {"ok": False, "error": "pattern needs at least 3 characters"}
    rows = [path for name, path in _names("Function") if needle in name]
    return {"ok": True, "count": len(rows), "functions": rows[: int(params.get("limit") or 200)]}


def _objects(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    limit = int(params.get("limit") or 50)
    rows = []
    for obj in _sdk().find_all(str(params["class"]), bool(params.get("exact", False))):
        path = _path(obj)
        if "Default__" in path and not params.get("defaults"):
            continue
        rows.append(path)
        if len(rows) >= limit:
            break
    return {"ok": True, "objects": rows}


def _inspect(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    obj = resolve_target(m, params.get("target"))
    if obj is None:
        return {"ok": False, "error": "target not available"}
    wanted = {str(name) for name in params.get("fields") or []}
    depth = int(params.get("depth") or (2 if wanted else 0))
    limit = int(params.get("limit") or 8)
    fields = {}
    for prop in obj.Class._properties():
        if wanted and prop.Name not in wanted:
            continue
        row: dict[str, Any] = {"type": _type_name(prop)}
        try:
            row["value"] = summarize(obj._get_field(prop), depth, limit)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        fields[prop.Name] = row
    return {"ok": True, "target": _path(obj), "fields": fields}


def _coerce(prop: Any, value: Any) -> Any:
    if getattr(getattr(prop, "Class", None), "Name", "") == "GameDataHandleProperty" and isinstance(value, str):
        return _data_handle(prop, value)
    struct = getattr(prop, "Struct", None)
    if struct is not None and isinstance(value, dict):
        members = {inner.Name: inner for inner in struct._properties()}
        return _sdk().make_struct(struct.Name, **{name: _coerce(members[name], item)
                                                  for name, item in value.items() if name in members})
    if getattr(prop, "PropertyClass", None) is not None and isinstance(value, str) and "'" in value:
        cls, _, rest = value.partition("'")
        return _sdk().find_object(cls, rest.rstrip("'"))
    return value


def _data_handle(prop: Any, name: str) -> Any:
    """Game-data handle (a challenge, mission... def) by name for a GameDataHandleProperty."""
    from unrealsdk.unreal import FGameDataHandle  # noqa: PLC0415
    return FGameDataHandle(int(prop.TypeHandle), name)


_CONTEXT_PARAMS = ("WorldContextObject", "WorldContext", "ContextObject", "OwnerContext")
_CONTROLLER_PARAMS = ("OakPC", "PC", "PlayerController")


def _placeholder(prop: Any) -> Any:
    """Value for an out parameter the caller did not supply (pyunrealsdk wants every param)."""
    kind = getattr(getattr(prop, "Class", None), "Name", "")
    struct = getattr(prop, "Struct", None)
    if struct is not None:
        return _sdk().make_struct(struct.Name)
    if kind in ("IntProperty", "Int64Property", "ByteProperty", "UInt32Property", "Int16Property", "EnumProperty"):
        return 0
    if kind in ("FloatProperty", "DoubleProperty"):
        return 0.0
    if kind == "BoolProperty":
        return False
    if kind in ("StrProperty", "NameProperty", "TextProperty"):
        return ""
    if kind == "ArrayProperty":
        return []
    return None


def _handle(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    """How a challenge def name resolves (repr/address), for checking handle validity."""
    func = _sdk().find_class("OakChallengeBlueprintLibrary")._find("GetChallengeProgressForPlayer")
    prop = next(p for p in func._properties() if p.Name == "challenge")
    rows = []
    for name in params.get("names") or []:
        handle = _data_handle(prop, str(name))
        row: dict[str, Any] = {"name": name, "repr": repr(handle)}
        for attr in ("_name", "_type_handle"):
            try:
                row[attr] = getattr(handle, attr)
            except Exception as exc:
                row[attr] = f"<{type(exc).__name__}: {exc}>"
        try:
            row["address"] = handle._get_address()
        except Exception as exc:
            row["address"] = f"<{type(exc).__name__}: {exc}>"
        try:
            row["dir"] = [item for item in dir(handle) if not item.startswith("__")][:40]
        except Exception as exc:
            row["dir"] = f"<{type(exc).__name__}: {exc}>"
        rows.append(row)
    return {"ok": True, "type_handle": int(prop.TypeHandle), "handles": rows}


def _call(m: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Call one const/pure getter; anything that might mutate is refused."""
    obj = resolve_target(m, params.get("target"))
    name = str(params["function"])
    func = obj.Class._find(name)
    flags = int(func.FunctionFlags)
    if name.startswith(_MUTATOR_PREFIXES) or (
            not (flags & (FUNC_BLUEPRINT_PURE | FUNC_CONST)) and not name.startswith(_GETTER_PREFIXES)):
        return {"ok": False, "error": f"{name} is not a const/pure getter", "flags": hex(flags)}
    args = dict(params.get("args") or {})
    kwargs = {}
    for prop in func._properties():
        pflags = int(prop.PropertyFlags)
        if not pflags & CPF_PARM or pflags & CPF_RETURN_PARM:
            continue
        if prop.Name in args:
            kwargs[prop.Name] = _coerce(prop, args[prop.Name])
        elif prop.Name in _CONTEXT_PARAMS + _CONTROLLER_PARAMS:
            kwargs[prop.Name] = m._player_controller()
        elif pflags & CPF_OUT_PARM:
            kwargs[prop.Name] = _placeholder(prop)
    result = getattr(obj, name)(**kwargs)
    return {"ok": True, "function": _function_row(func),
            "result": summarize(result, int(params.get("depth") or 2), int(params.get("limit") or 16))}


_HANDLERS = {
    "progress_capabilities": _capabilities,
    "progress_facts": _facts,
    "progress_increment_challenges": _increment_challenges,
    "progress_reload": _reload,
    "progress_classes": _classes,
    "progress_functions": _functions,
    "progress_find_functions": _find_functions,
    "progress_objects": _objects,
    "progress_inspect": _inspect,
    "progress_call": _call,
    "progress_handle": _handle,
}
