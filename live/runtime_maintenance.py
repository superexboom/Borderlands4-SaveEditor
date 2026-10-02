"""BL4Live 0.10.25 maintenance repair, installed in the game's bl4_live package.

All calls run on the existing game-thread dispatcher. No DLL or native offset
changes. Enumerate equipped slots, never the global UObject array, in the hot path.
"""
import math
import time

VERSION = '0.10.28'
REVISION = 'slot-maintenance-20261002.12'

# Weapon values, movement, crit, stamina and cooldown features change only when the
# game rebuilds them (equip, reload, buffs): refresh them at 5 Hz.  Health and shield
# locks stay on the 25 Hz tick but refill only what is below full.
SLOW_INTERVAL = 0.2
SKILL_TTL = 1.0
EQUIPPED_TTL = 0.25
HEALTH_LAYER_TTL = 2.0


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
    from unrealsdk.unreal import UObject, WeakPointer
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
        '_runtime_camera_readback', '_runtime_key', '_runtime_behaviors', '_cls',
        '_select_player_controller', '_runtime_snapshot', '_runtime_refill_health_types',
        '_runtime_selected_action_skill', '_runtime_set_combat_xp_scale',
        '_runtime_refresh_xp_context', '_runtime_add_xp_modifier', '_runtime_combat_xp_value',
        '_runtime_remove_xp_modifiers') if hasattr(m, name)}
    base_key = m._runtime_key
    base_behaviors = getattr(m, '_runtime_behaviors', None)
    base_cls = getattr(m, '_cls', None)
    seen_weapons = {}
    classes = {}
    context = [None]
    cycle_cache = {}
    missing_fields = {}
    weapon_plan = [None, None, 0., None]
    stats = dict(ticks=0, runs=0, slow_runs=0, writes=0, last_ms=0., max_ms=0., total_ms=0.)
    key_cache = {}
    equipped_cache = [0., 0, []]
    slow_last = [0.]
    health_layers = {}
    struct_missing = {}
    skill_cache = [0., 0, None, '']
    base_selected_skill = getattr(m, '_runtime_selected_action_skill', None)

    def cached(name, obj, read):
        if context[0] is None:
            return read(obj)
        key = (name, m._addr(obj))
        if key not in cycle_cache:
            cycle_cache[key] = read(obj)
        return cycle_cache[key]

    def identity(obj, attr, sub=''):
        # The reflected path is rebuilt from strings on every call; keep it per live
        # object (weakly, re-checked by address) instead of per maintenance cycle.
        address = m._addr(obj)
        hit = key_cache.get(address) if address else None
        if hit is not None:
            live = hit[0]()
            if live is not None and m._addr(live) == address:
                return (hit[1], attr, sub)
        base = base_key(obj, '')[0]
        if address and isinstance(obj, UObject):
            if len(key_cache) > 1024:
                key_cache.clear()
            key_cache[address] = (WeakPointer(obj), base)
        return (base, attr, sub)

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

    def equipped(pawn, now):
        """Equipped inventory actors, re-enumerated at most every EQUIPPED_TTL seconds."""
        address = m._addr(pawn)
        if address == equipped_cache[1] and now - equipped_cache[0] < EQUIPPED_TTL:
            rows = [weak() for weak in equipped_cache[2]]
            if all(row is not None for row in rows):
                return rows
        rows = actors(pawn)
        equipped_cache[:] = [now, address, [WeakPointer(row) for row in rows]]
        return rows

    def refill_below_full(pawn, needle, now, *, always=False):
        """Health/shield lock.  The fast tick refills only a layer below 100 %; the 5 Hz
        pass (always=True) refills unconditionally.  Health-type handles are cached: each
        read converts the whole resolved definition and was the costliest part."""
        lib = m._runtime_static('DamageStatics')
        if lib is None:
            return 0
        key = (m._addr(pawn), needle)
        entry = health_layers.get(key)
        if entry is None or now - entry[0] > HEALTH_LAYER_TTL:
            rows = []
            health = m._get_field(pawn, 'HealthState')
            for state in m._safe(lambda: list(m._get_field(health, 'HealthTypeStates')), []) or []:
                handle = m._get_field(state, 'HealthType')
                label = str(m._safe(lambda handle=handle: handle._name, '') or '').lower()
                if needle == 'shield':
                    selected = 'shield' in label and 'overshield' not in label
                else:
                    selected = 'flesh' in label
                if selected:
                    layer = m._safe(lambda handle=handle: int(lib.GetHealthPoolLayerOfType(pawn, handle, True)), -1)
                    rows.append((handle, layer))
            if len(health_layers) > 8:
                health_layers.clear()
            entry = health_layers[key] = (now, rows)
        writes = 0
        for handle, layer in entry[1]:
            percent = 0. if always or layer < 0 else m._safe(lambda layer=layer: float(lib.GetHealthPoolPercent(pawn, layer)), 0.)
            if percent < 0.999:
                try:
                    lib.RefillHealthPercent(Context=pawn, HealthType=handle, Percent=1.0, MaxPercent=1.0)
                    writes += 1
                except Exception:
                    pass
        return writes

    def jumps_used(pawn):
        """Infinite jump between full passes: rewrite only once a jump counter moved."""
        movement = m._get_field(pawn, 'OakCharacterMovement') or m._get_field(pawn, 'CharacterMovement')
        for obj in (pawn, movement):
            if obj is None:
                continue
            for field in ('JumpCurrentCount', 'CurrentJumpCount', 'JumpedCount'):
                value = m._safe(lambda obj=obj, field=field: getattr(obj, field, 0), 0)
                if m._runtime_number(value) and value:
                    return True
        return False

    def refill_health_types(pawn, needle):
        return refill_below_full(pawn, needle, time.perf_counter(), always=True)

    def selected_action_skill(pawn):
        """The slotted action skill, re-resolved at most every SKILL_TTL seconds."""
        now = time.perf_counter()
        address = m._addr(pawn)
        if address == skill_cache[1] and now - skill_cache[0] < SKILL_TTL:
            if skill_cache[2] is None:
                return None  # no slotted action skill a moment ago (also cached: the scan is the cost)
            script = skill_cache[2]()
            if script is not None:
                return script, skill_cache[3]
        found = base_selected_skill(pawn)
        if found is None:
            skill_cache[:] = [now, address, None, '']
            return None
        skill_cache[:] = [now, address, WeakPointer(found[0]), found[1]]
        return found

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
        if not isinstance(obj, UObject):
            # Reflected structs (HealthState, DamageCauserData) have no Class; asking
            # for one is a slow failing lookup.  Key their misses by struct type.
            absent = struct_missing.setdefault(m._safe(lambda: obj._type.Name, '') or '', set())
            if attr in absent:
                return 0
            cls = None
        else:
            try:
                cls = obj.Class
            except Exception:
                cls = None
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
            originals = m._RUNTIME_ORIGINALS.setdefault(feature, {})
            if feature not in m._RUNTIME_TRANSIENT_FEATURES and isinstance(obj, UObject):
                if key not in originals:  # the weak reference only serves a later restore
                    ref = WeakPointer(obj)
            elif feature not in m._RUNTIME_TRANSIENT_FEATURES:
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
            context[0] = equipped(pawn, now)
            # The formerly unconditional FOV scan has deliberately been removed.
            writes = 0
            if force or now - slow_last[0] >= SLOW_INTERVAL:
                slow_last[0] = now
                stats['slow_runs'] += 1
                writes += apply_weapons(pawn, force, now)
                writes += m._runtime_apply_player_features(pawn)  # includes the full health/shield refill
                writes += m._runtime_apply_backpack_size()
                size = int(state.get('bank_size') or 0)
                if 'bank_size' in m._RUNTIME_ORIGINALS:
                    writes += write('bank_size',m._get_field(m.GAME.player_state,'BankContainer'),'MaxSize',value=size) if size else restore('bank_size')
            else:
                if state.get('health_lock'):
                    writes += refill_below_full(pawn, 'health', now)
                if state.get('shield_lock'):
                    writes += refill_below_full(pawn, 'shield', now)
            # Jump features act on the jump in progress: keep them on every tick.
            writes += m._runtime_apply_jump_scale(pawn)
            if slow_last[0] == now or not state.get('infinite_jump') or jumps_used(pawn):
                writes += m._runtime_apply_infinite_jump(pawn)
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
            result = dict(ok=True,version=VERSION,revision=REVISION,interval=m._RUNTIME_INTERVAL,slow_interval=SLOW_INTERVAL,stats=dict(stats),discovery_strategy='equipped_slots',
                          runtime_settings=dict(m._RUNTIME_STATE),pawn_available=pawn is not None,
                          maintain_errors=getattr(m, '_RUNTIME_MAINTAIN_ERROR_COUNT', 0),
                          equipped=[dict(cls=m._cls(a),path=m._path(a)) for a in actors(pawn)],
                          saved_originals={k:len(v) for k,v in m._RUNTIME_ORIGINALS.items()},
                          xp=dict(applied=getattr(m, '_XP_APPLIED', None), guard=dict(getattr(m, '_XP_GUARD', None) or {})))
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
    m._runtime_refill_health_types = refill_health_types
    if base_selected_skill is not None:
        m._runtime_selected_action_skill = selected_action_skill
    m._runtime_action = action
    # Snapshot polling must not revive the removed global camera enumeration.
    m._runtime_camera_readback = lambda: {'available': False, 'removed': True}
    install_player_selection(m)
    install_xp_guard(m)
    install_drop_replay(m)
    install_skill_builds(m)
    m.__version__ = VERSION
    if getattr(m, 'mod', None) is not None:
        m._safe(lambda: setattr(m.mod, 'version', VERSION))
    m._maintenance_revision = REVISION
    m._log('Installed '+REVISION+'; equipped-slot maintenance, FOV disabled.')


