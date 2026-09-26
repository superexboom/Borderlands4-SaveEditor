"""BL4Live background workers: every bridge call runs on a QThread so the UI never blocks.

Used by ``ui_huskar.live_support.LiveManager``.
"""

import hashlib

from PyQt6.QtCore import QThread, pyqtSignal

from core import b_encoder


class _LiveFetchWorker(QThread):
    """Fetch live items off the GUI thread; emits the save-shaped dict back."""

    loaded = pyqtSignal(object, object)  # (yaml_like, err)

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge

    def run(self):
        from live.adapter import fetch_live_yaml
        try:
            yaml_like = fetch_live_yaml(self._bridge)
            err = None
        except Exception as e:
            yaml_like = None
            err = f"{type(e).__name__}: {e}"
        self.loaded.emit(yaml_like, err)


_LIVE_INVENTORY_MUTATION_ACTIONS = frozenset({'claim_lost_loot'})


def _spawn_delivered(result, count):
    """True when the game created every requested item with the requested serial.

    BL4Live 0.10.26 also compares part pointers and reports ``ok: False`` when a
    named class mod perk ("ClassMod.x") resolves to an extra part, although the
    item is in the backpack with exactly the requested serial. Treat that as
    delivered so the editor neither reports a failure nor loses the new item.
    """
    if not isinstance(result, dict):
        return False
    if result.get("ok"):
        return True
    items = result.get("items")
    return (isinstance(items, list) and len(items) == int(count) > 0
            and int(result.get("added_count") or 0) == int(count)
            and all(isinstance(item, dict) and item.get("verify_serial") for item in items))


def _live_inventory_recovery_state(source):
    """Extract the recovery-lock tri-state and reason from any bridge result."""
    states = []
    reasons = []
    seen = set()

    def visit(value):
        if isinstance(value, dict):
            marker = id(value)
            if marker in seen:
                return
            seen.add(marker)
            pending = value.get('recovery_pending')
            if pending is True or pending is False:
                states.append(pending)
                if pending:
                    reasons.append(str(value.get('reason') or value.get('error') or ''))
            if str(value.get('code') or '').strip().lower() == 'inventory_recovery_pending':
                states.append(True)
                reasons.append(str(value.get('reason') or value.get('error') or ''))
            recovery = value.get('recovery')
            if recovery is True or (isinstance(recovery, dict) and recovery):
                states.append(True)
                reasons.append(str(
                    recovery.get('reason') if isinstance(recovery, dict)
                    else value.get('reason') or value.get('error') or ''
                ))
            for nested in value.values():
                if isinstance(nested, (dict, list, tuple)):
                    visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    visit(source)
    pending = True if True in states else False if False in states else None
    reason = next((item for item in reasons if item), '')
    return pending, reason


def _live_inventory_mutation_preflight(bridge):
    """Probe the optional recovery lock; only an explicit True blocks writes."""
    probe = {
        'blocked': False,
        'recovery_pending': None,
        'reason': '',
        'capabilities': None,
    }
    try:
        capabilities = bridge.loadout_capabilities()
    except Exception as exc:
        probe['error'] = f"{type(exc).__name__}: {exc}"
        return probe
    if not isinstance(capabilities, dict):
        probe['error'] = 'invalid loadout capabilities response'
        return probe

    probe['capabilities'] = capabilities
    pending, recovery_reason = _live_inventory_recovery_state(capabilities)
    probe['recovery_pending'] = pending
    probe['reason'] = str(capabilities.get('reason') or capabilities.get('error') or '')
    if pending is True:
        probe['blocked'] = True
        probe['reason'] = (
            recovery_reason or probe['reason']
            or 'unresolved loadout recovery requires review'
        )
    return probe


