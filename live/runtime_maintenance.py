"""BL4Live 0.10.25 maintenance repair, installed in the game's bl4_live package.

All calls run on the existing game-thread dispatcher. No DLL or native offset
changes. Enumerate equipped slots, never the global UObject array, in the hot path.
"""
import math
import time

VERSION = '0.10.26'
REVISION = 'slot-maintenance-20260919.6'


class ValueBindings:
    """Weak-object scalar/attribute bindings; no Unreal wrapper survives apply()."""
    def __init__(self, rows):
        self.rows = rows

    def apply(self):
        writes, invalid, changes = 0, False, []
        for weak, fields, weapon_ref in self.rows:
            obj = weak()
            if obj is None:
                invalid = True
                continue
            for attr, subs in fields.items():
                try:
                    holder = getattr(obj, attr)
                    for sub, target in subs.items():
                        current = getattr(holder, sub) if sub else holder
                        if math.isclose(float(current), float(target), rel_tol=1e-6, abs_tol=1e-7):
                            continue
                        setattr(holder if sub else obj, sub or attr, target)
                        writes += 1
                        if attr == 'MaxLoadedAmmo' and sub in ('', 'Value') and weapon_ref:
                            weapon = weapon_ref()
                            if weapon is not None:
                                changes.append((weapon, obj, int(current), int(target)))
                except (AttributeError, TypeError, ValueError, ReferenceError):
                    invalid = True
        return writes, invalid, changes