def install_xp_guard(m):
    """Combat XP multiplier without ever removing a modifier.

    Measured 2026-10-02: GbxAttributeBlueprintLibrary.RemoveModifierFromGbxAttribute
    (and the legacy RemoveAttributeModifier) report success for the handle Python
    gets back from AddModifierToGbxAttribute, but the modifier stays: the handle
    arrives as an empty struct.  Every modifier the base code ever added therefore
    stayed in force.  Its "compensation" (add 1/scale, then remove both) kept the
    numbers right while nothing was really removed, but the pawn-change rebind
    (death, driving, travel) removed without compensating and added another scale
    on top: 3.3 -> 9.9 -> 29.7, while the editor showed 1x.

    Here the mod only ever adds: it tracks the product of everything it applied
    (``m._XP_APPLIED``) and reaches a new scale with one factor new/old.  The
    modifier lives on the player's blackboard, so it is added and read through the
    controller; death and vehicles need no handling.  Once a second the value is
    checked: back at the bare base means the modifiers are gone (map travel) and the
    scale is re-applied; any other difference is a real XP bonus change and becomes
    the new base.
    """
    if not hasattr(m, '_runtime_set_combat_xp_scale') or not hasattr(m, '_runtime_add_xp_modifier'):
        return
    base_add = m._runtime_add_xp_modifier
    if not isinstance(getattr(m, '_XP_APPLIED', None), float):
        # Hot install over the base code: its live modifiers multiply to its scale.
        m._XP_APPLIED = float(m._RUNTIME_REGISTRY.get('xp_scale', 1.0) or 1.0)
    if not isinstance(getattr(m, '_XP_GUARD', None), dict):
        m._XP_GUARD = {}

    def controller():
        return m._player_controller()

    def close(a, b):
        return a is not None and b is not None and abs(a - b) <= max(0.005, abs(b) * 0.005)

    def scale_now():
        return float(m._RUNTIME_STATE.get('experience_reward_scale', 1.0) or 1.0)

    def value():
        pc = controller()
        library = m._runtime_static('GbxAttributeBlueprintLibrary')
        if pc is None or library is None:
            return None
        try:
            result = float(library.GetValueOfAttribute(m._RUNTIME_XP_ATTRIBUTE, pc, -1.0))
        except Exception:
            return None
        return None if result == -1.0 else result

    def add(library, _context, factor):
        return base_add(library, controller(), factor)

    def apply_factor(factor):
        """Multiply the live value by ``factor`` (one more modifier); False when it failed."""
        if abs(factor - 1.0) < 1e-6:
            return True
        library = m._runtime_static('GbxAttributeBlueprintLibrary')
        if library is None or controller() is None:
            return False
        handle, action, error = add(library, None, factor)
        if handle is None or action != 0:
            m._warn(f'combat XP modifier x{factor:.4f} failed: {error}')
            return False
        m._XP_APPLIED *= factor
        return True

    def set_scale(requested):
        scale = max(1.0, min(10.0, float(requested)))
        current = value()
        if current is None:
            return {'ok': False, 'error': 'combat XP attribute unavailable (no player)', 'state': dict(m._RUNTIME_STATE)}
        base = current / m._XP_APPLIED
        if not apply_factor(scale / m._XP_APPLIED):
            return {'ok': False, 'error': 'combat XP modifier failed', 'state': dict(m._RUNTIME_STATE)}
        m._RUNTIME_STATE['experience_reward_scale'] = scale
        m._RUNTIME_REGISTRY['xp_scale'] = scale
        m._RUNTIME_XP_MODIFIERS[:] = []  # the base code's handles: removal never worked
        pc = controller()
        m._RUNTIME_XP_CONTEXT_KEY = (m._addr(pc), m._path(pc)) if scale != 1.0 and pc is not None else None
        m._RUNTIME_REGISTRY['xp_context_key'] = m._RUNTIME_XP_CONTEXT_KEY
        m._XP_GUARD = dict(base=base, checked=time.perf_counter())
        m._RUNTIME_XP_REFRESH_STATUS = {'ok': True, 'value_after': value(), 'expected': base * scale}
        return {'ok': True, 'feature': 'experience_reward_scale', 'value': scale, 'scope': 'combat_xp',
                'resolved': value(), 'state': dict(m._RUNTIME_STATE)}

    def remove_all(*, compensate=True):
        del compensate
        result = set_scale(1.0)
        return 1 if result.get('ok') else 0

    def refresh():
        guard = m._XP_GUARD
        if not guard:
            return False
        now = time.perf_counter()
        if now - guard.get('checked', 0.) < 1.0:
            return False
        guard['checked'] = now
        current = value()
        if current is None:
            return False
        if close(current, guard['base'] * m._XP_APPLIED):
            return False
        scale = scale_now()
        if scale != 1.0 and close(current, guard['base']):
            # Our modifiers went with the old blackboard (map travel): start over.
            m._XP_APPLIED = 1.0
            return bool(set_scale(scale).get('ok'))
        guard['base'] = current / m._XP_APPLIED  # a real XP bonus changed underneath
        return False

    m._runtime_add_xp_modifier = add
    m._runtime_combat_xp_value = value
    m._runtime_set_combat_xp_scale = set_scale
    m._runtime_remove_xp_modifiers = remove_all
    m._runtime_refresh_xp_context = refresh


