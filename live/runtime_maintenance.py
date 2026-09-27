"""BL4Live 0.10.25 maintenance repair, installed in the game's bl4_live package.

All calls run on the existing game-thread dispatcher. No DLL or native offset
changes. Enumerate equipped slots, never the global UObject array, in the hot path.
"""
import math
import time

VERSION = '0.10.28'
REVISION = 'slot-maintenance-20260927.1'


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
        '_runtime_camera_readback', '_runtime_key', '_runtime_behaviors', '_cls',
        '_select_player_controller', '_runtime_snapshot') if hasattr(m, name)}
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
    install_player_selection(m)
    m.__version__ = VERSION
    if getattr(m, 'mod', None) is not None:
        m._safe(lambda: setattr(m.mod, 'version', VERSION))
    m._maintenance_revision = REVISION
    m._log('Installed '+REVISION+'; equipped-slot maintenance, FOV disabled.')


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