class _LiveRuntimeWorker(QThread):
    """Run one bridge runtime action without blocking the Qt event loop."""

    completed = pyqtSignal(str, object, object, bool)

    def __init__(self, bridge, action, params=None, *, quiet=False, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._action = str(action or '')
        self._params = dict(params or {})
        self._quiet = bool(quiet)
        self.mutation_preflight = None

    def run(self):
        try:
            if self._action in _LIVE_INVENTORY_MUTATION_ACTIONS:
                self.mutation_preflight = _live_inventory_mutation_preflight(self._bridge)
                if self.mutation_preflight['blocked']:
                    result = {
                        'ok': False,
                        'action': self._action,
                        'error': self.mutation_preflight['reason'],
                        'recovery_pending': True,
                        'capabilities': self.mutation_preflight.get('capabilities'),
                    }
                    self.completed.emit(self._action, result, None, self._quiet)
                    return
            result = self._bridge.runtime_action(self._action, **self._params)
            err = None
        except Exception as exc:
            result = None
            err = f"{type(exc).__name__}: {exc}"
        self.completed.emit(self._action, result, err, self._quiet)


class _LiveItemApplyWorker(QThread):
    """Persist one live item, then rebuild its equipped runtime actor when supported."""

    completed = pyqtSignal(object, object, object)

    def __init__(self, bridge, context, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._context = dict(context or {})
        self.mutation_preflight = None

    def run(self):
        context = self._context
        result = {
            'ok': False,
            'apply': None,
            'cache_rebuild': {
                'supported': False,
                'attempted': False,
                'ok': False,
                'uncertain': False,
            },
        }
        stage = 'capabilities'
        try:
            self.mutation_preflight = _live_inventory_mutation_preflight(self._bridge)
            result['mutation_preflight'] = self.mutation_preflight
            capabilities = self.mutation_preflight.get('capabilities')
            if isinstance(capabilities, dict):
                result['capabilities'] = capabilities
            cache = result['cache_rebuild']
            rebuild_declared = (
                isinstance(capabilities, dict) and 'rebuild_item_cache' in capabilities
            )
            publish_declared = (
                isinstance(capabilities, dict) and 'publish_backpack_item' in capabilities
            )
            cache['rebuild_supported'] = bool(
                rebuild_declared and capabilities.get('rebuild_item_cache') is True
            )
            cache['publish_backpack_supported'] = bool(
                publish_declared and capabilities.get('publish_backpack_item') is True
            )
            cache['supported'] = bool(
                cache['rebuild_supported'] or cache['publish_backpack_supported']
            )
            if rebuild_declared or publish_declared:
                cache['availability'] = (
                    'available' if cache['supported'] else 'temporarily_unavailable'
                )
                cache['capability_reason'] = self.mutation_preflight.get('reason', '')
            else:
                cache['availability'] = 'unsupported'
            if self.mutation_preflight['blocked']:
                result['failed_stage'] = 'recovery_gate'
                result['error'] = self.mutation_preflight['reason']
                self.completed.emit(context, result, None)
                return

            stage = 'apply'
            stable_kwargs = {}
            expected_handle = context.get('live_handle')
            expected_instance_id = context.get('live_instance_id')
            stable_metadata_present = (
                expected_handle is not None or expected_instance_id is not None
            )
            stable_identity_required = (
                context.get('container') == 'BackpackItems'
                and context.get('live_identity_supported') is True
            )
            if (
                context.get('container') == 'BackpackItems'
                and isinstance(expected_handle, int)
                and not isinstance(expected_handle, bool)
                and isinstance(expected_instance_id, int)
                and not isinstance(expected_instance_id, bool)
            ):
                stable_kwargs = {
                    'expect_handle': expected_handle,
                    'expect_instance_id': expected_instance_id,
                }
            elif (
                context.get('container') == 'BackpackItems'
                and (stable_metadata_present or stable_identity_required)
            ):
                result['apply'] = {
                    'ok': False,
                    'code': 'optimistic_lock_invalid_token',
                    'error': 'the live item identity token is incomplete',
                }
                result['failed_stage'] = 'apply_identity_precondition'
                self.completed.emit(context, result, None)
                return
            applied = self._bridge.apply(
                int(context['idx']),
                str(context['serial']),
                str(context['container']),
                expect_old=context.get('old_serial'),
                **stable_kwargs,
            )
            result['apply'] = applied
            result['ok'] = bool(applied.get('ok'))
            if not result['ok']:
                self.completed.emit(context, result, None)
                return
            actual_idx = applied.get('idx')
            if (
                applied.get('container') != context['container']
                or isinstance(actual_idx, bool) or not isinstance(actual_idx, int)
                or actual_idx < 0
            ):
                result['cache_rebuild']['error'] = 'live apply response coordinates changed'
                result['failed_stage'] = 'apply_postcondition'
                self.completed.emit(context, result, None)
                return
            context['actual_idx'] = actual_idx
            context['relocated'] = bool(
                applied.get('relocated') or actual_idx != context['idx']
            )

            applied_handle = applied.get('handle')
            applied_instance_id = applied.get('instance_id')
            applied_token_valid = (
                isinstance(applied_handle, int) and not isinstance(applied_handle, bool)
                and isinstance(applied_instance_id, int)
                and not isinstance(applied_instance_id, bool)
            )
            if stable_kwargs and (
                not applied_token_valid
                or applied_handle != expected_handle
                or applied_instance_id != expected_instance_id
            ):
                cache['error'] = 'live apply did not preserve the requested item identity'
                result['failed_stage'] = 'apply_identity_postcondition'
                self.completed.emit(context, result, None)
                return

            if context['container'] == 'BankItems':
                cache.update(ok=True, not_applicable=True, skipped='bank_item')
                self.completed.emit(context, result, None)
                return

            if not cache['supported']:
                self.completed.emit(context, result, None)
                return

            requested_fingerprint = hashlib.sha256(
                str(context['serial']).encode('ascii', 'replace')
            ).hexdigest()
            stage = 'probe'
            if applied_token_valid:
                probe = self._bridge.probe_item_runtime_cache(
                    container=context['container'],
                    handle=applied_handle,
                    instance_id=applied_instance_id,
                    expect_serial=context['serial'],
                )
            else:
                probe = self._bridge.probe_item_runtime_cache(
                    container=context['container'],
                    idx=actual_idx,
                    serial=context['serial'],
                    serial_sha256=requested_fingerprint,
                )
            cache['probe'] = probe
            if not probe.get('ok'):
                cache['error'] = str(
                    probe.get('error') or 'runtime cache probe failed'
                )
                self.completed.emit(context, result, None)
                return
            if probe.get('ok') and probe.get('epoch_stable') is not True:
                cache['error'] = 'inventory context changed during runtime cache probe'
                self.completed.emit(context, result, None)
                return
            item = probe.get('item') if isinstance(probe.get('item'), dict) else None
            handle = item.get('handle') if isinstance(item, dict) else None
            fingerprint = str(item.get('serial_sha256', '') or '') if isinstance(item, dict) else ''
            instance_id = item.get('instance_id') if isinstance(item, dict) else None
            probe_idx = item.get('idx') if isinstance(item, dict) else None
            current_serial = str(item.get('serial') or '') if isinstance(item, dict) else ''
            if (
                not isinstance(item, dict)
                or isinstance(handle, bool) or not isinstance(handle, int)
                or not fingerprint
                or isinstance(instance_id, bool) or not isinstance(instance_id, int)
                or isinstance(probe_idx, bool) or not isinstance(probe_idx, int)
                or probe_idx < 0
                or not current_serial.startswith('@U')
                or (applied_token_valid and (
                    handle != applied_handle or instance_id != applied_instance_id
                ))
            ):
                cache['error'] = 'fresh live item identity is unavailable or changed'
                self.completed.emit(context, result, None)
                return
            serial_gate_reported = (
                'serial_exact' in probe or 'serial_semantic' in probe
            )
            if (
                applied_token_valid
                and (
                    (serial_gate_reported and not (
                        probe.get('serial_exact') is True
                        or probe.get('serial_semantic') is True
                    ))
                    or (not serial_gate_reported and current_serial != str(context['serial']))
                )
            ):
                cache['error'] = 'the live backend cannot verify the canonicalized item serial'
                self.completed.emit(context, result, None)
                return
            context['applied_serial'] = current_serial
            if probe_idx != actual_idx:
                context['actual_idx'] = probe_idx
                context['relocated'] = True
                actual_idx = probe_idx
            unequipped = bool(
                probe.get('ok') and probe.get('epoch_stable') is True
                and probe.get('equipped') is False
            )
            if unequipped and not cache['publish_backpack_supported']:
                cache['supported'] = False
                cache['availability'] = (
                    'temporarily_unavailable' if publish_declared else 'unsupported'
                )
                if isinstance(capabilities, dict):
                    cache['capability_reason'] = str(
                        capabilities.get('publish_backpack_item_reason')
                        or cache.get('capability_reason') or ''
                    )
                self.completed.emit(context, result, None)
                return
            if (
                probe.get('ok') and probe.get('epoch_stable') is True
                and probe.get('container_actor_diverged') is False
                and not unequipped
            ):
                cache.update(ok=True, skipped='already_consistent')
                self.completed.emit(context, result, None)
                return
            if not unequipped and not cache['rebuild_supported']:
                cache['supported'] = False
                cache['availability'] = (
                    'temporarily_unavailable' if rebuild_declared else 'unsupported'
                )
                self.completed.emit(context, result, None)
                return

            resolved = {
                'ok': probe.get('ok'),
                'status': 'unique',
                'item': item,
            }
            cache['resolution'] = resolved
            cache['requested_serial_sha256'] = requested_fingerprint
            cache['current_serial_sha256'] = fingerprint

            snapshot = self._bridge.loadout_snapshot()
            cache['snapshot'] = snapshot
            matching_slots = [
                slot for slot in (snapshot.get('slots') or [])
                if isinstance(slot, dict)
                and slot.get('join_status') == 'unique'
                and slot.get('source_handle') == handle
                and str(slot.get('serial_sha256', '') or '').lower() == fingerprint.lower()
                and slot.get('instance_id') == instance_id
            ]
            if (
                not snapshot.get('ok')
                or not snapshot.get('epoch')
                or not snapshot.get('player_state')
            ):
                cache['error'] = 'fresh loadout snapshot identity is unavailable'
                self.completed.emit(context, result, None)
                return

            if unequipped:
                if matching_slots:
                    cache['error'] = 'item became equipped before backpack publication'
                    self.completed.emit(context, result, None)
                    return
                stage = 'publish'
                cache['attempted'] = True
                published = self._bridge.publish_backpack_item(
                    handle=handle,
                    serial_sha256=fingerprint,
                    instance_id=instance_id,
                    epoch=snapshot['epoch'],
                    player_state=snapshot['player_state'],
                )
                cache['result'] = published
                cache['mode'] = str(published.get('mode') or '')
                cache['uncertain'] = bool(
                    published.get('uncertain') or published.get('rollback_required')
                )
                if cache['uncertain']:
                    cache['recovery_pending'] = True
                cache['ok'] = bool(
                    published.get('ok')
                    and published.get('full_identity_committed')
                    and published.get('full_identity_verified')
                    and published.get('full_identity_dataref_verified')
                    and published.get('full_identity_parts_verified')
                )
                if not cache['ok']:
                    cache['error'] = str(
                        published.get('error') or published.get('warning')
                        or 'backpack full runtime identity publication was not verified'
                    )
                self.completed.emit(context, result, None)
                return

            if len(matching_slots) != 1:
                cache['error'] = 'item is not uniquely equipped in the fresh loadout snapshot'
                self.completed.emit(context, result, None)
                return

            stage = 'rebuild'
            cache['attempted'] = True
            rebuilt = self._bridge.rebuild_item_cache(
                handle=handle,
                serial_sha256=fingerprint,
                instance_id=instance_id,
                epoch=snapshot['epoch'],
                player_state=snapshot['player_state'],
                active_weapon_slot=snapshot.get('active_weapon_slot'),
            )
            cache['result'] = rebuilt
            cache['uncertain'] = bool(
                rebuilt.get('uncertain') or rebuilt.get('rollback_required')
            )
            if cache['uncertain']:
                cache['recovery_pending'] = True
            cache['ok'] = bool(
                rebuilt.get('ok')
                and rebuilt.get('restored')
                and rebuilt.get('rebuild_verified')
                and rebuilt.get('actor_cache_verified')
                and rebuilt.get('full_identity_committed')
                and rebuilt.get('full_identity_dataref_verified')
                and rebuilt.get('full_identity_parts_verified')
            )
            if not cache['ok']:
                cache['error'] = str(
                    rebuilt.get('error') or rebuilt.get('warning')
                    or 'full runtime identity and actor cache rebuild was not verified'
                )
            self.completed.emit(context, result, None)
        except Exception as exc:
            cache = result['cache_rebuild']
            cache['uncertain'] = stage in {'publish', 'rebuild'}
            if cache['uncertain']:
                cache['recovery_pending'] = True
            cache['error'] = f"{type(exc).__name__}: {exc}"
            result['failed_stage'] = stage
            self.completed.emit(context, result, cache['error'])


class _LiveLoadoutWorker(QThread):
    """Capture or apply one loadout without blocking the Qt event loop."""

    completed = pyqtSignal(str, int, object, object, object)

    def __init__(self, bridge, operation, slot, context=None, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._operation = str(operation or '')
        self._slot = int(slot)
        self._context = dict(context or {})
        self.mutation_preflight = None

    def run(self):
        try:
            if self._operation == 'save':
                result = self._bridge.loadout_snapshot()
            elif self._operation == 'apply':
                self.mutation_preflight = _live_inventory_mutation_preflight(self._bridge)
                if self.mutation_preflight['blocked']:
                    result = {
                        'ok': False,
                        'action': 'apply_loadout',
                        'error': self.mutation_preflight['reason'],
                        'recovery_pending': True,
                        'capabilities': self.mutation_preflight.get('capabilities'),
                    }
                    self.completed.emit(
                        self._operation, self._slot, self._context, result, None,
                    )
                    return
                snapshot = self._bridge.loadout_snapshot()
                if not snapshot.get('ok'):
                    result = snapshot
                elif not snapshot.get('epoch') or not snapshot.get('snapshot_hash'):
                    result = {
                        'ok': False,
                        'action': 'apply_loadout',
                        'error': 'fresh loadout snapshot is missing epoch or snapshot_hash',
                    }
                else:
                    result = self._bridge.apply_loadout(
                        epoch=snapshot['epoch'],
                        snapshot_hash=snapshot['snapshot_hash'],
                        entries=list(self._context.get('entries') or []),
                    )
            elif self._operation == 'recovery':
                result = self._bridge.loadout_recovery()
            elif self._operation == 'clear_recovery':
                snapshot = self._bridge.loadout_snapshot()
                if not snapshot.get('ok'):
                    result = snapshot
                elif not snapshot.get('epoch') or not snapshot.get('snapshot_hash'):
                    result = {
                        'ok': False,
                        'action': 'clear_loadout_recovery',
                        'error': 'fresh loadout snapshot is missing epoch or snapshot_hash',
                    }
                else:
                    result = self._bridge.clear_loadout_recovery(
                        epoch=snapshot['epoch'],
                        snapshot_hash=snapshot['snapshot_hash'],
                    )
            else:
                raise ValueError(f'unsupported live loadout operation: {self._operation}')
            err = None
        except Exception as exc:
            result = None
            err = f"{type(exc).__name__}: {exc}"
        self.completed.emit(
            self._operation, self._slot, self._context, result, err,
        )


class _LiveBatchSpawnWorker(QThread):
    """Materialize rolled items in compact native batches without blocking Qt."""

    progress = pyqtSignal(int, int, int, int)
    batch_finished = pyqtSignal(int, int)

    def __init__(self, bridge, lines, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._lines = list(lines)
        self.spawned_records = []
        self.incremental_safe = True
        self.mutation_preflight = None
        self.mutation_results = []
        self.blocked_reason = ''

    def run(self):
        success = 0
        fail = 0
        total = len(self._lines)
        self.mutation_preflight = _live_inventory_mutation_preflight(self._bridge)
        if self.mutation_preflight['blocked']:
            self.blocked_reason = self.mutation_preflight['reason']
            self.incremental_safe = False
            self.progress.emit(total, total, 0, total)
            self.batch_finished.emit(0, total)
            return
        serials = []
        for line in self._lines:
            try:
                if line.strip().startswith('@U'):
                    serial = line.strip()
                else:
                    serial, err = b_encoder.encode_to_base85(line)
                    if err:
                        raise ValueError(err)
                serials.append(serial)
            except Exception:
                fail += 1
        completed = fail
        self.progress.emit(completed, total, success, fail)

        # Keep one game transaction modest: large reward payloads cause more UI
        # churn and are harder to verify atomically. This is independent of any
        # third-party mod's batching implementation.
        chunks = []
        current = []
        current_chars = 0
        for serial in serials:
            size = len(serial)
            if current and (len(current) >= 20 or current_chars + size > 18000):
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(serial)
            current_chars += size
        if current:
            chunks.append(current)

        for chunk_index, chunk in enumerate(chunks):
            result = None
            try:
                result = self._bridge.spawn_many(chunk, "BackpackItems")
                self.mutation_results.append(result)
                if _spawn_delivered(result, len(chunk)):
                    success += len(chunk)
                    records = result.get("items")
                    if isinstance(records, list) and len(records) == len(chunk):
                        for record in records:
                            normalized = dict(record)
                            normalized["container"] = "BackpackItems"
                            normalized["idx"] = normalized.get("index")
                            self.spawned_records.append(normalized)
                    else:
                        self.incremental_safe = False
                else:
                    fail += len(chunk)
                    self.incremental_safe = False
            except Exception:
                fail += len(chunk)
                self.incremental_safe = False
            completed += len(chunk)
            pending, reason = _live_inventory_recovery_state(result)
            if pending is True:
                self.blocked_reason = reason or 'unresolved loadout recovery requires review'
                self.incremental_safe = False
                remaining = sum(len(item) for item in chunks[chunk_index + 1:])
                fail += remaining
                completed += remaining
                self.progress.emit(completed, total, success, fail)
                break
            self.progress.emit(completed, total, success, fail)
        self.batch_finished.emit(success, fail)