def install_drop_replay(m):
    """Retire the dedicated-drop hook (the editor no longer offers the feature).

    It spawned the dead actor's ItemPoolList through SpawnItemsFromItemPoolUsingActor_Drop
    with a hard-coded GameDataHandle type (4160); the game expects 4144 there, rejects
    every call ("type mismatch") and never resolves ItemPoolList names anyway, so it
    dropped nothing.  Re-running OakCharacter.DropLoot on a dead enemy (tested
    2026-10-02 on 16 kills) drops nothing either, and DropLoot / kill XP never reach a
    UFunction hook because the game calls them natively.  The hook stays registered
    (hooks survive reloads); its callback now does nothing.
    """
    if isinstance(getattr(m, '_CALLBACKS', None), dict) and 'drop' in m._CALLBACKS:
        m._CALLBACKS['drop'] = lambda obj, args, ret, func: None
        m._RUNTIME_STATE['dedicated_drop_100'] = False


def install_skill_builds(m):
    """Live skill builds through the game's own progress graph server functions.

    ``skill_snapshot`` reads every GbxProgressGraph on the player's
    GbxProgressionManager (index-addressed nodes: points spent, bonus points,
    activation).  ``skill_apply`` resets the graphs of the requested point pools,
    spends the wanted points again (several passes, so tier/trunk prerequisites
    resolve), toggles activations that still differ (augments, capstones, action
    skills: the owning group is found by trying each group), and optionally sets
    bonus points (overlimit).  Every step goes through Server_SpendProgressPoints /
    Server_ResetSpentPoints / Server_ActivateNodeInGroup / Server_AddBonusPoints,
    so the game validates points and prerequisites itself.  Verified in game on
    2026-10-02 (reset + respend, augment swap, bonus add/remove).
    """
    base_action = m._runtime_action

    def graphs():
        manager = m._get_field(m._runtime_pawn(), 'GbxProgressionManager')
        rows = m._safe(lambda: list(m._get_field(manager, 'ProgressGraphs')), []) if manager is not None else []
        return manager, rows or []

    def graph_name(graph):
        return str(m._safe(lambda: graph.ProgressGraphDef._name, '') or '')

    def node_rows(graph):
        return [dict(i=i, spent=int(n.ProgressPointsSpent), bonus=int(n.BonusPoints), active=bool(n.bIsActivated),
                     level=int(n.ActivationLevel), unlocked=bool(n.bIsUnlocked))
                for i, n in enumerate(list(graph.nodes))]

    def describe(graph):
        definition = graph.ProgressGraphDef
        return dict(graph=graph_name(graph), type=int(m._safe(lambda: definition.GraphType, 0) or 0),
                    pool=str(getattr(m._safe(lambda: definition.PointPool), '_name', '') or ''),
                    groups=len(m._safe(lambda: list(graph.Groups), []) or []), nodes=node_rows(graph))

    def snapshot():
        manager, rows = graphs()
        if manager is None:
            return dict(ok=False, error='no progression manager (no player in the world)')
        container = m._get_field(manager, 'ProgressPointsContainer')
        pools = m._safe(lambda: [int(v) for v in m._get_field(container, 'PointsAcquiredPerPool')], [])
        return dict(ok=True, points_per_pool=pools, graphs=[describe(graph) for graph in rows])

    def set_activation(graph, index, on, level=0):
        groups = len(m._safe(lambda: list(graph.Groups), []) or []) or 1
        for group in range(groups):
            graph.Server_ActivateNodeInGroup(group, index, bool(on), int(level))
            if bool(graph.nodes[index].bIsActivated) == bool(on):
                return True
        return False

    def apply(params):
        _, rows = graphs()
        by_name = {graph_name(graph).lower(): graph for graph in rows}
        targets = {}
        for entry in params.get('graphs') or []:
            graph = by_name.get(str(entry.get('graph') or '').lower())
            if graph is not None:
                targets[graph_name(graph).lower()] = (graph, {int(n['i']): n for n in entry.get('nodes') or []})
        unknown = [str(e.get('graph')) for e in params.get('graphs') or [] if str(e.get('graph') or '').lower() not in by_name]
        bad_nodes = [f"{name}/{index}" for name, (graph, nodes) in targets.items()
                     for index in nodes if not 0 <= index < len(list(graph.nodes))]
        if unknown or bad_nodes or not targets:
            # Another class's build (or a stale catalog): refuse before anything is reset.
            return dict(ok=False, error='build does not match this character', unknown_graphs=unknown,
                        bad_nodes=bad_nodes[:20], applied=0)
        reset_pools = {str(p).lower() for p in params.get('reset_pools') or []}
        # 1. reset every graph of the requested pools (and every target point graph)
        for graph in rows:
            info = describe(graph)
            if info['pool'].lower() in reset_pools or (graph_name(graph).lower() in targets and info['type'] == 0):
                graph.Server_ResetSpentPoints()
        # 2. spend, in passes, until nothing more is accepted
        for _ in range(8):
            progress = 0
            for graph, nodes in targets.values():
                for index in sorted(nodes):
                    want = int(nodes[index].get('spent') or 0)
                    have = int(graph.nodes[index].ProgressPointsSpent)
                    if want > have:
                        graph.Server_SpendProgressPoints(index, want - have)
                        progress += int(graph.nodes[index].ProgressPointsSpent) - have
            if not progress:
                break
        # 3. activations that still differ (activation graphs; only nodes the build lists)
        for graph, nodes in targets.values():
            if describe(graph)['type'] != 1:
                continue
            current = {row['i'] for row in node_rows(graph) if row['active']}
            wanted = {i for i, node in nodes.items() if node.get('active')}
            for index in sorted(current - wanted):
                set_activation(graph, index, False)
            for index in sorted(wanted - current):
                set_activation(graph, index, True, int(nodes[index].get('level') or 0))
        # 4. bonus points (overlimit) only on request
        if params.get('bonus'):
            for graph, nodes in targets.values():
                for index, node in nodes.items():
                    delta = int(node.get('bonus') or 0) - int(graph.nodes[index].BonusPoints)
                    if delta:
                        graph.Server_AddBonusPoints(index, delta)
        # 5. verify
        mismatches = []
        for name, (graph, nodes) in targets.items():
            live = node_rows(graph)
            graph_type = describe(graph)['type']
            for index, node in nodes.items():
                row = live[index] if index < len(live) else None
                if row is None:
                    mismatches.append(dict(graph=name, i=index, reason='no such node'))
                    continue
                if int(node.get('spent') or 0) != row['spent']:
                    mismatches.append(dict(graph=name, i=index, want=node.get('spent'), have=row['spent']))
                if graph_type == 1 and bool(node.get('active')) != row['active']:
                    mismatches.append(dict(graph=name, i=index, want_active=bool(node.get('active')), active=row['active']))
                if params.get('bonus') and int(node.get('bonus') or 0) != row['bonus']:
                    mismatches.append(dict(graph=name, i=index, want_bonus=node.get('bonus'), bonus=row['bonus']))
        return dict(ok=not mismatches and not unknown, applied=len(targets), unknown_graphs=unknown,
                    mismatches=mismatches[:40], snapshot=snapshot())

    def action(name, params=None):
        if name == 'skill_snapshot':
            return dict(action=name, **snapshot())
        if name == 'skill_apply':
            try:
                return dict(action=name, **apply(params or {}))
            except Exception as exc:
                return dict(ok=False, action=name, error=f'{type(exc).__name__}: {exc}')
        return base_action(name, params)

    m._runtime_action = action