def install(m):
    from unrealsdk.unreal import WeakPointer
    if getattr(m._runtime_maintain, '_maintenance_revision', None) == REVISION:
        return
    # Keep one set of base functions when explicitly updating this module in an
    # existing session. Never stack action/restore closures across revisions.
    for name, fn in getattr(m, '_maintenance_originals', {}).items():
        setattr(m, name, fn)
    # Unwrap the optional diagnostic decorator before installing replacement code.
    for name, fn in getattr(m, '_perf_originals', {}).items():
        setattr(m, name, fn)
    if hasattr(m, '_perf_action_original'):
        m._runtime_action = m._perf_action_original
        del m._perf_action_original
    for name in ('_perf_originals', '_perf_samples'):
        if hasattr(m, name):
            delattr(m, name)
    old_action, old_restore = m._runtime_action, m._runtime_restore
    m._maintenance_originals = {name: getattr(m, name) for name in (
        '_runtime_action', '_runtime_restore', '_runtime_maintain',
        '_runtime_owned', '_runtime_weapon_behavior_pairs', '_runtime_write',
        '_runtime_camera_readback', '_runtime_key', '_runtime_behaviors', '_cls') if hasattr(m, name)}
    base_key = m._runtime_key
    base_behaviors = getattr(m, '_runtime_behaviors', None)
    base_cls = getattr(m, '_cls', None)
    seen_weapons = {}
    classes = {}
    context = [None]
    cycle_cache = {}
    missing_fields = {}
    weapon_plan = [None, None, 0., None]
    stats = dict(ticks=0, runs=0, writes=0, last_ms=0., max_ms=0., total_ms=0.)

    def cached(name, obj, read):
        if context[0] is None:
            return read(obj)
        key = (name, m._addr(obj))
        if key not in cycle_cache:
            cycle_cache[key] = read(obj)
        return cycle_cache[key]

    def identity(obj, attr, sub=''):
        return (cached('key', obj, lambda o: base_key(o, '')[0]), attr, sub)

    def behaviors(obj):
        return cached('behaviors', obj, lambda o: list(base_behaviors(o)))

    def cls_name(obj):
        return cached('class', obj, base_cls)

    def apply_weapons(pawn, force, now):
        config = m._RUNTIME_STATE
        feature_targets = {
            'no_spread': (config['no_spread'], 0., None),
            'no_recoil': (config['no_recoil'], 0., None),
            'instant_reload': (config['instant_reload'], .03, None),
            'no_overheat': (config['no_overheat'], 0., None),
            'fire_rate': (config['fire_rate_scale'] != 1., None, config['fire_rate_scale']),
            'magazine_capacity': (config['magazine_capacity_scale'] != 1., None, config['magazine_capacity_scale']),
            'projectile_speed': (config['projectile_speed_scale'] != 1., None, config['projectile_speed_scale']),
        }
        weapons = owned('Weapon', pawn)
        signature = (m._addr(pawn), tuple(m._addr(w) for w in weapons), tuple(feature_targets.items()))
        # Rebuild on new actors/settings. Periodically compare only behavior
        # identities to detect an in-place behavior graph replacement.
        graph_changed = False
        if now - weapon_plan[2] > .5:
            graph = tuple((m._addr(w), tuple(m._addr(b) for b in behaviors(w))) for w in weapons)
            graph_changed = graph != weapon_plan[3]
            weapon_plan[2:4] = [now, graph]
        if force or signature != weapon_plan[0] or graph_changed or weapon_plan[1] is None:
            count = m._runtime_apply_weapon_features(pawn)
            live = {identity(b, '')[0]: (w, b) for w in weapons for b in behaviors(w)}
            rows = {}
            for feature, (enabled, value, scale) in feature_targets.items():
                if not enabled:
                    continue
                for (key, attr, sub), (_, original) in m._RUNTIME_ORIGINALS.get(feature, {}).items():
                    pair = live.get(key)
                    if pair is None:
                        continue
                    if key not in rows:
                        rows[key] = (WeakPointer(pair[1]), {}, WeakPointer(pair[0]))
                    target_value = value
                    if feature == 'instant_reload' and attr == 'MinReloadTime':
                        target_value = 0.
                    elif feature == 'no_overheat' and attr == 'CooldownRate':
                        target_value = 100.
                    target = m._runtime_target(original, target_value, scale, 1 if feature == 'magazine_capacity' else None)
                    rows[key][1].setdefault(attr, {})[sub] = target
            weapon_plan[0:2] = [signature, ValueBindings(list(rows.values()))]
            return count
        writes, invalid, magazine_changes = weapon_plan[1].apply()
        if invalid:
            weapon_plan[0] = None
        m._runtime_finalize_magazine_changes(pawn, magazine_changes)
        return writes

    def actors(pawn):
        equipped = m._get_field(pawn, 'EquippedInventorySlots')
        slots = m._get_field(equipped, 'items')
        result = []
        addresses = set()
        for slot in m._safe(lambda: list(slots), []) or []:
            actor = m._live_interface_object(m._get_field(slot, 'InstancedInventory'))
            address = m._addr(actor) if actor is not None else 0
            if address and address not in addresses:
                result.append(actor)
                addresses.add(address)
        return result

    def owned(class_name, pawn):
        cls = classes.get(class_name)
        if cls is None:
            cls = m._safe(lambda: m.unrealsdk.find_class(class_name))
            if cls is not None:
                classes[class_name] = cls
        if cls is None:
            return []
        rows = context[0] if context[0] is not None else actors(pawn)
        return [obj for obj in rows if m._safe(lambda obj=obj: obj.Class._inherits(cls), False)]

    def weapon_pairs(pawn, *, include_saved):
        current = owned('Weapon', pawn)
        for obj in current:
            seen_weapons[m._runtime_key(obj, '')[0]] = WeakPointer(obj)
        selected = list(current)
        if include_saved:
            selected = []
            for key, weak in list(seen_weapons.items()):
                obj = weak()
                if obj is None:
                    seen_weapons.pop(key, None)
                else:
                    selected.append(obj)
        return [(weapon, behavior) for weapon in selected for behavior in m._runtime_behaviors(weapon)]

    def write(feature, obj, attr, *, value=None, scale=None, minimum=None):
        if obj is None:
            return 0
        # Most behavior classes do not own most of the legacy feature fields.
        # Avoid repeating failed reflection lookups at 25 Hz. The weak UClass
        # proves that the same schema is still alive before reusing the miss.
        cls = m._get_field(obj, 'Class')
        absent = None
        if cls is not None:
            address = m._addr(cls)
            existing = missing_fields.get(address)
            if existing is None or existing[0]() is None:
                existing = (WeakPointer(cls), set())
                missing_fields[address] = existing
            absent = existing[1]
            if attr in absent:
                return 0
        holder = m._safe(lambda: getattr(obj, attr, None))
        if holder is None:
            if absent is not None:
                absent.add(attr)
            return 0
        scalar = m._runtime_number(holder)
        rows = [('', holder)] if scalar else [(sub, m._get_field(holder, sub)) for sub in ('Value', 'BaseValue')]
        writes = 0
        for sub, current in rows:
            if not m._runtime_number(current):
                continue
            ref = None
            key = m._runtime_key(obj, attr, sub)
            if feature not in m._RUNTIME_TRANSIENT_FEATURES:
                try:
                    ref = WeakPointer(obj)
                except TypeError:
                    # Reflected structs are not UObjects. Reacquire them from
                    # their weak owner rather than retaining a stale UStruct.
                    if feature in ('backpack_size', 'bank_size'):
                        parent = m.GAME.player_state
                        field = 'BackpackContainer' if feature == 'backpack_size' else 'BankContainer'
                    else:
                        parent = m._runtime_pawn()
                        field = 'HealthState' if feature == 'repairkit_no_cd' else 'DamageCauserData'
                    parent_ref = WeakPointer(parent)
                    ref = lambda parent_ref=parent_ref, field=field: m._get_field(parent_ref(), field) if parent_ref() is not None else None
                    key = (m._runtime_key(parent, '')[0] + '.' + field, attr, sub)
            originals = m._RUNTIME_ORIGINALS.setdefault(feature, {})
            if key not in originals:
                originals[key] = (ref, current)
            target = m._runtime_target(originals[key][1], value, scale, minimum)
            if math.isclose(float(current), float(target), rel_tol=1e-6, abs_tol=1e-7):
                continue
            try:
                setattr(obj if scalar else getattr(obj, attr), attr if scalar else sub, target)
                writes += 1
            except Exception:
                pass
        return writes

    def restore(feature):
        if feature in m._RUNTIME_TRANSIENT_FEATURES:
            return old_restore(feature)
        writes = 0
        for (_, attr, sub), (ref, original) in m._RUNTIME_ORIGINALS.pop(feature, {}).items():
            obj = ref() if callable(ref) else ref
            if obj is None:
                continue
            try:
                setattr(getattr(obj, attr) if sub else obj, sub or attr, original)
                writes += 1
            except Exception:
                pass
        return writes

    def maintain(force=False, *, refresh_xp=True):
        stats['ticks'] += 1
        now = time.perf_counter()
        if not force and now-m._RUNTIME_LAST_MAINTAIN < m._RUNTIME_INTERVAL:
            return 0
        m._RUNTIME_LAST_MAINTAIN = now
        try:
            if refresh_xp:
                m._runtime_refresh_xp_context()
            state = m._RUNTIME_STATE
            active = any(state.get(k) for k in ('no_spread','no_recoil','instant_reload','no_overheat',
                'health_lock','shield_lock','repairkit_no_cd','skill_no_cd','gadget_no_cd',
                'stamina_lock','infinite_jump','guaranteed_crit','backpack_size'))
            active |= any(float(state.get(k, 1.)) != 1. for k in ('fire_rate_scale','movement_speed_scale',
                'jump_height_scale','critical_damage_scale','magazine_capacity_scale','projectile_speed_scale'))
            active |= bool(m._RUNTIME_ORIGINALS or m._RUNTIME_JUMP_GOALS)
            if not active:
                return 0
            pawn = m._runtime_pawn()
            if pawn is None:
                return 0
            context[0] = actors(pawn)
            # The formerly unconditional FOV scan has deliberately been removed.
            writes = apply_weapons(pawn, force, now)
            writes += m._runtime_apply_player_features(pawn)
            writes += m._runtime_apply_jump_scale(pawn)
            writes += m._runtime_apply_infinite_jump(pawn)
            writes += m._runtime_apply_backpack_size()
            size = int(state.get('bank_size') or 0)
            if 'bank_size' in m._RUNTIME_ORIGINALS:
                writes += write('bank_size',m._get_field(m.GAME.player_state,'BankContainer'),'MaxSize',value=size) if size else restore('bank_size')
            stats['writes'] += writes
            return writes
        finally:
            context[0] = None
            cycle_cache.clear()
            ms = (time.perf_counter()-now)*1000
            stats['runs'] += 1
            stats['last_ms'] = ms
            stats['max_ms'] = max(stats['max_ms'],ms)
            stats['total_ms'] += ms

    def action(name, params=None):
        if name in ('set_fov','reset_fov','set_base_fov','set_viewmodel_fov'):
            return dict(ok=False, action=name, error='FOV controls have been removed.')
        if name == 'maintenance_diagnostics':
            pawn = m._runtime_pawn()
            result = dict(ok=True,version=VERSION,revision=REVISION,interval=m._RUNTIME_INTERVAL,stats=dict(stats),discovery_strategy='equipped_slots',
                          runtime_settings=dict(m._RUNTIME_STATE),pawn_available=pawn is not None,
                          maintain_errors=getattr(m, '_RUNTIME_MAINTAIN_ERROR_COUNT', 0),
                          equipped=[dict(cls=m._cls(a),path=m._path(a)) for a in actors(pawn)],
                          saved_originals={k:len(v) for k,v in m._RUNTIME_ORIGINALS.items()})
            if (params or {}).get('clear'):
                for key in stats:
                    stats[key] = 0
            return result
        result = old_action(name, params)
        # Runtime attribute changes are not inventory mutations. Avoid expensive
        # editor inventory+stats re-decodes when only a transient scale changed.
        if name in ('set_magazine_capacity_scale','set_projectile_speed_scale'):
            result['runtime_changed'] = bool(result.pop('changed', False))
            if not result.get('ok') and (result.get('readback') or {}).get('available') and result.get('value') == (params or {}).get('value'):
                feature = 'magazine_capacity' if name.startswith('set_magazine') else 'projectile_speed'
                requested = float(result['value'])
                expected = m._RUNTIME_ORIGINALS.get(feature, {})
                actual = {m._runtime_key(obj, '')[0]: obj for _, obj in weapon_pairs(m._runtime_pawn(), include_saved=False)}
                verified = []
                for (identity, attr, sub), (_, original) in expected.items():
                    obj = actual.get(identity)
                    if obj is None:
                        continue
                    holder = m._get_field(obj, attr)
                    current = m._get_field(holder, sub) if sub else holder
                    target = m._runtime_target(original, None, requested, 1 if feature == 'magazine_capacity' else None)
                    verified.append(m._runtime_number(current) and math.isclose(float(current),float(target),rel_tol=1e-6,abs_tol=1e-7))
                result['ok'] = bool(verified) and all(verified)
                if result['ok']:
                    result.pop('error',None)
        return result

    maintain._maintenance_revision = REVISION
    m._runtime_owned = owned
    m._runtime_key = identity
    if base_behaviors is not None:
        m._runtime_behaviors = behaviors
    if base_cls is not None:
        m._cls = cls_name
    m._runtime_weapon_behavior_pairs = weapon_pairs
    m._runtime_write = write
    m._runtime_restore = restore
    m._runtime_maintain = maintain
    m._runtime_action = action
    # Snapshot polling must not revive the removed global camera enumeration.
    m._runtime_camera_readback = lambda: {'available': False, 'removed': True}
    m.__version__ = VERSION
    if getattr(m, 'mod', None) is not None:
        m._safe(lambda: setattr(m.mod, 'version', VERSION))
    m._maintenance_revision = REVISION
    m._log('Installed '+REVISION+'; equipped-slot maintenance, FOV disabled.')
