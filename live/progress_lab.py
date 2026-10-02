"""BL4Live development experiments (dev flag only, never shipped).

Loaded by ``progress_lab`` in progress_probe.py and re-imported from disk on
request.  Each test is a small, named function; results are plain data.
"""

from __future__ import annotations

import time
from typing import Any


def _sdk():
    import unrealsdk  # noqa: PLC0415 - only importable inside the game
    return unrealsdk


def _pickups(m: Any) -> list[Any]:
    return [obj for obj in _sdk().find_all("InventoryPickup", False)
            if "Default__" not in str(m._path(obj))]


def _pickup_rows(m: Any, pickups: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for obj in pickups:
        row = {"path": m._path(obj)}
        for field in ("InventoryItem", "Item", "ItemIdentity"):
            value = m._safe(lambda field=field: getattr(obj, field), None)
            if value is not None:
                row[field] = str(value)[:160]
        rows.append(row)
    return rows


def drop_pool(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Spawn an ItemPoolList (or ItemPool) at the player like the dedicated-drop hook does."""
    from unrealsdk.unreal import FGameDataHandle
    pawn = m._runtime_pawn()
    lib = m._runtime_static("ItemPoolFunctionLibrary")
    spawn = getattr(lib, "SpawnItemsFromItemPoolUsingActor_Drop")
    pool = str(args.get("pool") or "ItemPoolList_Destroyer")
    handle_type = int(args.get("handle_type") or m._ITEM_POOL_LIST_HANDLE)
    times = max(1, min(50, int(args.get("times") or 1)))
    before = {m._addr(obj) for obj in _pickups(m)}
    results = []
    for _ in range(times):
        out = spawn(SourceActor=pawn, itempool=FGameDataHandle(handle_type, pool),
                    SpawnPattern=FGameDataHandle(m._SPAWN_PATTERN_HANDLE, m._DEDICATED_DROP_PATTERN),
                    SocketName="None", OutJunkIds=[])
        junk = out[-1] if isinstance(out, tuple) else out
        results.append(len(junk) if junk is not None else -1)
    after = [obj for obj in _pickups(m) if m._addr(obj) not in before]
    return {"ok": True, "pool": pool, "handle_type": handle_type, "times": times,
            "junk_per_call": results, "junk_total": sum(n for n in results if n > 0),
            "new_pickups": len(after)}


def handle_types(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """TypeHandle of every GameDataHandle parameter of the given functions vs the mod's constants."""
    out = {}
    for path in args.get("functions") or ["/Script/GbxGame.ItemPoolFunctionLibrary:SpawnItemsFromItemPoolUsingActor_Drop"]:
        func = _sdk().find_object("Function", path)
        out[path] = {prop.Name: int(getattr(prop, "TypeHandle", -1)) for prop in func._properties()
                     if prop.Class.Name == "GameDataHandleProperty"}
    return {"ok": True, "params": out, "mod_constants": {
        "_ITEM_POOL_LIST_HANDLE": m._ITEM_POOL_LIST_HANDLE, "_SPAWN_PATTERN_HANDLE": m._SPAWN_PATTERN_HANDLE}}


def functions_taking_handle(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Every UFunction with a GameDataHandle parameter of the given TypeHandle(s)."""
    wanted = {int(x) for x in (args.get("types") or [4160])}
    rows = []
    for func in _sdk().find_all("Function", False):
        try:
            for prop in func._properties():
                if prop.Class.Name == "GameDataHandleProperty" and int(prop.TypeHandle) in wanted:
                    rows.append(f"{func._path_name()} ({prop.Name}={int(prop.TypeHandle)})")
        except Exception:
            continue
    return {"ok": True, "count": len(rows), "functions": rows[:200]}


def handle_type_census(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """TypeHandle -> a few (function, parameter) examples, to name the handle types."""
    census: dict[int, list[str]] = {}
    for func in _sdk().find_all("Function", False):
        try:
            for prop in func._properties():
                if prop.Class.Name == "GameDataHandleProperty":
                    rows = census.setdefault(int(prop.TypeHandle), [])
                    if len(rows) < int(args.get("per_type") or 3):
                        rows.append(f"{func.Name}.{prop.Name}")
        except Exception:
            continue
    return {"ok": True, "types": {str(k): v for k, v in sorted(census.items())}}


def find_handles(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """GameDataHandles (type, name) reachable from an object: default = the first equipped item."""
    from unrealsdk.unreal import UObject, WrappedArray, WrappedStruct
    target = args.get("target")
    if target:
        root = _sdk().find_object(*str(target).rstrip("'").split("'", 1))
    else:
        pawn = m._runtime_pawn()
        slots = m._get_field(m._get_field(pawn, "EquippedInventorySlots"), "items")
        root = m._live_interface_object(m._get_field(list(slots)[0], "InstancedInventory"))
    found, seen = [], set()

    def walk(value, path, depth):
        if len(found) >= 60 or depth < 0:
            return
        kind = type(value).__name__
        if kind == "FGameDataHandle" or "GameDataHandle" in kind:
            found.append({"path": path, "type": int(getattr(value, "_type", getattr(value, "TypeHandle", -1)) or -1),
                          "repr": str(value)[:160]})
            return
        if isinstance(value, UObject):
            if m._addr(value) in seen or depth < 1:
                return
            seen.add(m._addr(value))
            props = value.Class._properties()
        elif isinstance(value, WrappedStruct):
            props = value._type._properties()
        elif isinstance(value, WrappedArray):
            for i in range(min(len(value), 4)):
                walk(value[i], f"{path}[{i}]", depth - 1)
            return
        else:
            return
        for prop in props:
            if prop.Class.Name in ("DelegateProperty", "MulticastInlineDelegateProperty", "MulticastSparseDelegateProperty"):
                continue
            sub = m._safe(lambda: value._get_field(prop))
            if sub is not None:
                walk(sub, f"{path}.{prop.Name}", depth - 1)

    walk(root, m._path(root), int(args.get("depth") or 4))
    return {"ok": True, "root": m._path(root), "handles": found}


def resolve_handle(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Which TypeHandle values resolve ``name`` to a definition (third FGameDataHandle field)."""
    from unrealsdk.unreal import FGameDataHandle
    name = str(args["name"])
    lo, hi = int(args.get("lo", 4096)), int(args.get("hi", 4352))
    hits = []
    for type_handle in range(lo, hi):
        try:
            handle = FGameDataHandle(type_handle, name)
        except Exception:
            continue
        text = str(handle)
        if not text.endswith("None)"):
            hits.append({"type": type_handle, "repr": text[:200]})
    return {"ok": True, "name": name, "hits": hits[:20]}


def attach_probe(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Spawn loot attached to the player (SpawnLootFromDef_Attach), report what attached, destroy it.

    args: name, types=[...] (TypeHandles to try), keep=False."""
    from unrealsdk.unreal import FGameDataHandle
    pawn = m._runtime_pawn()
    loot = m._runtime_static("LootFunctionLibrary")
    junk = m._runtime_static("JunkSystemFunctionLibrary")

    def attached():
        out = junk.GetJunkAttachedToActor(Actor=pawn, OutJunkIds=[])
        ids = out[-1] if isinstance(out, tuple) else out
        return [ids[i] for i in range(len(ids))] if ids is not None else []

    rows = []
    for type_handle in args.get("types") or [4144]:
        before = len(attached())
        error = ""
        try:
            for _ in range(int(args.get("times") or 1)):
                if args.get("via") == "pool":
                    m._runtime_static("ItemPoolFunctionLibrary").SpawnItemsFromItemPool_Attach(
                        SourceActor=pawn, itempool=FGameDataHandle(int(type_handle), str(args["name"])),
                        SocketName="None", OutJunkIds=[])
                    continue
                loot.SpawnLootFromDef_Attach(SourceActor=pawn, Item=FGameDataHandle(int(type_handle), str(args["name"])),
                                             InstancingPolicy=int(args.get("policy") or 0), InstancedFor=None,
                                             SocketName="None")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        ids = attached()
        rows.append({"type": type_handle, "attached": len(ids) - before, "error": error,
                     "ids": [str(x)[:120] for x in ids[before:before + 3]]})
        if not args.get("keep"):
            for junk_id in ids:
                m._safe(lambda junk_id=junk_id: junk.DestroyJunkItem(WorldContextObject=pawn, JunkId=junk_id))
    return {"ok": True, "name": args["name"], "rows": rows, "left": len(attached())}


def clear_attached(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    pawn = m._runtime_pawn()
    junk = m._runtime_static("JunkSystemFunctionLibrary")
    out = junk.GetJunkAttachedToActor(Actor=pawn, OutJunkIds=[])
    ids = out[-1] if isinstance(out, tuple) else out
    errors = []
    for i in range(len(ids)):
        try:
            junk.DestroyJunkItem(pawn, ids[i])
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    out = junk.GetJunkAttachedToActor(Actor=pawn, OutJunkIds=[])
    left = out[-1] if isinstance(out, tuple) else out
    return {"ok": True, "had": len(ids), "left": len(left), "errors": errors[:3],
            "id_fields": [p.Name for p in ids[0]._type._properties()] if len(ids) else []}


def clear_near_player(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Destroy loot junk in a box around the player (test drops only)."""
    pawn = m._runtime_pawn()
    junk = m._runtime_static("JunkSystemFunctionLibrary")
    loc = pawn.K2_GetActorLocation()
    r = float(args.get("radius") or 400)
    box = _sdk().make_struct("Box", Min=_sdk().make_struct("Vector", X=loc.X - r, Y=loc.Y - r, Z=loc.Z - r),
                             Max=_sdk().make_struct("Vector", X=loc.X + r, Y=loc.Y + r, Z=loc.Z + r), IsValid=True)
    junk.DestroyJunkWithinBounds(pawn, box)
    out = junk.GetJunkAttachedToActor(Actor=pawn, OutJunkIds=[])
    left = out[-1] if isinstance(out, tuple) else out
    return {"ok": True, "center": [loc.X, loc.Y, loc.Z], "attached_left": len(left)}


def struct_fields(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Reflected fields of script structs (name -> type), one level, for the named structs."""
    out = {}
    for name in args.get("structs") or []:
        struct = _sdk().find_object("ScriptStruct", name) if "/" in name else None
        if struct is None:
            for candidate in _sdk().find_all("ScriptStruct", False):
                if candidate.Name == name:
                    struct = candidate
                    break
        if struct is None:
            out[name] = None
            continue
        rows = {}
        for prop in struct._properties():
            kind = prop.Class.Name
            inner = getattr(prop, "Struct", None) or getattr(prop, "PropertyClass", None) or getattr(prop, "Inner", None)
            rows[prop.Name] = kind + (f"<{getattr(inner, 'Name', '')}>" if inner is not None else "")
            if kind == "GameDataHandleProperty":
                rows[prop.Name] += f" type={int(prop.TypeHandle)}"
        out[name] = {"path": struct._path_name(), "fields": rows}
    return {"ok": True, "structs": out}


def show_handle(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """repr of FGameDataHandle(type, name) and of its attributes (resolved def when available)."""
    from unrealsdk.unreal import FGameDataHandle
    handle = FGameDataHandle(int(args.get("type") or 0), str(args["name"]))
    attrs = {name: str(m._safe(lambda name=name: getattr(handle, name)))[:600]
             for name in dir(handle) if not name.startswith("__")}
    return {"ok": True, "repr": str(handle)[:2000], "attrs": attrs}


def data_attach(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """SpawnLootFromData_Attach with InventoryItemSelectionData{Item.Handle=(type, name)}; count attached junk."""
    from unrealsdk.unreal import FGameDataHandle
    pawn = m._runtime_pawn()
    loot = m._runtime_static("LootFunctionLibrary")
    junk = m._runtime_static("JunkSystemFunctionLibrary")

    def attached():
        out = junk.GetJunkAttachedToActor(Actor=pawn, OutJunkIds=[])
        ids = out[-1] if isinstance(out, tuple) else out
        return len(ids) if ids is not None else 0

    rows = []
    for type_handle in args.get("types") or [0]:
        before = attached()
        error = ""
        try:
            data = _sdk().make_struct("InventoryItemSelectionData")
            provider = data.Item
            provider.Handle = FGameDataHandle(int(type_handle), str(args["name"]))
            provider.bInstance = False
            data.Item = provider
            criteria = data.Criteria
            criteria.Preset = FGameDataHandle(1000127390, str(args.get("preset") or "None"))
            data.Criteria = criteria
            loot.SpawnLootFromData_Attach(SourceActor=pawn, Item=data, InstancingPolicy=0,
                                          InstancedFor=None, SocketName="None")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:200]
        rows.append({"type": type_handle, "attached": attached() - before, "error": error})
    return {"ok": True, "name": args["name"], "rows": rows}


def maintain_profile(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Time the pieces of one maintenance cycle (same calls maintain() makes), averaged."""
    n = int(args.get("n") or 20)
    pawn = m._runtime_pawn()
    pieces = {
        "runtime_pawn": lambda: m._runtime_pawn(),
        "player_controller": lambda: m._player_controller(),
        "refresh_xp_context": lambda: m._runtime_refresh_xp_context(),
        "apply_player_features": lambda: m._runtime_apply_player_features(pawn),
        "apply_jump_scale": lambda: m._runtime_apply_jump_scale(pawn),
        "apply_infinite_jump": lambda: m._runtime_apply_infinite_jump(pawn),
        "apply_backpack_size": lambda: m._runtime_apply_backpack_size(),
        "maintain_force": lambda: m._runtime_maintain(force=True),
    }
    out = {}
    for name, fn in pieces.items():
        start = time.perf_counter()
        for _ in range(n):
            fn()
        out[name] = round((time.perf_counter() - start) * 1000 / n, 3)
    return {"ok": True, "ms_per_call": out}


def maintain_closure_profile(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Time the runtime_maintenance closures (actors, owned, apply_weapons) via the maintain() cells."""
    fn = m._runtime_maintain
    cells = dict(zip(fn.__code__.co_freevars, (c.cell_contents for c in fn.__closure__)))
    n = int(args.get("n") or 20)
    pawn = m._runtime_pawn()
    out = {"freevars": sorted(cells)}
    timings = {}
    def timed(name, call):
        start = time.perf_counter()
        for _ in range(n):
            call()
        timings[name] = round((time.perf_counter() - start) * 1000 / n, 3)
    actors = cells.get("actors")
    if actors:
        timed("actors", lambda: actors(pawn))
        rows = actors(pawn)
        out["actor_count"] = len(rows)
        out["actor_classes"] = [m._cls(a) for a in rows]
        timed("live_interface_object_x_slots", lambda: [m._live_interface_object(m._get_field(s, "InstancedInventory"))
                                                       for s in list(m._get_field(m._get_field(pawn, "EquippedInventorySlots"), "items"))])
    owned = cells.get("owned")
    if owned:
        timed("owned_weapon", lambda: owned("Weapon", pawn))
    apply_weapons = cells.get("apply_weapons")
    if apply_weapons:
        timed("apply_weapons", lambda: apply_weapons(pawn, False, time.perf_counter()))
    behaviors = cells.get("behaviors") or getattr(m, "_runtime_behaviors", None)
    if owned and behaviors:
        weapons = owned("Weapon", pawn)
        timed("behaviors_all_weapons", lambda: [list(m._runtime_behaviors(w)) for w in weapons])
        out["behaviors_per_weapon"] = [len(list(m._runtime_behaviors(w))) for w in weapons]
    timed("apply_player_features", lambda: m._runtime_apply_player_features(pawn))
    out["ms_per_call"] = timings
    return {"ok": True, **out}


def health_states(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    pawn = m._runtime_pawn()
    health = m._get_field(pawn, "HealthState")
    rows = []
    for state in list(m._get_field(health, "HealthTypeStates")):
        row = {}
        for prop in state._type._properties():
            value = m._safe(lambda prop=prop: state._get_field(prop))
            row[prop.Name] = value if isinstance(value, (int, float, bool)) else str(value)[:80]
        rows.append(row)
    return {"ok": True, "states": rows}


def install_maintenance(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Re-import runtime_maintenance.py from disk and install it (the module supports
    in-session updates), then re-wrap the progress probe that the install unwrapped."""
    import importlib
    import sys
    package = __name__.rpartition(".")[0]
    maintenance = importlib.reload(sys.modules[f"{package}.runtime_maintenance"])
    maintenance.install(m)
    probe = sys.modules[f"{package}.progress_probe"]
    probe.install(m)
    return {"ok": True, "maintenance": maintenance.REVISION, "probe": probe.REVISION,
            "maintain_revision": getattr(m._runtime_maintain, "_maintenance_revision", None)}


def profile_maintain(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """cProfile of N maintenance runs (interval gate bypassed), top functions by own time."""
    import cProfile
    import io
    import pstats
    n = int(args.get("n") or 50)
    profiler = cProfile.Profile()
    start = time.perf_counter()
    cells = dict(zip(m._runtime_maintain.__code__.co_freevars,
                     (c.cell_contents for c in m._runtime_maintain.__closure__ or ())))
    for _ in range(n):
        m._RUNTIME_LAST_MAINTAIN = 0.0
        if args.get("slow") and "slow_last" in cells:
            cells["slow_last"][0] = 0.0
        profiler.enable()
        m._runtime_maintain()
        profiler.disable()
    total = (time.perf_counter() - start) * 1000 / n
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats(str(args.get("sort") or "tottime")).print_stats(int(args.get("top") or 25))
    return {"ok": True, "ms_per_run": round(total, 3), "profile": out.getvalue()[-6000:]}


def field_costs(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Time m._get_field per field name across N slow maintenance runs."""
    n = int(args.get("n") or 20)
    cells = dict(zip(m._runtime_maintain.__code__.co_freevars,
                     (c.cell_contents for c in m._runtime_maintain.__closure__ or ())))
    original = m._get_field
    costs: dict[str, list[float]] = {}

    def timed(obj, name):
        start = time.perf_counter()
        try:
            return original(obj, name)
        finally:
            row = costs.setdefault(f"{m._safe(lambda: obj.Class.Name, type(obj).__name__)}.{name}", [0, 0.0])
            row[0] += 1
            row[1] += time.perf_counter() - start

    m._get_field = timed
    try:
        for _ in range(n):
            m._RUNTIME_LAST_MAINTAIN = 0.0
            if "slow_last" in cells:
                cells["slow_last"][0] = 0.0
            m._runtime_maintain()
    finally:
        m._get_field = original
    rows = sorted(((round(total * 1000 / n, 3), count // n, name) for name, (count, total) in costs.items()), reverse=True)
    return {"ok": True, "ms_per_run_by_field": rows[: int(args.get("top") or 25)]}


def health_layers(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    pawn = m._runtime_pawn()
    lib = m._runtime_static("DamageStatics")
    rows = []
    for state in list(m._get_field(m._get_field(pawn, "HealthState"), "HealthTypeStates")):
        handle = m._get_field(state, "HealthType")
        layer = int(lib.GetHealthPoolLayerOfType(pawn, handle, True))
        rows.append({"type": handle._name, "layer": layer,
                     "percent": float(lib.GetHealthPoolPercent(pawn, layer)) if layer >= 0 else None})
    return {"ok": True, "layers": rows, "slots": int(lib.GetNumHealthSlots(pawn, False))}


def spawn_actor(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """GbxSpawnActorAtTransform(GbxActorDef) a few metres in front of the player (latent, no callback)."""
    import random
    from unrealsdk.unreal import FGameDataHandle
    sdk = _sdk()
    pawn = m._runtime_pawn()
    lib = m._runtime_static("SpawnBlueprintLibrary")
    loc = pawn.K2_GetActorLocation()
    forward = pawn.GetActorForwardVector()
    distance = float(args.get("distance") or 600)
    transform = sdk.make_struct(
        "Transform",
        Rotation=sdk.make_struct("Quat", X=0.0, Y=0.0, Z=0.0, W=1.0),
        Translation=sdk.make_struct("Vector", X=loc.X + forward.X * distance, Y=loc.Y + forward.Y * distance,
                                    Z=loc.Z + float(args.get("lift") or 50)),
        Scale3D=sdk.make_struct("Vector", X=1.0, Y=1.0, Z=1.0))
    details = sdk.make_struct("SpawnDetails")
    latent = sdk.make_struct("LatentActionInfo", Linkage=-1, UUID=random.randint(1, 2**30),
                             ExecutionFunction="None", CallbackTarget=pawn)
    result = lib.GbxSpawnActorAtTransform(
        Context=pawn, GbxActorDef=FGameDataHandle(16384, str(args.get("def") or "Char_BatBasic")),
        Transform=transform, owner=None, instigator=None, SpawnDetails=details, bIsCritical=False,
        Result=None, LatentInfo=latent)
    return {"ok": True, "returned": str(result)[:200], "at": [transform.Translation.X, transform.Translation.Y,
                                                             transform.Translation.Z]}


def find_actors(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """OakCharacters whose path contains ``needle`` (with location and actor def)."""
    needle = str(args.get("needle") or "").lower()
    lib = m._runtime_static("SpawnBlueprintLibrary")
    rows = []
    for obj in _sdk().find_all("OakCharacter", False):
        path = m._path(obj)
        if "Default__" in path or (needle and needle not in path.lower()):
            continue
        loc = m._safe(lambda obj=obj: obj.K2_GetActorLocation())
        rows.append({"path": path, "def": str(m._safe(lambda obj=obj: lib.GetGbxActorDefinition(obj)._name, "")),
                     "loc": [round(loc.X), round(loc.Y), round(loc.Z)] if loc is not None else None})
    return {"ok": True, "count": len(rows), "actors": rows[: int(args.get("limit") or 20)]}


_AWARDED: dict[str, Any] = {}


def _xp_points(m: Any) -> list[dict[str, Any]]:
    rows = []
    for state in list(m._get_field(m.GAME.player_state, "ExperienceState")):
        row = {}
        for prop in state._type._properties():
            value = m._safe(lambda prop=prop: state._get_field(prop))
            if isinstance(value, (int, float, bool)):
                row[prop.Name] = value
            elif prop.Name in ("ExperienceType", "Type", "Def"):
                row[prop.Name] = str(m._safe(lambda value=value: value._name, value))[:60]
        rows.append(row)
    return rows


def xp_points(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tracks": _xp_points(m)}


def award_kill_xp(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """OakExperienceStatics.AwardKillExperienceToParty on an actor (no kill); XP deltas per track."""
    needle = str(args.get("needle") or "batbasic").lower()
    used = _AWARDED.setdefault("paths", set())
    target = next((obj for obj in _sdk().find_all("OakCharacter", False)
                   if needle in m._path(obj).lower() and "Default__" not in m._path(obj)
                   and m._path(obj) not in used), None)
    if target is None:
        return {"ok": False, "error": f"no actor matching {needle!r}"}
    used.add(m._path(target))
    statics = m._runtime_static("OakExperienceStatics")
    before = _xp_points(m)
    for _ in range(int(args.get("times") or 1)):
        statics.AwardKillExperienceToParty(ContextActor=target, OptionalKiller=m._player_controller())
    after = _xp_points(m)
    deltas = []
    for b, a in zip(before, after):
        deltas.append({k: a[k] - b[k] for k in a if isinstance(a.get(k), (int, float)) and not isinstance(a.get(k), bool)
                       and k in b and a[k] != b[k]})
    return {"ok": True, "target": m._path(target), "deltas": deltas,
            "combat_xp_multiplier": m._runtime_combat_xp_value()}


def xp_rebind(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Run the pawn-change path of the XP multiplier (_runtime_refresh_xp_context) N times
    by faking a different context key, and report the resolved multiplier after each."""
    rows = [{"start": m._runtime_combat_xp_value(), "handles": len(m._RUNTIME_XP_MODIFIERS)}]
    for _ in range(int(args.get("times") or 3)):
        m._RUNTIME_XP_CONTEXT_KEY = (1, "fake-previous-pawn")
        rebound = m._runtime_refresh_xp_context()
        rows.append({"rebound": rebound, "value": m._runtime_combat_xp_value(),
                     "handles": len(m._RUNTIME_XP_MODIFIERS), "refresh": dict(m._RUNTIME_XP_REFRESH_STATUS),
                     "scale": m._RUNTIME_STATE.get("experience_reward_scale")})
    return {"ok": True, "rows": rows}


def xp_values(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    lib = m._runtime_static("GbxAttributeBlueprintLibrary")
    pc = m._player_controller()
    contexts = {"pawn": m._runtime_pawn(), "controller": pc, "player_state": m.GAME.player_state,
                "character": m._get_field(pc, "Character")}
    out = {}
    for name, ctx in contexts.items():
        out[name] = None if ctx is None else round(float(lib.GetValueOfAttribute(
            "Att_CombatXP_Multiplier", ctx, -1.0)), 4)
    out["pawn_class"] = m._cls(contexts["pawn"]) if contexts["pawn"] is not None else None
    return {"ok": True, "values": out, "lab_handles": len(_AWARDED.get("xp_handles", []))}


def xp_add(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Add one multiplicative Att_CombatXP_Multiplier modifier through the chosen context."""
    lib = m._runtime_static("GbxAttributeBlueprintLibrary")
    pc = m._player_controller()
    ctx = {"controller": pc, "player_state": m.GAME.player_state, "pawn": m._runtime_pawn()}[
        str(args.get("context") or "controller")]
    handle, action, error = m._runtime_add_xp_modifier(lib, ctx, float(args["value"]))
    if handle is not None and action == 0:
        _AWARDED.setdefault("xp_handles", []).append(handle)
    return {"ok": handle is not None and action == 0, "error": error, **xp_values(m, {})}


def attr_mod(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Add (value given) or remove (remove=true) multiplicative modifiers on a named attribute,
    applied through the player controller; handles are kept per attribute in this module."""
    lib = m._runtime_static("GbxAttributeBlueprintLibrary")
    pc = m._player_controller()
    contexts = {"controller": pc, "pawn": m._runtime_pawn(), "player_state": m.GAME.player_state,
                "world": m._get_field(pc, "World") if pc is not None else None,
                "game_state": m._get_field(m._get_field(pc, "World"), "GameState") if pc is not None else None}
    ctx = contexts.get(str(args.get("context") or "controller"))
    name = str(args["attribute"])
    action = None
    handles = _AWARDED.setdefault("attr_handles", {}).setdefault(name, [])
    removed = 0
    if args.get("remove"):
        for handle in list(handles):
            ok, _ = m._remove_attribute_modifier_handle(lib, handle)
            if ok:
                handles.remove(handle)
                removed += 1
    else:
        ptr = m._runtime_def_ptr(name, ("/Script/GbxEngine.GbxAttributeDef", "/Script/GbxGame.GbxAttributeDef"),
                                 "GbxAttributeDef")
        if ptr is None:
            return {"ok": False, "error": f"attribute {name} unavailable"}
        handle, action = m._runtime_modifier_action(lib.AddModifierToGbxAttribute(
            attribute=ptr, ContextSource=ctx, ModifierType=int(args.get("type") or 3),
            modifiervalue=float(args["value"]), bAutoRefresh=True, ModifierActionResult=0))
        if handle is not None and action == 0:
            handles.append(handle)
    values = {k: (None if c is None else m._safe(lambda c=c: float(lib.GetValueOfAttribute(name, c, -1.0))))
              for k, c in contexts.items()}
    return {"ok": True, "attribute": name, "action": action, "values": values, "handles": len(handles),
            "removed": removed}


def xp_remove_test(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Add x2 through the controller, remove that handle, force a refresh (add x1): does removal work?"""
    lib = m._runtime_static("GbxAttributeBlueprintLibrary")
    pc = m._player_controller()
    read = lambda: round(float(lib.GetValueOfAttribute("Att_CombatXP_Multiplier", pc, -1.0)), 4)
    steps = {"start": read()}
    handle, action, _ = m._runtime_add_xp_modifier(lib, pc, 2.0)
    steps["after_add_x2"] = read()
    raw = lib.RemoveModifierFromGbxAttribute(ModifierHandle=handle, ModifierActionResult=0)
    steps["remove_return"] = str(raw)[:160]
    steps["after_remove"] = read()
    legacy = m._safe(lambda: lib.RemoveAttributeModifier(ModifierHandle=handle))
    steps["legacy_remove_return"] = str(legacy)[:160]
    refresh, _, _ = m._runtime_add_xp_modifier(lib, pc, 1.0)
    steps["after_refresh"] = read()
    steps["handle"] = str(handle)[:200]
    return {"ok": True, "steps": steps}


def xp_set_applied(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Tell the XP guard the product of the modifiers already live (orphans from older code)."""
    m._XP_APPLIED = float(args["applied"])
    return {"ok": True, "applied": m._XP_APPLIED, "value": m._runtime_combat_xp_value()}


_HOOK_PROBE: dict[str, Any] = {}
_HOOK_PREFIX = "bl4_live_lab_probe:"


def hook_probe(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Count calls of UFunctions (POST hooks that only count): start / report / stop."""
    from unrealsdk.hooks import Type, add_hook, remove_hook
    mode = str(args.get("mode") or "report")
    if mode in ("start", "stop"):
        for path in list(_HOOK_PROBE):
            m._safe(lambda path=path: remove_hook(path, Type.POST, _HOOK_PREFIX + path))
        report = {path: dict(row) for path, row in _HOOK_PROBE.items()}
        _HOOK_PROBE.clear()
        if mode == "stop":
            return {"ok": True, "stopped": report}
        added = []
        for path in args.get("functions") or []:
            row = _HOOK_PROBE[path] = {"calls": 0, "objects": {}}

            def counter(obj, _args, _ret, _func, row=row):
                row["calls"] += 1
                name = m._safe(lambda: obj.Class.Name, "?")
                row["objects"][name] = row["objects"].get(name, 0) + 1
                return None

            if add_hook(path, Type.POST, _HOOK_PREFIX + path, counter):
                added.append(path)
        return {"ok": True, "hooked": added}
    return {"ok": True, "counts": {path: {"calls": row["calls"],
                                          "objects": dict(sorted(row["objects"].items(), key=lambda kv: -kv[1])[:8])}
                                   for path, row in _HOOK_PROBE.items()}}


def hook_census(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Counting POST hooks on every non-getter UFunction whose name matches a pattern
    (start), then report the ones that were called; stop removes them."""
    mode = str(args.get("mode") or "report")
    if mode != "start":
        result = hook_probe(m, {"mode": mode})
        if mode == "report":
            result["counts"] = {k: v for k, v in result["counts"].items() if v["calls"]}
        return result
    patterns = [p.lower() for p in args.get("patterns") or []]
    skip = [s.lower() for s in args.get("skip") or ["delegatesignature", "widget", "/ui", "anim", "audio",
                                                       "dialog", "camera", "__", "menu", "hud"]]
    paths = []
    for func in _sdk().find_all("Function", False):
        try:
            path = func._path_name()
            name = func.Name.lower()
            if not any(p in name for p in patterns) or any(s in path.lower() for s in skip):
                continue
            flags = int(func.FunctionFlags)
            if flags & (0x10000000 | 0x40000000):  # pure / const getters run constantly
                continue
            if name.startswith(("get", "is", "has", "can", "should")):
                continue
            paths.append(path)
        except Exception:
            continue
    limit = int(args.get("limit") or 400)
    result = hook_probe(m, {"mode": "start", "functions": paths[:limit]})
    return {"ok": True, "matched": len(paths), "hooked": len(result.get("hooked") or [])}


def enemy_scan_cost(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Cost of find_all(OakCharacter) and of IsDead() over the result."""
    n = int(args.get("n") or 5)
    start = time.perf_counter()
    for _ in range(n):
        rows = list(_sdk().find_all("OakCharacter", False))
    scan_ms = (time.perf_counter() - start) * 1000 / n
    start = time.perf_counter()
    dead = sum(1 for obj in rows if m._safe(lambda obj=obj: bool(obj.IsDead()), False))
    dead_ms = (time.perf_counter() - start) * 1000
    return {"ok": True, "characters": len(rows), "dead": dead, "find_all_ms": round(scan_ms, 3),
            "is_dead_all_ms": round(dead_ms, 3)}


def replay_dead(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Call DropLoot() ``extra`` more times on every newly dead non-player OakCharacter."""
    from unrealsdk.hooks import prevent_hooking_direct_calls
    handled = _AWARDED.setdefault("replayed", {})
    extra = int(args.get("extra") or 3)
    pawn = m._runtime_pawn()
    rows = []
    for obj in _sdk().find_all("OakCharacter", False):
        path = m._path(obj)
        if "Default__" in path or (pawn is not None and m._addr(obj) == m._addr(pawn)):
            continue
        key = (m._addr(obj), path)
        if key in handled or not m._safe(lambda obj=obj: bool(obj.IsDead()), False):
            continue
        handled[key] = time.time()
        error = ""
        try:
            with prevent_hooking_direct_calls():
                for _ in range(extra):
                    obj.DropLoot()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:160]
        rows.append({"actor": path.rsplit(".", 1)[-1], "extra": extra, "error": error})
    return {"ok": True, "replayed": rows, "total_handled": len(handled)}


def count_pickups(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    pickups = _pickups(m)
    return {"ok": True, "count": len(pickups), "rows": _pickup_rows(m, pickups[: int(args.get("limit") or 10)])}


TESTS = {name: fn for name, fn in globals().items() if callable(fn) and not name.startswith("_")
         and name not in {"run", "annotations"}}


def run(m: Any, test: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = TESTS.get(test)
    if fn is None:
        return {"ok": False, "error": f"unknown lab test {test!r}", "tests": sorted(TESTS)}
    return fn(m, args)