def install_player_selection(m):
    """Let the editor choose whose character live mode reads and writes.

    A co-op host has one OakPlayerController per player, and the base picker
    took the fullest backpack, which was often a friend's. Every live read and
    write goes through GAME.player_controller, so choosing here moves all of
    them. The choice survives requests (it is kept on the module) and is
    matched by PlayerId + name, then by name, because map travel can recreate
    the PlayerState. Without a choice the local player wins.
    """
    if not hasattr(m, '_select_player_controller') or not hasattr(m, '_runtime_snapshot'):
        return
    base_snapshot = m._runtime_snapshot
    base_action = m._runtime_action
    if not isinstance(getattr(m, '_PLAYER_CHOICE', None), dict):
        m._PLAYER_CHOICE = None

    def text(value):
        return str(value or '').strip()

    def player_name(ps):
        get_name = m._safe(lambda: getattr(ps, 'GetPlayerName', None))
        name = text(m._safe(get_name, '')) if callable(get_name) else ''
        for attr in ('PlayerNamePrivate', 'PlayerName'):
            if name:
                break
            name = text(m._safe(lambda attr=attr: getattr(ps, attr, ''), ''))
        return name

    def player_id(ps):
        value = m._safe(lambda: int(m._get_field(ps, 'PlayerId')))
        return value if isinstance(value, int) else None

    def is_local(pc):
        for fn_name in ('IsLocalController', 'IsLocalPlayerController'):
            fn = m._safe(lambda fn_name=fn_name: getattr(pc, fn_name, None))
            if callable(fn):
                value = m._safe(fn)
                if value is not None:
                    return bool(value)
        player = m._get_field(pc, 'Player')
        return player is not None and 'localplayer' in m._cls(player).lower()

    def valid_samples(ps, counts):
        valid = 0
        for container in ('BackpackItems', 'BankItems'):
            holder = m._get_field(ps, container)
            arr = m._get_field(holder, 'items') if holder is not None else None
            count = (m._safe(lambda arr=arr: len(arr), 0) or 0) if arr is not None else 0
            counts[container] = count
            if container != 'BackpackItems':
                continue
            for i in range(min(count, 4)):
                entry = m._safe(lambda arr=arr, i=i: arr[i])
                inv_item = m._get_field(entry, 'InventoryItem') if entry is not None else None
                ident = m._get_item_identity(inv_item) if inv_item is not None else None
                if ident is not None and m._read_identity(ident).get('ok'):
                    valid += 1
        return valid

    def candidates():
        sdk = getattr(m, 'unrealsdk', None)
        found = m._safe(lambda: list(sdk.find_all('OakPlayerController', False)), []) if sdk else []
        rows = []
        for pc in found or []:
            ps = m._get_field(pc, 'PlayerState')
            if ps is None:
                continue
            counts = {}
            valid = valid_samples(ps, counts)
            name, pid, local = player_name(ps), player_id(ps), is_local(pc)
            if pid is not None:
                key = f'{pid}:{name}'
            else:
                key = f'name:{name}' if name else m._hex(m._addr(ps))
            info = dict(controller=m._hex(m._addr(pc)), player_state=m._hex(m._addr(ps)),
                        valid_samples=valid, name=name, player_id=pid, local=local, key=key, **counts)
            score = (1 if valid else 0, 1 if local else 0,
                     counts.get('BackpackItems', 0), counts.get('BankItems', 0))
            rows.append((score, pc, ps, info))
        return rows

    def select():
        rows = candidates()
        choice = m._PLAYER_CHOICE
        chosen = None
        if choice:
            for same in (lambda info: info['key'] == choice['key'],
                         lambda info: bool(choice['name']) and info['name'] == choice['name']):
                hits = [row for row in rows if same(row[3])]
                if hits:
                    chosen = max(hits, key=lambda row: row[0])
                    break
        mode = 'manual' if chosen is not None else 'auto'
        if chosen is None and rows:
            chosen = max(rows, key=lambda row: row[0])
        # One entry per player for the picker; stale menu previews have no
        # name, no items and no local player behind them.
        players = {}
        for _score, _pc, _ps, info in sorted(rows, key=lambda row: row[0], reverse=True):
            if info['name'] or info['valid_samples'] or info['local']:
                players.setdefault(info['key'], info)
        selection = dict(selected=chosen[3] if chosen else {}, candidates=[row[3] for row in rows],
                         players=sorted(players.values(), key=lambda info: (not info['local'], info['name'])),
                         mode=mode, choice=choice['key'] if choice else '')
        return (chosen[1], chosen[2], selection) if chosen else (None, None, selection)

    def player_rows():
        selection = m.GAME.selection or {}
        selected = (selection.get('selected') or {}).get('key')
        return [dict(key=info['key'], name=info['name'], local=info['local'],
                     selected=info['key'] == selected)
                for info in selection.get('players') or []]

    def snapshot():
        state = base_snapshot()
        if isinstance(state, dict):
            state['players'] = player_rows()
            state['player_mode'] = (m.GAME.selection or {}).get('mode', 'auto')
        return state

    def action(name, params=None):
        if name not in ('select_player', 'list_players'):
            return base_action(name, params)
        params = params or {}
        if name == 'list_players':
            return dict(ok=True, action=name, players=player_rows(),
                        mode=(m.GAME.selection or {}).get('mode', 'auto'))
        key = text(params.get('player'))
        before = m.GAME.player_state_addr
        if key in ('', 'auto'):
            m._PLAYER_CHOICE = None
        else:
            known = (m.GAME.selection or {}).get('players') or []
            info = next((p for p in known if p['key'] == key), None)
            if info is None:
                return dict(ok=False, action=name, error='player not found: ' + key, players=player_rows())
            m._PLAYER_CHOICE = dict(key=key, name=info['name'])
        m.GAME.refresh_containers()
        selection = m.GAME.selection or {}
        return dict(ok=m.GAME.player_state is not None, action=name,
                    changed=m.GAME.player_state_addr != before,
                    selected=selection.get('selected') or {}, mode=selection.get('mode', 'auto'),
                    players=player_rows())

    m._select_player_controller = select
    m._runtime_snapshot = snapshot
    m._runtime_action = action
