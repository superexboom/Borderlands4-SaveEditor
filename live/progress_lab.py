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


def progression_dump(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only view of pawn.GbxProgressionManager (fields, graphs, nodes, point pools)."""
    import sys
    summarize = sys.modules[__name__.rpartition(".")[0] + ".progress_probe"].summarize
    pawn = m._runtime_pawn()
    manager = m._get_field(pawn, "GbxProgressionManager")
    if manager is None:
        return {"ok": False, "error": "no GbxProgressionManager on the pawn"}
    kind = getattr(manager, "_type", None) or manager.Class
    out = {"class": kind.Name, "fields": {}}
    for prop in kind._properties():
        if prop.Class.Name in ("DelegateProperty", "MulticastInlineDelegateProperty", "MulticastSparseDelegateProperty"):
            continue
        value = m._safe(lambda prop=prop: manager._get_field(prop))
        out["fields"][prop.Name] = {"type": prop.Class.Name,
                                    "value": summarize(value, int(args.get("depth") or 3), int(args.get("limit") or 4))}
    return {"ok": True, **out}


def graph_def_probe(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """What a GbxProgressGraphDef pointer exposes in Python (attributes, a few fields)."""
    pawn = m._runtime_pawn()
    manager = m._get_field(pawn, "GbxProgressionManager")
    graph = list(m._get_field(manager, "ProgressGraphs"))[int(args.get("index") or 0)]
    ptr = graph.ProgressGraphDef
    out = {"type": type(ptr).__name__, "attrs": [a for a in dir(ptr) if not a.startswith("__")]}
    for attr in out["attrs"]:
        value = m._safe(lambda attr=attr: getattr(ptr, attr))
        out[f"value.{attr}"] = str(value)[:300]
    data = m._safe(lambda: ptr._get_data() if hasattr(ptr, "_get_data") else None)
    out["data"] = str(data)[:1500] if data is not None else None
    return {"ok": True, **out}


def _plain(m: Any, value: Any, depth: int = 2) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    name = getattr(value, "_name", None)
    if isinstance(name, str) and type(value).__name__ in ("FGbxDefPtr", "FGameDataHandle"):
        return name
    kind = getattr(value, "_type", None)
    if kind is not None and hasattr(kind, "_properties") and depth > 0:
        return {p.Name: _plain(m, m._safe(lambda p=p: value._get_field(p)), depth - 1)
                for p in kind._properties() if p.Class.Name not in ("MapProperty", "SetProperty")}
    try:
        if depth > 0 and hasattr(value, "__len__") and not isinstance(value, (bytes, dict)):
            return [_plain(m, value[i], depth - 1) for i in range(min(len(value), 64))]
    except Exception:
        pass
    return str(value)[:120]


def skill_snapshot(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Every progress graph of the player: def name/type/pool, def nodes and live node state."""
    pawn = m._runtime_pawn()
    manager = m._get_field(pawn, "GbxProgressionManager")
    pools = list(m._get_field(m._get_field(manager, "ProgressPointsContainer"), "PointsAcquiredPerPool"))
    graphs = []
    for graph in list(m._get_field(manager, "ProgressGraphs")):
        entry = {"errors": []}
        try:
            definition = graph.ProgressGraphDef
            entry.update(graph=definition._name, type=int(m._safe(lambda: definition.GraphType, 0) or 0),
                         pool=getattr(m._safe(lambda: definition.PointPool), "_name", None))
            def_nodes = m._safe(lambda: list(definition.nodes), []) or []
            live = list(graph.nodes)
            rows = []
            for index, state in enumerate(live):
                row = {"i": index, "spent": state.ProgressPointsSpent, "bonus": state.BonusPoints,
                       "unlocked": state.bIsUnlocked, "active": state.bIsActivated, "level": state.ActivationLevel}
                if index < len(def_nodes):
                    try:
                        row["def"] = _plain(m, def_nodes[index], int(args.get("depth") or 1))
                    except Exception as exc:
                        entry["errors"].append(f"node {index}: {type(exc).__name__}: {exc}"[:120])
                rows.append(row)
            entry["nodes"] = rows
            entry["groups"] = len(list(graph.Groups))
        except Exception as exc:
            entry["errors"].append(f"{type(exc).__name__}: {exc}"[:160])
        graphs.append(entry)
    return {"ok": True, "points_per_pool": pools, "graphs": graphs}


def _graph_by_name(m: Any, name: str) -> Any:
    manager = m._get_field(m._runtime_pawn(), "GbxProgressionManager")
    for graph in list(m._get_field(manager, "ProgressGraphs")):
        if str(graph.ProgressGraphDef._name).lower() == name.lower():
            return graph
    return None


def _graph_state(graph: Any) -> list[dict[str, Any]]:
    return [{"i": i, "spent": n.ProgressPointsSpent, "bonus": n.BonusPoints, "active": n.bIsActivated,
             "level": n.ActivationLevel, "unlocked": n.bIsUnlocked} for i, n in enumerate(list(graph.nodes))]


def skill_reapply(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Reset one point-spending graph and spend the same points again; compare before/after."""
    graph = _graph_by_name(m, str(args["graph"]))
    if graph is None:
        return {"ok": False, "error": "graph not found"}
    before = _graph_state(graph)
    wanted = {row["i"]: row["spent"] for row in before if row["spent"] > 0}
    graph.Server_ResetSpentPoints()
    after_reset = _graph_state(graph)
    passes = []
    for _ in range(6):
        progress = 0
        for index in sorted(wanted):
            have = graph.nodes[index].ProgressPointsSpent
            need = wanted[index] - have
            if need <= 0:
                continue
            graph.Server_SpendProgressPoints(index, need)
            got = graph.nodes[index].ProgressPointsSpent - have
            progress += got
        passes.append(progress)
        if not progress:
            break
    after = _graph_state(graph)
    same = [(b["spent"], b["active"]) for b in before] == [(a["spent"], a["active"]) for a in after]
    return {"ok": same, "same_as_before": same, "passes": passes,
            "before": [(r["i"], r["spent"], r["active"]) for r in before if r["spent"] or r["active"]],
            "after_reset": [(r["i"], r["spent"], r["active"]) for r in after_reset if r["spent"] or r["active"]],
            "after": [(r["i"], r["spent"], r["active"]) for r in after if r["spent"] or r["active"]]}


def graph_groups(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Def groups of one graph (node membership, limits) plus live group/node state."""
    graph = _graph_by_name(m, str(args["graph"]))
    definition = graph.ProgressGraphDef
    groups = m._safe(lambda: list(definition.Groups), None)
    out = {"def_groups": None if groups is None else [_plain(m, g, int(args.get("depth") or 3)) for g in groups],
           "def_groups_raw": str(m._safe(lambda: definition.Groups))[:1500],
           "live_groups": [_plain(m, g, 2) for g in list(graph.Groups)],
           "nodes": _graph_state(graph)}
    return {"ok": True, **out}


def skill_swap_back(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Activate node ``other`` in ``group`` (swapping the equipped choice), then the original back."""
    graph = _graph_by_name(m, str(args["graph"]))
    group, original, other = int(args.get("group") or 0), int(args["original"]), int(args["other"])
    active = lambda: [r["i"] for r in _graph_state(graph) if r["active"]]
    before = active()
    graph.Server_ActivateNodeInGroup(group, other, True, 0)
    swapped = active()
    graph.Server_ActivateNodeInGroup(group, original, True, 0)
    after = active()
    return {"ok": after == before, "before": before, "swapped": swapped, "after": after}


def skill_activation_steps(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Run a list of Server_ActivateNodeInGroup(group, node, on) steps, log the active set after each,
    then restore the original active set (deactivate extras, re-activate originals)."""
    graph = _graph_by_name(m, str(args["graph"]))
    active = lambda: [r["i"] for r in _graph_state(graph) if r["active"]]
    before = active()
    log = []
    for group, node, on in args.get("steps") or []:
        graph.Server_ActivateNodeInGroup(int(group), int(node), bool(on), 0)
        log.append({"step": [group, node, on], "active": active()})
    restore = args.get("restore") or []
    for group, node, on in restore:
        graph.Server_ActivateNodeInGroup(int(group), int(node), bool(on), 0)
    after = active()
    return {"ok": after == before, "before": before, "log": log, "after": after}


def skill_bonus_test(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Server_AddBonusPoints(node, n); then reset+respend the graph and see whether the bonus stays."""
    graph = _graph_by_name(m, str(args["graph"]))
    node = int(args["node"])
    row = lambda: _graph_state(graph)[node]
    before = row()
    graph.Server_AddBonusPoints(node, int(args.get("points") or 1))
    with_bonus = row()
    reapplied = skill_reapply(m, {"graph": args["graph"]})
    after = row()
    return {"ok": True, "before": before, "with_bonus": with_bonus, "after_reset_respend": after,
            "reapply_same": reapplied.get("same_as_before")}


def skill_add_bonus(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    graph = _graph_by_name(m, str(args["graph"]))
    node = int(args["node"])
    before = _graph_state(graph)[node]
    graph.Server_AddBonusPoints(node, int(args["points"]))
    return {"ok": True, "before": before, "after": _graph_state(graph)[node]}


def count_pickups(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    pickups = _pickups(m)
    return {"ok": True, "count": len(pickups), "rows": _pickup_rows(m, pickups[: int(args.get("limit") or 10)])}


def native_gates(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    base = k32.GetModuleHandleW(None) or 0
    pc = m._player_controller()
    pc_addr = m._addr(pc)
    vtable = m._u64(m._rd(pc_addr, 8) or b"", 0) if pc_addr else 0
    submit = m._u64(m._rd(vtable + m._INVENTORY_SERVER_IMPLEMENTATION_VTABLE_OFFSET, 8) or b"", 0) if vtable else 0
    return {"ok": True, "module_base": hex(base), "image_base": hex(m.IMAGE_BASE), "vtable": hex(vtable),
            "submit": hex(submit), "submit_rva": hex(submit - base) if base else None,
            "expected": hex(m._INVENTORY_SERVER_IMPLEMENTATION_EXPECTED),
            "mismatches": m._inventory_native_gate()[:4]}


def set_pool(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Set PointsAcquiredPerPool[index] (restores a pool after experiments)."""
    manager = m._get_field(m._runtime_pawn(), "GbxProgressionManager")
    pools = m._get_field(m._get_field(manager, "ProgressPointsContainer"), "PointsAcquiredPerPool")
    index, before = int(args["index"]), None
    before = int(pools[index])
    pools[index] = int(args["value"])
    setattr(manager, "ProgressGraphsArrayDirty", 3)
    return {"ok": True, "before": before, "after": int(pools[index])}


def resolve_defs(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: how each serial's parts resolve to live definitions (no item is written)."""
    out = []
    for serial in args.get("serials") or []:
        res = m._resolve_serial_definitions(serial)
        refs = res.get("refs") or {}
        out.append({
            "ok": res.get("ok"), "root": res.get("root"), "error": res.get("error"),
            "parts": [[r["owner"], r["id"], r["name"]] for r in refs.get("parts") or []],
            "comp": refs.get("comp") and [refs["comp"]["owner"], refs["comp"]["id"]],
            "missing": [{k: r.get(k) for k in ("kind", "owner", "id", "name")} for r in res.get("missing") or []],
        })
    roots = {}
    for root in args.get("roots") or []:
        root = int(root)
        type_ptr = m.GAME.type_index.get(root, 0)
        mapped, stats = m._parts_from_type_def(root, type_ptr) if type_ptr else ({}, {})
        ids = sorted(pid for (owner, pid) in mapped if owner == root)
        bucket = m._bucket_for_root(root) or {}
        bucket_parts = sorted(int(k) for k, v in bucket.items()
                              if str(k).isdigit() and m._definition_kind(str(v)) == "part")
        roots[str(root)] = {
            "type_ptr": hex(type_ptr), "stats": stats, "mapped_ids": ids,
            "owners_in_map": sorted({owner for (owner, _pid) in mapped}),
            "bucket_parts_missing_live": [pid for pid in bucket_parts if pid not in ids],
            "probe": {str(pid): bucket.get(str(pid)) for pid in args.get("probe_ids") or []},
            "probe_live": {str(pid): hex(m.GAME.part_index.get((root, int(pid)), 0)) for pid in args.get("probe_ids") or []},
        }
    return {"ok": True, "serials": out, "roots": roots}


def partdef_vtables(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: vtables of live items' part definitions and of a type map's entries vs PARTDEF_VTBL."""
    from collections import Counter
    items = Counter()
    for c in ("BackpackItems", "BankItems"):
        arr = m.GAME.items_array(c)
        n = (m._safe(lambda: len(arr), 0) or 0) if arr is not None else 0
        for i in range(min(n, int(args.get("items", 20)))):
            ident = m.GAME.identity_at(c, i)
            addr = m._addr(ident) if ident is not None else 0
            for ptr in m._read_part_ptrs(addr) if addr else []:
                items[hex(m._u64(m._rd(ptr, 8) or b"", 0))] += 1
    maps = Counter()
    root = int(args.get("root", 20))
    type_ptr = m.GAME.type_index.get(root, 0)
    header = m._rd(type_ptr + m.OFF_TYPE_ALL_PART_DEFS, 16) if type_ptr else None
    if header:
        outer_data, outer_cap = m._u64(header, 0), m._u32(header, 12)
        for oi in range(min(outer_cap, 64)):
            hdr = m._rd(outer_data + oi * m.TYPE_PART_OUTER_STRIDE + m.TYPE_PART_INNER_OFFSET, 16)
            if not hdr:
                continue
            data, num, cap = m._u64(hdr, 0), m._u32(hdr, 8), m._u32(hdr, 12)
            if not m._looks_ptr(data) or not (0 < num <= cap <= 4096):
                continue
            for ii in range(cap):
                entry = m._rd(data + ii * m.TYPE_PART_INNER_STRIDE, m.TYPE_PART_INNER_STRIDE)
                ptr = m._u64(entry, m.TYPE_PART_INNER_VALUE_OFFSET) if entry else 0
                if m._looks_ptr(ptr):
                    maps[hex(m._u64(m._rd(ptr, 8) or b"", 0))] += 1
    module = m._safe(lambda: m._module_base(), None) if hasattr(m, "_module_base") else None
    return {"ok": True, "PARTDEF_VTBL": hex(m.PARTDEF_VTBL), "IMAGE_BASE": hex(m.IMAGE_BASE),
            "module_base": hex(module) if module else None,
            "item_part_vtables": items.most_common(5), "type_map_vtables": maps.most_common(5)}


def _find_identity(m: Any, obj: Any, depth: int = 4, seen: set | None = None) -> Any:
    """First InventoryIdentity struct reachable from a pickup (reflected fields only)."""
    from unrealsdk.unreal import UObject, WrappedArray, WrappedStruct
    seen = set() if seen is None else seen
    if depth < 0 or obj is None:
        return None
    if isinstance(obj, WrappedStruct):
        if obj._type.Name == "InventoryIdentity":
            return obj
        props = obj._type._properties()
    elif isinstance(obj, UObject):
        if m._addr(obj) in seen:
            return None
        seen.add(m._addr(obj))
        props = obj.Class._properties()
    elif isinstance(obj, WrappedArray):
        for i in range(min(len(obj), 2)):
            hit = _find_identity(m, obj[i], depth - 1, seen)
            if hit is not None:
                return hit
        return None
    else:
        return None
    for prop in props:
        if prop.Class.Name not in ("StructProperty", "ObjectProperty", "ArrayProperty"):
            continue
        if prop.Class.Name == "ObjectProperty" and depth < 3:
            continue
        hit = _find_identity(m, m._safe(lambda prop=prop: obj._get_field(prop)), depth - 1, seen)
        if hit is not None:
            return hit
    return None


def _pickup_serials(m: Any, pickups: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for obj in pickups:
        ident = _find_identity(m, obj)
        info = m._read_identity(ident) if ident is not None else {"ok": False, "why": "no identity"}
        loc = m._safe(lambda obj=obj: obj.K2_GetActorLocation())
        item = m._safe(lambda obj=obj: obj.Item)
        data = m._safe(lambda: item.data) if item is not None else None
        rows.append({"id": m._safe(lambda: int(data.InstanceId)) if data is not None else None,
                     "obj": m._path(obj).rsplit("_", 1)[-1],
                     "serial": info.get("serial"), "why": info.get("why"),
                     "pos": [round(loc.X), round(loc.Y), round(loc.Z)] if loc is not None else None})
    return rows


def spawn_comp(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Roll items natively from one composition (OakInventoryStatics.SpawnInventoryFromCharacter) and
    report the new pickups' serials. args: type, comp, times (<=30), policy, owner_only."""
    pawn = m._runtime_pawn()
    statics = m._runtime_static("OakInventoryStatics")
    inv_type = str(args.get("type") or "ted_repair_kit")
    comp = str(args.get("comp") or "comp_05_legendary_font")
    times = max(1, min(30, int(args.get("times") or 1)))
    before = {m._addr(obj) for obj in _pickups(m)}
    errors = []
    started = time.perf_counter()
    for _ in range(times):
        try:
            statics.SpawnInventoryFromCharacter(
                OwnerContext=pawn, InventoryType=inv_type, InventoryComp=comp,
                InstancingPolicy=int(args.get("policy") or 0), bOwnerOnly=bool(args.get("owner_only", False)),
                owner=pawn)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}"[:240])
            break
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    new = [obj for obj in _pickups(m) if m._addr(obj) not in before]
    return {"ok": not errors, "type": inv_type, "comp": comp, "times": times, "elapsed_ms": elapsed,
            "errors": errors, "new_pickups": len(new), "items": _pickup_serials(m, new[:60])}


def pickup_parts(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: root / composition / part ids of pickups straight from their identities
    (fresh drops carry no serial text yet). args: roots=[290, 243], min_id=0, radius."""
    roots = {int(r) for r in args.get("roots") or [290, 243]}
    m._ensure_part_index(roots, roots)
    part_by_ptr = {ptr: f"{k[0]}:{k[1]}" for k, ptr in m.GAME.part_index.items() if k[0] in roots}
    comp_by_ptr = {ptr: f"{k[0]}:{k[1]}" for k, ptr in m.GAME.comp_index.items() if k[0] in roots}
    type_by_ptr = {ptr: root for root, ptr in m.GAME.type_index.items()}
    pawn = m._runtime_pawn()
    here = pawn.K2_GetActorLocation()
    radius = float(args.get("radius") or 100000)
    min_id = int(args.get("min_id") or 0)
    rows = []
    for obj in _pickups(m):
        item = m._safe(lambda obj=obj: obj.Item)
        data = m._safe(lambda: item.data) if item is not None else None
        pid = m._safe(lambda: int(data.InstanceId)) if data is not None else None
        loc = m._safe(lambda obj=obj: obj.K2_GetActorLocation())
        if pid is None or pid < min_id or loc is None:
            continue
        if ((loc.X - here.X) ** 2 + (loc.Y - here.Y) ** 2 + (loc.Z - here.Z) ** 2) ** 0.5 > radius:
            continue
        ident = _find_identity(m, obj)
        addr = m._addr(ident) if ident is not None else 0
        raw = m._rd(addr, m.IDENTITY_SIZE) if addr else None
        if not raw:
            rows.append({"id": pid, "why": "no identity"})
            continue
        type_ptr, comp_ptr = m._u64(raw, m.OFF_TYPE_PTR), m._u64(raw, m.OFF_COMP_PTR)
        info = m._read_identity_address(addr)
        rows.append({"id": pid, "root": type_by_ptr.get(type_ptr, hex(type_ptr)),
                     "comp": comp_by_ptr.get(comp_ptr, hex(comp_ptr)),
                     "parts": [part_by_ptr.get(p, hex(p)) for p in m._read_part_ptrs(addr)],
                     "serial": info.get("serial")})
    rows.sort(key=lambda row: row["id"])
    return {"ok": True, "count": len(rows), "items": rows[: int(args.get("limit") or 80)]}


def clear_ids(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Destroy test drops by InstanceId with a small DestroyJunkWithinBounds box around each one.
    args: ids=[...], size=15. Reports which of the ids are still there afterwards."""
    pawn = m._runtime_pawn()
    junk = m._runtime_static("JunkSystemFunctionLibrary")
    wanted = {int(x) for x in args.get("ids") or []}
    size = float(args.get("size") or 15)

    def by_id():
        out = {}
        for obj in _pickups(m):
            item = m._safe(lambda obj=obj: obj.Item)
            data = m._safe(lambda: item.data) if item is not None else None
            pid = m._safe(lambda: int(data.InstanceId)) if data is not None else None
            if pid in wanted:
                out[pid] = obj
        return out

    targets = by_id()
    for pid, obj in targets.items():
        loc = m._safe(lambda obj=obj: obj.K2_GetActorLocation())
        if loc is None:
            continue
        box = _sdk().make_struct("Box", Min=_sdk().make_struct("Vector", X=loc.X - size, Y=loc.Y - size, Z=loc.Z - size),
                                 Max=_sdk().make_struct("Vector", X=loc.X + size, Y=loc.Y + size, Z=loc.Z + size),
                                 IsValid=True)
        junk.DestroyJunkWithinBounds(pawn, box)
    return {"ok": True, "found": sorted(targets), "left": sorted(by_id())}


def backpack_serials(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only: serials of the backpack entries (last `n`, default 10), with their index."""
    m.GAME.refresh_containers()
    arr = m.GAME.items_array("BackpackItems")
    total = (m._safe(lambda: len(arr), 0) or 0) if arr is not None else 0
    rows = []
    for i in range(max(0, total - int(args.get("n") or 10)), total):
        ident = m.GAME.identity_at("BackpackItems", i)
        info = m._read_identity(ident) if ident is not None else {"ok": False, "why": "empty"}
        row = {"index": i, "serial": info.get("serial"), "why": info.get("why")}
        addr = m._addr(ident) if ident is not None else 0
        raw = m._rd(addr, m.IDENTITY_SIZE) if addr else None
        if raw and args.get("roots"):
            roots = {int(r) for r in args["roots"]}
            m._ensure_part_index(roots, roots)
            part_by_ptr = {ptr: f"{k[0]}:{k[1]}" for k, ptr in m.GAME.part_index.items() if k[0] in roots}
            comp_by_ptr = {ptr: f"{k[0]}:{k[1]}" for k, ptr in m.GAME.comp_index.items() if k[0] in roots}
            type_by_ptr = {ptr: root for root, ptr in m.GAME.type_index.items()}
            row.update({"root": type_by_ptr.get(m._u64(raw, m.OFF_TYPE_PTR)),
                        "comp": comp_by_ptr.get(m._u64(raw, m.OFF_COMP_PTR)),
                        "parts": [part_by_ptr.get(p, hex(p)) for p in m._read_part_ptrs(addr)]})
        rows.append(row)
    return {"ok": True, "total": total, "items": rows}


def pickup_serials(m: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Serials of the pickups within `radius` (default 3000) of the player."""
    pawn = m._runtime_pawn()
    here = pawn.K2_GetActorLocation()
    radius = float(args.get("radius") or 3000)
    near = []
    for obj in _pickups(m):
        loc = m._safe(lambda obj=obj: obj.K2_GetActorLocation())
        if loc is not None and ((loc.X - here.X) ** 2 + (loc.Y - here.Y) ** 2 + (loc.Z - here.Z) ** 2) ** 0.5 <= radius:
            near.append(obj)
    return {"ok": True, "count": len(near), "items": _pickup_serials(m, near[: int(args.get("limit") or 80)])}


TESTS = {name: fn for name, fn in globals().items() if callable(fn) and not name.startswith("_")
         and name not in {"run", "annotations"}}


def run(m: Any, test: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = TESTS.get(test)
    if fn is None:
        return {"ok": False, "error": f"unknown lab test {test!r}", "tests": sorted(TESTS)}
    return fn(m, args)
