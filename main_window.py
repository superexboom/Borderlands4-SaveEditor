
import sys
import time
import itertools
import os
import hashlib
from importlib import import_module
from pathlib import Path

# Force UTF-8 stdio so the app's bilingual (Chinese) log prints don't crash a
# frozen Windows build, whose default cp1252 codepage can't encode them. In a
# windowed exe stdout/stderr may be None, so route those to the null device.
# 强制 UTF-8 标准输出，使应用的双语（中文）日志打印不会导致冻结的 Windows
# 版本崩溃（其默认 cp1252 代码页无法编码中文）。在窗口化 exe 中 stdout/stderr
# 可能为 None，故将其重定向到空设备。
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is None:
        setattr(sys, _stream_name, open(os.devnull, "w", encoding="utf-8"))
    else:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

VERSION = "4.1.1"
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QMessageBox, QFileDialog,
    QStackedWidget, QButtonGroup, QInputDialog,
    QMenu, QGraphicsBlurEffect, QStackedLayout, QSizePolicy, QCheckBox, QLayout,
    QScrollArea
)
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter
from PyQt6.QtCore import pyqtSlot, Qt, QTimer, QObject, QThread, pyqtSignal, QEvent, QRect

from core import b_encoder
from core import resource_loader
from core import bl4_functions as bl4f
from core import SaveGameController, SaveSelectorWidget, ThemeManager, infer_user_id_from_save_path

class BackgroundWidget(QLabel):
    """Widget that displays a blurred background image for frosted glass effect."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("backgroundLayer")
        self._original_pixmap = None
        self._corner_radius = 20  # Match the window corner radius
        # Prevent the background from affecting window size
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        from PyQt6.QtCore import QSettings
        self.settings = QSettings('SuperExboom', 'BL4SaveEditor')
        self.setStyleSheet("background-color: #1a1a20;")
        # Let the first frame paint before decoding a multi-megabyte custom/background image.
        QTimer.singleShot(100, self._load_background_image)
        
    def _load_background_image(self):
        """Load and apply the background image with blur effect."""
        custom_bg = self.settings.value('custom_background', None)
        if custom_bg and Path(custom_bg).exists():
            bg_path = Path(custom_bg)
        else:
            bg_path = resource_loader.get_resource_path("assets/bg.jpg")
            
        if bg_path and bg_path.exists():
            self._original_pixmap = QPixmap(str(bg_path))
            self._apply_blur()
            self._update_scaled_pixmap()
        else:
            # Fallback: solid dark background
            self.setStyleSheet("background-color: #1a1a20;")

    def set_custom_image(self, bg_path):
        if bg_path and Path(bg_path).exists():
            self.settings.setValue('custom_background', str(bg_path))
        else:
            self.settings.remove('custom_background')
            
        self._load_background_image()
    
    def _apply_blur(self):
        """Apply blur effect to the background."""
        if self._original_pixmap:
            blur = QGraphicsBlurEffect(self)
            blur.setBlurRadius(15)
            blur.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
            self.setGraphicsEffect(blur)
            # Don't set pixmap directly here, let resizeEvent handle scaling
            self.setScaledContents(True)
    
    def resizeEvent(self, event):
        """Handle resize to scale background - maintains aspect ratio, crops to fill."""
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self):
        """Scale the loaded image immediately, including after deferred loading."""
        if self._original_pixmap:
            # Use KeepAspectRatioByExpanding to maintain aspect ratio and crop excess
            scaled_pixmap = self._original_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # Crop to center if larger than widget size
            if scaled_pixmap.size() != self.size():
                x = (scaled_pixmap.width() - self.width()) // 2
                y = (scaled_pixmap.height() - self.height()) // 2
                scaled_pixmap = scaled_pixmap.copy(x, y, self.width(), self.height())
            self.setPixmap(scaled_pixmap)
        # Note: Mask is applied at the central widget level in MainWindow.resizeEvent


class IteratorWorker(QObject):
    status_update = pyqtSignal(str)
    finished_generation = pyqtSignal(str)
    finished_add_to_backpack = pyqtSignal(int, int)

    def __init__(self, controller, params, loc_data):
        super().__init__()
        self.controller = controller
        self.params = params
        self.loc = loc_data

    def run(self):
        try:
            is_add_to_backpack = self.params.get('add_to_backpack', False)
            
            deserialized_strings = self._generate_deserialized_list()
            if not deserialized_strings:
                self.status_update.emit(self.loc['no_data'])
                if is_add_to_backpack:
                    self.finished_add_to_backpack.emit(0, 0)
                else:
                    self.finished_generation.emit("")
                return

            if is_add_to_backpack:
                self._add_items_to_backpack(deserialized_strings)
            else:
                self._generate_output_text(deserialized_strings)

        except ValueError as e:
            self.status_update.emit(f"{self.loc['error_prefix']}{e}")
            if self.params.get('add_to_backpack'): self.finished_add_to_backpack.emit(0, 0)
            else: self.finished_generation.emit("")
        except Exception as e:
            self.status_update.emit(f"{self.loc['error_prefix']}{e}")
            if self.params.get('add_to_backpack'): self.finished_add_to_backpack.emit(0, 0)
            else: self.finished_generation.emit("")

    def _generate_deserialized_list(self):
        self.status_update.emit(self.loc['generating'])
        base_data = self.params['base_data'].strip()
        if not base_data: raise ValueError(self.loc['base_empty'])
        
        strings = []
        if self.params['is_combo']:
            start, end, size = int(self.params['combo_start']), int(self.params['combo_end']), int(self.params['combo_size'])
            if start > end: raise ValueError(self.loc['combo_error_range'])
            source_set = list(range(start, end + 1))
            if len(source_set) < size: raise ValueError(self.loc['combo_error_size'])
            combos = list(itertools.combinations(source_set, size))
            for combo in combos:
                strings.append(f"{base_data} {' '.join(f'{{{c}}}' for c in combo)}|")
        else:
            start, end = int(self.params['start']), int(self.params['end'])
            if start > end: raise ValueError(self.loc['iter_error_range'])
            if self.params['is_skin']:
                for i in range(start, end + 1):
                    strings.append(f'{base_data} | "c", {i}|')
            else:
                special_base = self.params['special_base']
                is_special_combo = self.params.get('is_special_combo', False)
                combo_text = self.params.get('special_combo_text', "").strip()

                if (self.params['is_special'] or is_special_combo) and not special_base:
                    raise ValueError(self.loc['special_base_needed'])
                
                for i in range(start, end + 1):
                    if is_special_combo:
                        # Format: {AAA:[98 99 B]}
                        part = f"{{{special_base}:[{combo_text} {i}]}}"
                    elif self.params['is_special']:
                        part = f"{{{special_base}:{i}}}"
                    else:
                        part = f"{{{i}}}"
                    strings.append(f"{base_data}{part}|")
        return strings

    def _add_items_to_backpack(self, strings):
        self.status_update.emit(self.loc['generated_writing'].format(count=len(strings)))
        success, fail = 0, 0
        total = len(strings)
        flag = self.params['yaml_flag']

        for i, line in enumerate(strings):
            self.status_update.emit(self.loc['writing_progress'].format(current=i + 1, total=total))
            try:
                serial, err = b_encoder.encode_to_base85(line)
                if err:
                    fail += 1
                    continue
                if self.controller.add_item_to_backpack(serial, flag):
                    success += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
            time.sleep(0.01)
        self.finished_add_to_backpack.emit(success, fail)

    def _generate_output_text(self, strings):
        self.status_update.emit(self.loc['generated_encoding'].format(count=len(strings)))
        final_output = []
        total = len(strings)
        is_yaml = self.params['is_yaml']
        yaml_flag = self.params['yaml_flag']

        for i, line in enumerate(strings):
            if (i+1) % 20 == 0:
                self.status_update.emit(self.loc['encoding_progress'].format(current=i + 1, total=total))

            result, error = b_encoder.encode_to_base85(line)
            if error:
                output_line = f"{self.loc['error_prefix']}{error}"
            elif is_yaml:
                output_line = f"        - serial: '{result}'\n          state_flags: {yaml_flag}"
            else:
                output_line = f"{line}  -->  {result}"
            final_output.append(output_line)
            time.sleep(0.005)
        self.finished_generation.emit('\n'.join(final_output))

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
                if result.get("ok"):
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


class BatchAddWorker(QObject):
    progress = pyqtSignal(int, int, int, int) # current, total, success, fail
    finished = pyqtSignal(int, int) # success, fail

    def __init__(self, controller, lines, flag):
        super().__init__()
        self.controller = controller
        self.lines = lines
        self.flag = flag

    def run(self):
        success_count = 0
        fail_count = 0
        total = len(self.lines)
        for i, line in enumerate(self.lines):
            try:
                if line.strip().startswith('@U'):
                    serial = line
                else:
                    serial, err = b_encoder.encode_to_base85(line)
                    if err:
                        fail_count += 1
                        continue
                
                if self.controller.add_item_to_backpack(serial, self.flag):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception:
                fail_count += 1
            finally:
                self.progress.emit(i + 1, total, success_count, fail_count)
        
        self.finished.emit(success_count, fail_count)


class MainWindow(QMainWindow):
    _NAV_STATE_KEY = 'nav_bar_expanded'
    _NAV_SMALL_SCREEN_WIDTH = 1050
    _NAV_COLLAPSED_WIDTH = 56
    _NAV_EXPANDED_MIN_WIDTH = 196
    _NAV_EXPANDED_MAX_WIDTH = 240
    _NAV_HORIZONTAL_CHROME = 46
    _RESIZE_MARGIN = 8

    def __getattr__(self, name):
        """Keep the historical ``window.foo_tab`` API while tabs are lazy."""
        lazy_attrs = self.__dict__.get("_lazy_tab_attrs", {})
        if name in lazy_attrs:
            return self._ensure_tab(lazy_attrs[name])
        raise AttributeError(name)

    def __init__(self):
        super().__init__()
        from PyQt6.QtCore import QSettings
        self._settings = QSettings('SuperExboom', 'BL4SaveEditor')
        self.current_language = self._settings.value('language', 'zh-CN')
        self._load_localization()
        
        # Initialize theme manager
        self.theme_manager = ThemeManager()
        
        self.setWindowTitle(f"{self.loc['window_title']} V{VERSION}")
        icon_path = resource_loader.get_resource_path("assets/BL4.ico")
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.controller = SaveGameController()
        self._items_snapshot = None
        self._dirty_item_views = {"items", "weapon", "yaml"}
        self._lazy_tab_specs = {}
        self._lazy_tab_attrs = {}
        self._lazy_tab_indexes = {}
        self._loaded_tabs = {}
        self._character_data = None
        self._character_level = ""
        # --- live (online) mode state ---
        self._live_active = False
        self._live_connecting = False
        self._live_bridge = None
        self._live_thread = None
        self._live_runtime_worker = None
        self._live_workers = set()
        self._live_batch_spawn_worker = None
        self._god_roll_worker = None
        self._live_recovery_pending = None
        self._live_recovery_reason = ''
        self._batch_add_active = False
        self._close_when_live_idle = False
        screen = QApplication.primaryScreen()
        screen_width = screen.availableGeometry().width() if screen else 1600
        if self._settings.contains(self._NAV_STATE_KEY):
            self.is_nav_bar_expanded = self._settings.value(
                self._NAV_STATE_KEY, True, type=bool
            )
        else:
            self.is_nav_bar_expanded = screen_width >= self._NAV_SMALL_SCREEN_WIDTH
        self.nav_bar_width_expanded = self._NAV_EXPANDED_MIN_WIDTH
        self.nav_bar_width_collapsed = self._NAV_COLLAPSED_WIDTH

        # Apply themed stylesheet
        self._apply_themed_stylesheet()

        self._create_actions()

        # Create central widget with background support
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setObjectName("centralWidget")
        
        # Use stacked layout for background + content overlay
        stacked_layout = QStackedLayout(central_widget)
        stacked_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stacked_layout.setContentsMargins(0, 0, 0, 0)
        
        # Background layer (blurred image)
        self.background_widget = BackgroundWidget()
        stacked_layout.addWidget(self.background_widget)
        
        # Content layer (on top of background)
        content_container = QWidget()
        content_container.setObjectName("contentWrapper")
        content_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        root_layout = QVBoxLayout(content_container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        stacked_layout.addWidget(content_container)
        
        # Ensure content is on top
        stacked_layout.setCurrentWidget(content_container)

        self._create_header_bar()
        root_layout.addWidget(self.header_bar)

        main_content_layout = QHBoxLayout()
        main_content_layout.setSpacing(0)
        
        self.content_stack = QStackedWidget()
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._create_nav_bar()

        main_content_layout.addWidget(self.nav_bar)
        main_content_layout.addWidget(self.content_stack)
        
        root_layout.addLayout(main_content_layout)

        # Custom footer
        self.footer = QWidget()
        self.footer.setObjectName("footer")
        self.footer.setFixedHeight(25)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(15, 0, 15, 0)
        footer_layout.addStretch()
        root_layout.addWidget(self.footer)

        self._init_autosave(footer_layout)
        self._create_resize_handles()
        
        self._add_tabs()
        self.content_stack.currentChanged.connect(self._refresh_inventory_view)

        available = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        width = min(1600, max(1, available.width() - 40))
        height = min(900, max(1, available.height() - 40))
        self.resize(width, height)
        self.move(available.center() - self.rect().center())

        # If saved language differs from default (zh-CN), sync backend + all tabs
        if self.current_language != 'zh-CN':
            bl4f.set_language(self.current_language)
            for tab in self._all_content_tabs():
                if hasattr(tab, 'update_language'):
                    tab.update_language(self.current_language)
            self.update_ui_text()

        self.scan_for_saves()
        self.update_action_states()
    
    def _load_localization(self):
        lang_map = {
            'zh-CN': "i18n/ui_localization.json",
            'en-US': "i18n/ui_localization_EN.json",
            'ru': "i18n/ui_localization_RU.json",
            'ua': "i18n/ui_localization_UA.json"
        }
        filename = lang_map.get(self.current_language, "i18n/ui_localization_EN.json")
        data = resource_loader.load_json_resource(filename)
        if data and "main_window" in data:
            self.loc = data["main_window"]
        else:
            # Fallback if file missing (or partial)
            self.loc = {
                "window_title": "Borderlands 4 Save Editor",
                "subtitle": "By SuperExboom",
                "header": {"title": "BL4 Save Editor", "open": "Open", "save": "Save", "save_as": "Save As..."},
                "menu": {"open_selector": "Open Selector", "save": "Save", "save_as": "Save As..."},
                "status": {"welcome": "Welcome"},
                "tabs": {
                    "select_save": "Select Save", "character": "Character", "items": "Items", 
                    "converter": "Converter", "yaml_editor": "YAML", "class_mod": "Class Mod", 
                    "enhancement": "Enhancement", "weapon_editor": "Weapon Edit", 
                    "weapon_generator": "Weapon Gen", "god_roll": "God Roll", "grenade": "Grenade", "shield": "Shield",
                    "repkit": "RepKit", "heavy_weapon": "Heavy", "loadout_manager": "Loadout"
                },
                "dialogs": {
                    "success": "Success", "error": "Error", "critical": "Critical", "warning": "Warning", "cancel": "Cancel",
                    "change_bg_title": "Select Background Image",
                    "image_files": "Image Files",
                    "clear_bg_prompt": "Do you want to clear the custom background or select a new one?\nYes: Clear\nNo: Select New\nCancel: Do Nothing",
                    "clear_bg_title": "Clear Background"
                },
                "worker": {
                    "no_data": "No data.", "error_prefix": "Error: "
                }
            }

    def mousePressEvent(self, event):
        """Let Windows move the frameless window through its native drag path."""
        if event.button() == Qt.MouseButton.LeftButton and self.header_bar.underMouse():
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def _create_resize_handles(self):
        specs = (
            (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.BottomEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
        )
        self._resize_handles = {}
        for edges, cursor in specs:
            zone = QWidget(self)
            zone.setCursor(cursor)
            zone.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            zone.installEventFilter(self)
            zone.raise_()
            self._resize_handles[zone] = edges

    def eventFilter(self, watched, event):
        edges = getattr(self, '_resize_handles', {}).get(watched)
        if watched is getattr(self, '_manual_resize_widget', None):
            if (
                event.type() == QEvent.Type.MouseMove
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self._manual_resize_to(event.globalPosition().toPoint())
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._manual_resize_to(event.globalPosition().toPoint())
                self._manual_resize_widget = None
                return True

        if (
            edges is not None
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and not (self.isMaximized() or self.isFullScreen())
        ):
            # Qt's own QSizeGrip deliberately avoids startSystemResize() on
            # translucent Windows windows (QTBUG-90628: resize flicker).
            if (
                sys.platform == 'win32'
                and self.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            ):
                self._manual_resize_widget = watched
                self._manual_resize_edges = edges
                self._manual_resize_origin = event.globalPosition().toPoint()
                self._manual_resize_geometry = self.geometry()
                return True

            handle = self.windowHandle()
            if handle is not None and handle.startSystemResize(edges):
                return True
        return super().eventFilter(watched, event)

    def _manual_resize_to(self, global_position):
        initial = self._manual_resize_geometry
        delta = global_position - self._manual_resize_origin
        edges = self._manual_resize_edges
        requested = initial.size()
        if edges & Qt.Edge.LeftEdge:
            requested.setWidth(initial.width() - delta.x())
        elif edges & Qt.Edge.RightEdge:
            requested.setWidth(initial.width() + delta.x())
        if edges & Qt.Edge.TopEdge:
            requested.setHeight(initial.height() - delta.y())
        elif edges & Qt.Edge.BottomEdge:
            requested.setHeight(initial.height() + delta.y())

        geometry = QRect(initial.topLeft(), QLayout.closestAcceptableSize(self, requested))
        if edges & Qt.Edge.LeftEdge:
            geometry.moveRight(initial.right())
        if edges & Qt.Edge.TopEdge:
            geometry.moveBottom(initial.bottom())
        self.setGeometry(geometry)

    def _layout_resize_handles(self):
        handles = list(getattr(self, '_resize_handles', {}))
        if not handles:
            return
        active = not (self.isMaximized() or self.isFullScreen())
        for zone in handles:
            zone.setVisible(active)
        if not active:
            return

        width, height, margin = self.width(), self.height(), self._RESIZE_MARGIN
        inner_width = max(0, width - margin * 2)
        inner_height = max(0, height - margin * 2)
        geometries = (
            QRect(0, 0, margin, margin),
            QRect(margin, 0, inner_width, margin),
            QRect(width - margin, 0, margin, margin),
            QRect(width - margin, margin, margin, inner_height),
            QRect(width - margin, height - margin, margin, margin),
            QRect(margin, height - margin, inner_width, margin),
            QRect(0, height - margin, margin, margin),
            QRect(0, margin, margin, inner_height),
        )
        for zone, geometry in zip(handles, geometries):
            if zone.geometry() != geometry:
                zone.setGeometry(geometry)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_resize_handles()
        self._apply_window_mask()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._sync_window_frame)

    def _sync_window_frame(self):
        self._apply_window_mask()
        self._layout_resize_handles()

    def _apply_window_mask(self):
        # Apply rounded corner mask to central widget to clip all child widgets including blur effect
        central = self.centralWidget()
        if central:
            if self.isMaximized() or self.isFullScreen():
                if not central.mask().isEmpty():
                    central.clearMask()
            else:
                from PyQt6.QtGui import QBitmap
                corner_radius = 20
                bitmap = QBitmap(central.width(), central.height())
                bitmap.fill(Qt.GlobalColor.white)
                painter = QPainter(bitmap)
                painter.setBrush(Qt.GlobalColor.black)
                painter.setPen(Qt.GlobalColor.black)
                painter.drawRoundedRect(
                    0, 0, central.width(), central.height(), corner_radius, corner_radius
                )
                painter.end()
                central.setMask(bitmap)

    def _create_actions(self):
        self.open_action = QAction(self.loc['menu']['open_selector'], self)
        self.open_action.triggered.connect(self.browse_and_open_save)
        
        self.save_action = QAction(self.loc['menu']['save'], self)
        self.save_action.triggered.connect(self.encrypt_and_save)

        self.save_as_action = QAction(self.loc['menu']['save_as'], self)
        self.save_as_action.triggered.connect(lambda: self.encrypt_and_save(save_as=True))

    def change_background(self):
        """Open file dialog to select a new background image or clear existing one."""
        has_custom = self.background_widget.settings.value('custom_background', None) is not None
        
        if has_custom:
            reply = QMessageBox.question(
                self, 
                self.loc.get('dialogs', {}).get('clear_bg_title', 'Clear Background'),
                self.loc.get('dialogs', {}).get('clear_bg_prompt', 'Do you want to clear the custom background or select a new one?\nYes: Clear\nNo: Select New\nCancel: Do Nothing'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.background_widget.set_custom_image(None)
                return
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.loc.get('dialogs', {}).get('change_bg_title', 'Select Background Image'),
            "",
            f"{self.loc.get('dialogs', {}).get('image_files', 'Image Files')} (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_path:
            self.background_widget.set_custom_image(file_path)

    def _create_header_bar(self):
        self.header_bar = QWidget()
        self.header_bar.setObjectName("headerBar")
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(15, 5, 10, 5)
        header_layout.setSpacing(8)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(0) 
        
        title_label = QLabel(self.loc['header']['title'])
        title_label.setObjectName("titleLabel")
        title_label.setWordWrap(True)
        title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        
        subtitle_label = QLabel(self.loc['subtitle'])
        subtitle_label.setObjectName("subtitleLabel")
        subtitle_label.setWordWrap(True)
        subtitle_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        
        title_vbox.addWidget(title_label)
        title_vbox.addWidget(subtitle_label)

        header_layout.addLayout(title_vbox, 1)

        self.open_button = QPushButton(self.loc['header']['open'])
        self.open_button.setObjectName("headerActionButton")
        self.open_button.clicked.connect(self.open_action.trigger)
        self.save_button = QPushButton(self.loc['header']['save'])
        self.save_button.setObjectName("headerActionButton")
        self.save_button.clicked.connect(self.save_action.trigger)
        self.save_as_button = QPushButton(self.loc['header']['save_as'])
        self.save_as_button.setObjectName("headerActionButton")
        self.save_as_button.clicked.connect(self.save_as_action.trigger)

        self.lang_button = QPushButton(self._get_lang_button_text())
        
        self.lang_menu = QMenu(self)
        
        # Define languages
        languages = [
            ("简体中文", "zh-CN"),
            ("English", "en-US"),
            ("Русский", "ru"),
            ("Українська", "ua")
        ]
        
        for label, code in languages:
            action = QAction(label, self)
            # Use default parameter to capture 'code' value in lambda closure
            action.triggered.connect(lambda checked, c=code: self.change_language(c))
            self.lang_menu.addAction(action)

        self.lang_button.setMenu(self.lang_menu)

        # Theme toggle button (next to language button)
        self.theme_button = QPushButton(self.theme_manager.get_theme_icon())
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setToolTip(self._get_theme_tooltip())
        self.theme_button.clicked.connect(self.toggle_theme)

        # Background toggle button (next to theme button)
        self.bg_button = QPushButton("🖼️")
        self.bg_button.setObjectName("bgButton")
        # We need a fallback tooltip text if not in dict
        self.bg_button.setToolTip(self.loc.get('header', {}).get('change_bg', 'Change Background'))
        self.bg_button.clicked.connect(self.change_background)

        for button in (
            self.open_button, self.save_button, self.save_as_button,
            self.lang_button, self.theme_button, self.bg_button,
        ):
            button.setProperty("headerControl", True)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            header_layout.addWidget(button)

        self.live_toggle_button = QPushButton()
        self.live_toggle_button.setObjectName("headerActionButton")
        self.live_toggle_button.setProperty("headerControl", True)
        self.live_toggle_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.live_toggle_button.clicked.connect(self._toggle_live_mode)
        header_layout.addWidget(self.live_toggle_button)

        self.live_refresh_button = QPushButton()
        self.live_refresh_button.setObjectName("headerActionButton")
        self.live_refresh_button.setProperty("headerControl", True)
        self.live_refresh_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.live_refresh_button.setEnabled(False)
        self.live_refresh_button.clicked.connect(self._live_refresh)
        header_layout.addWidget(self.live_refresh_button)
        self._update_live_header_text()

        header_layout.addStretch()

        self.minimize_button = QPushButton("—")
        self.minimize_button.setObjectName("minimizeButton")
        self.minimize_button.clicked.connect(self.showMinimized)

        self.maximize_button = QPushButton("⬜")
        self.maximize_button.setObjectName("maximizeButton")
        self.maximize_button.clicked.connect(self.toggle_maximize_restore)

        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("closeButton")
        self.close_button.clicked.connect(self.close)

        header_layout.addWidget(self.minimize_button)
        header_layout.addWidget(self.maximize_button)
        header_layout.addWidget(self.close_button)

    def toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("⬜")
        else:
            self.showMaximized()
            self.maximize_button.setText("❐")

    def _create_nav_bar(self):
        self.nav_bar = QWidget()
        self.nav_bar.setObjectName("nav_bar")
        self.nav_bar.setProperty("navCollapsed", not self.is_nav_bar_expanded)
        self.nav_bar.setFixedWidth(
            self.nav_bar_width_expanded
            if self.is_nav_bar_expanded else self.nav_bar_width_collapsed
        )
        self.nav_bar_layout = QVBoxLayout(self.nav_bar)
        self.nav_bar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.nav_bar_layout.setContentsMargins(4, 8, 4, 8)
        self.nav_bar_layout.setSpacing(4)

        self.toggle_button = QPushButton("‹" if self.is_nav_bar_expanded else "›")
        self.toggle_button.setObjectName("toggleButton")
        self.toggle_button.setFixedHeight(36)
        self.toggle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_button.clicked.connect(self.toggle_nav_bar)
        self.nav_bar_layout.addWidget(self.toggle_button)

        self.nav_scroll_area = QScrollArea(self.nav_bar)
        self.nav_scroll_area.setObjectName("navScrollArea")
        self.nav_scroll_area.setWidgetResizable(True)
        self.nav_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.nav_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_buttons_widget = QWidget()
        self.nav_buttons_widget.setObjectName("navButtonsWidget")
        self.nav_buttons_widget.setMinimumWidth(0)
        self.nav_buttons_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.nav_buttons_layout = QVBoxLayout(self.nav_buttons_widget)
        self.nav_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.nav_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_buttons_layout.setSpacing(4)
        self.nav_scroll_area.setWidget(self.nav_buttons_widget)
        self.nav_bar_layout.addWidget(self.nav_scroll_area)

        self.nav_button_group = QButtonGroup(self)
        self.nav_button_group.setExclusive(True)
        self.nav_button_group.idClicked.connect(self.handle_nav_click)
    
    def _add_tabs(self):
        self.selector_page = SaveSelectorWidget()
        self.selector_page.open_save_requested.connect(self.open_save_from_selector)
        self.selector_page.refresh_button.clicked.connect(self.scan_for_saves)
        self.add_tab(self.selector_page, self.loc['tabs']['select_save'], "📁")

        self._add_lazy_tab('character', 'character_tab', 'qt_character_tab', 'QtCharacterTab', "👤")
        self._add_lazy_tab('items', 'items_tab', 'qt_items_tab', 'QtItemsTab', "🎒")
        self._add_lazy_tab('serial_inspector', 'serial_inspector_tab', 'qt_serial_inspector_tab', 'QtSerialInspectorTab', "🔍")
        self._add_lazy_tab('yaml_editor', 'yaml_editor_tab', 'qt_yaml_editor_tab', 'QtYamlEditorTab', "📄", pass_main=True)
        self._add_nav_separator()

        self._add_lazy_tab('class_mod', 'class_mod_tab', 'qt_class_mod_editor_tab', 'QtClassModEditorTab', "🌟", main_app=True)
        self._add_lazy_tab('enhancement', 'enhancement_tab', 'qt_enhancement_editor_tab', 'QtEnhancementEditorTab', "✨", main_app=True)
        self._add_lazy_tab('weapon_editor', 'weapon_editor_tab', 'qt_weapon_editor_tab', 'WeaponEditorTab', "🔧", pass_main=True)
        self._add_lazy_tab('weapon_generator', 'weapon_generator_tab', 'qt_weapon_generator_tab', 'QtWeaponGeneratorTab', "🔫")
        self._add_lazy_tab('god_roll', 'god_roll_tab', 'qt_god_roll_tab', 'QtGodRollTab', "🏆")
        self._add_lazy_tab('grenade', 'grenade_tab', 'qt_grenade_editor_tab', 'QtGrenadeEditorTab', "💣", main_app=True)
        self._add_lazy_tab('shield', 'shield_tab', 'qt_shield_editor_tab', 'QtShieldEditorTab', "🛡️", main_app=True)
        self._add_lazy_tab('repkit', 'repkit_tab', 'qt_repkit_editor_tab', 'QtRepkitEditorTab', "🛠️", main_app=True)
        self._add_lazy_tab('heavy_weapon', 'heavy_weapon_tab', 'qt_heavy_weapon_editor_tab', 'QtHeavyWeaponEditorTab', "🚀", main_app=True)

        self._add_nav_separator()
        self._add_lazy_tab('loadout_manager', 'loadout_manager_tab', 'qt_loadout_manager_tab', 'QtLoadoutManagerTab', "📋")
        self._add_lazy_tab('converter', 'converter_tab', 'qt_converter_tab', 'QtConverterTab', "🔧")

        self._refresh_nav_bar()
        if self.nav_button_group.buttons():
            self.nav_button_group.buttons()[0].click()

    def _add_lazy_tab(self, key, attr, module, class_name, icon, *, pass_main=False, main_app=False):
        placeholder = QWidget()
        index = self.add_tab(placeholder, self.loc['tabs'][key], icon)
        self._lazy_tab_specs[key] = (attr, module, class_name, pass_main, main_app)
        self._lazy_tab_attrs[attr] = key
        self._lazy_tab_indexes[key] = index

    def _loaded_tab(self, key):
        return self._loaded_tabs.get(key)

    def _ensure_tab(self, key):
        loaded = self._loaded_tab(key)
        if loaded is not None:
            return loaded
        attr, module_name, class_name, pass_main, main_app = self._lazy_tab_specs[key]
        tab_class = getattr(import_module(f"tabs.{module_name}"), class_name)
        if main_app:
            tab = tab_class(main_app=self)
        elif pass_main:
            tab = tab_class(self)
        else:
            tab = tab_class()
        self._connect_tab(key, tab)
        if self.current_language != 'zh-CN' and hasattr(tab, 'update_language'):
            tab.update_language(self.current_language)
        if key == 'yaml_editor':
            tab.apply_theme(self.theme_manager.is_dark())

        index = self._lazy_tab_indexes[key]
        placeholder = self.content_stack.widget(index)
        self.content_stack.removeWidget(placeholder)
        self.content_stack.insertWidget(index, tab)
        placeholder.deleteLater()
        self._loaded_tabs[key] = tab
        self.__dict__[attr] = tab
        self._hydrate_tab(key, tab)
        self._apply_live_ui_state(tab_only=(key, tab))
        return tab

    def _connect_tab(self, key, tab):
        if key == 'character':
            tab.character_data_changed.connect(self.handle_character_update)
            tab.sync_levels_requested.connect(self.handle_sync_levels)
            tab.unlock_requested.connect(self.handle_unlock_request)
            tab.runtime_action_requested.connect(self.handle_live_runtime_action)
        elif key == 'items':
            tab.add_item_requested.connect(self.handle_add_to_backpack)
        elif key in {'serial_inspector', 'class_mod', 'enhancement', 'weapon_editor', 'weapon_generator', 'god_roll', 'grenade', 'shield', 'repkit', 'heavy_weapon'}:
            tab.add_to_backpack_requested.connect(self.handle_add_to_backpack)
        if key == 'yaml_editor':
            tab.yaml_text_changed.connect(self.handle_yaml_update)
            tab.structure_changed.connect(self.handle_yaml_structure_changed)
            tab.open_item_requested.connect(self.handle_open_item_from_yaml)
        elif key == 'weapon_editor':
            tab.update_item_requested.connect(self.handle_update_item)
        elif key in {'weapon_generator', 'god_roll', 'grenade', 'shield', 'repkit', 'heavy_weapon'}:
            tab.batch_add_to_backpack_requested.connect(self.handle_roll_batch_add)
        elif key == 'converter':
            tab.batch_add_requested.connect(self.handle_batch_add)
            tab.iterator_requested.connect(self.handle_iterator_request)
            tab.iterator_add_to_backpack_requested.connect(self.handle_iterator_add_to_backpack)
        elif key == 'loadout_manager':
            tab.live_snapshot_requested.connect(self.handle_live_loadout_snapshot)
            tab.live_apply_requested.connect(self.handle_live_loadout_apply)
            tab.live_recovery_requested.connect(self.handle_live_loadout_recovery)
        if key == 'god_roll':
            tab.worker_started.connect(self._track_god_roll_worker)
            if hasattr(tab, 'open_editor_requested'):
                tab.open_editor_requested.connect(self.handle_open_generated_weapon)

    def _hydrate_tab(self, key, tab):
        if self._character_level and hasattr(tab, 'set_character_level'):
            tab.set_character_level(self._character_level)
        if not self.controller.yaml_obj:
            return
        if key == 'character':
            tab.update_fields(self._character_data or self.controller.get_character_data())
        elif key == 'yaml_editor':
            tab.sync_from_controller()
            self._dirty_item_views.discard('yaml')
        elif key == 'loadout_manager':
            save_path = str(self.controller.save_path) if self.controller.save_path else None
            tab.set_data(self.controller.yaml_obj, save_path, dirty_callback=self.controller.mark_dirty)

    def add_tab(self, widget: QWidget, text: str, icon_char: str):
        index = self.content_stack.addWidget(widget)
        full_text = f"{icon_char}  {text}"
        button = QPushButton(full_text)
        button.setProperty("navItem", True)
        button.setProperty("navCollapsed", not self.is_nav_bar_expanded)
        button.setProperty("fullText", full_text)
        button.setProperty("iconChar", icon_char)
        button.setProperty("navLabel", text)
        button.setToolTip(text)
        button.setAccessibleName(text)
        button.setCheckable(True)
        button.setFixedHeight(42)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.nav_buttons_layout.addWidget(button)
        self.nav_button_group.addButton(button, index)
        return index

    def _add_nav_separator(self):
        separator = QWidget()
        separator.setObjectName("navSeparator")
        separator.setFixedHeight(1)
        separator.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.nav_buttons_layout.addWidget(separator)

    def _calculate_nav_bar_expanded_width(self):
        text_width = max((
            button.fontMetrics().horizontalAdvance(str(button.property("fullText") or ""))
            for button in self.nav_button_group.buttons()
        ), default=0)
        return min(
            self._NAV_EXPANDED_MAX_WIDTH,
            max(self._NAV_EXPANDED_MIN_WIDTH, text_width + self._NAV_HORIZONTAL_CHROME),
        )

    def _refresh_nav_bar(self):
        self.nav_bar_width_expanded = self._calculate_nav_bar_expanded_width()
        collapsed = not self.is_nav_bar_expanded
        target_width = (
            self.nav_bar_width_collapsed if collapsed else self.nav_bar_width_expanded
        )
        available_text_width = max(
            1, self.nav_bar_width_expanded - self._NAV_HORIZONTAL_CHROME
        )

        self.nav_bar.setProperty("navCollapsed", collapsed)
        self.nav_bar.setFixedWidth(target_width)
        self.toggle_button.setText("›" if collapsed else "‹")

        for button in self.nav_button_group.buttons():
            button.setProperty("navCollapsed", collapsed)
            full_text = str(button.property("fullText") or "")
            button.setText(
                str(button.property("iconChar") or "") if collapsed
                else button.fontMetrics().elidedText(
                    full_text, Qt.TextElideMode.ElideRight, available_text_width
                )
            )
            button.setToolTip(str(button.property("navLabel") or ""))
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

        self.nav_bar.updateGeometry()
    
    def switch_to_tab(self, index: int):
        if 0 <= index < self.content_stack.count():
            key = next((key for key, value in self._lazy_tab_indexes.items() if value == index), None)
            if key is not None:
                self._ensure_tab(key)
            self.content_stack.setCurrentIndex(index)
            self._refresh_inventory_view(index)
            
            # The button group `idClicked` signal is connected to `handle_nav_click`,
            # which already calls `setCurrentIndex`. To avoid recursion and redundant calls,
            # we directly update the button's checked state and styles.
            button_to_check = self.nav_button_group.button(index)
            if button_to_check and not button_to_check.isChecked():
                # Manually set the button as checked. This will not emit `idClicked`.
                button_to_check.setChecked(True)
            self.update_action_states()

    @pyqtSlot(int)
    def handle_nav_click(self, index: int):
        key = next((key for key, value in self._lazy_tab_indexes.items() if value == index), None)
        if key is not None:
            self._ensure_tab(key)
        self.content_stack.setCurrentIndex(index)
        self._refresh_inventory_view(index)
        self.update_action_states()

    def invalidate_items_snapshot(self):
        self._items_snapshot = None
        self._dirty_item_views.update(("items", "weapon", "yaml"))

    def get_items_snapshot(self):
        if self._items_snapshot is None:
            self._items_snapshot = self.controller.get_all_items() if self.controller.yaml_obj else []
        return self._items_snapshot

    def _refresh_inventory_view(self, index):
        if not hasattr(self, "content_stack") or not (0 <= index < self.content_stack.count()):
            return
        current = self.content_stack.widget(index)
        items_tab = self._loaded_tab('items')
        weapon_tab = self._loaded_tab('weapon_editor')
        yaml_tab = self._loaded_tab('yaml_editor')
        if current is items_tab and "items" in self._dirty_item_views:
            items_tab.update_tree(self.get_items_snapshot())
            self._dirty_item_views.discard("items")
        elif current is weapon_tab and "weapon" in self._dirty_item_views:
            weapon_tab.refresh_backpack_items(self.get_items_snapshot())
            self._dirty_item_views.discard("weapon")
        elif current is yaml_tab and "yaml" in self._dirty_item_views:
            if self.controller.yaml_obj:
                yaml_tab.sync_from_controller()
            self._dirty_item_views.discard("yaml")

    def browse_and_open_save(self):
        """
        打开文件选择对话框，让用户手动选择存档文件。
        """
        # 尝试定位到默认的存档路径作为起始目录
        custom_save = self.selector_page.get_custom_save_path()
        if custom_save and os.path.exists(custom_save):
            initial_path = custom_save
        else:
            initial_path = os.path.expanduser('~')

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.loc['header']['open'], 
            initial_path,
            self.loc['dialogs'].get('save_filter', "Borderlands 4 Saves (*.sav);;All Files (*.*)")
        )

        if not file_path:
            return

        self.open_save_from_selector(file_path, infer_user_id_from_save_path(file_path))

    @pyqtSlot()
    def toggle_nav_bar(self):
        self.is_nav_bar_expanded = not self.is_nav_bar_expanded
        self._settings.setValue(self._NAV_STATE_KEY, self.is_nav_bar_expanded)
        self._refresh_nav_bar()

    @pyqtSlot(str, str)
    def open_save_from_selector(self, file_path_str: str, user_id: str):
        file_path = Path(file_path_str)
        current_user_id = user_id
        
        custom_backup_path = self.selector_page.get_custom_backup_path()
        
        # 标记是否是第一次尝试，用于控制错误信息的显示
        # 如果一开始就没有ID，不算是一次"失败"的尝试，直接提示输入
        first_attempt = True

        while True:
            try:
                _, platform, backup_name = self.controller.decrypt_save(file_path, current_user_id, custom_backup_path)
                
                # Success
                QMessageBox.information(self, self.loc['dialogs']['success'],
                                        self.loc['dialogs']['decrypt_success'].format(platform=platform.upper(), backup_name=backup_name))
                self.setWindowTitle(f"{self.loc['window_title']} V{VERSION} - {file_path.name}")

                self._set_autosave_indicator("", False)
                self._maybe_restore_recovery(file_path)
                QTimer.singleShot(0, self.refresh_all_tabs)
                self.switch_to_tab(1)  # Switch to character tab
                return # Break loop and exit

            except Exception as e:
                # Prepare dialog message
                dialog_title = self.loc['dialogs']['user_id_needed']
                dialog_msg = self.loc['dialogs']['enter_user_id']
                
                # 如果是尝试过一次（且不是因为ID为空导致的验证错误），或者ID本身就不为空但失败了
                if (not first_attempt) or (current_user_id and str(e) != "User ID cannot be empty"):
                     # 简化错误信息显示，只显示第一行关键信息
                    short_err = self.loc['dialogs'].get(
                        'decrypt_failed_reason',
                        "The save could not be decrypted with the current user ID.",
                    )
                    
                    dialog_title = self.loc['dialogs']['decrypt_failed']
                    dialog_msg = self.loc['dialogs']['decrypt_failed_msg'].format(user_id=current_user_id, error=short_err)

                # Popup input dialog
                text, ok = QInputDialog.getText(self, dialog_title, dialog_msg, QLineEdit.EchoMode.Normal, current_user_id)
                
                if ok:
                    current_user_id = text.strip()
                    first_attempt = False
                else:
                    # User cancelled
                    # If it was a critical failure during the first automated attempt, maybe show the error?
                    # But usually cancel means "I give up".
                    if not first_attempt: # If user gave up after a retry
                        QMessageBox.warning(self, self.loc['dialogs']['cancel'], self.loc['dialogs']['open_cancelled'])
                    return

    def update_action_states(self):
        has_save = self.controller.yaml_obj is not None and not self._live_active
        self.save_action.setEnabled(has_save)
        self.save_as_action.setEnabled(has_save)
        self.save_button.setEnabled(has_save)
        self.save_as_button.setEnabled(has_save)

    def _all_content_tabs(self):
        return [self.selector_page, *self._loaded_tabs.values()]

    @pyqtSlot()
    def scan_for_saves(self):
        custom_path = self.selector_page.get_custom_save_path()
        saves = self.controller.scan_save_folders(custom_path)
        self.selector_page.update_view(saves)

    def refresh_all_tabs(self, *, invalidate_items=True):
        if not self.controller.yaml_obj: return
        self.log("Main window: Starting to refresh all tabs.")
        try:
            if invalidate_items:
                self.invalidate_items_snapshot()
            char_data = self.controller.get_character_data()
            self._character_data = char_data
            character_tab = self._loaded_tab('character')
            if character_tab is not None:
                character_tab.update_fields(char_data)
                self.log("  - Character tab refreshed.")
            # 同步角色等级到所有编辑器Tab的默认等级
            char_level = char_data.get("角色等级", "") if char_data else ""
            if char_level:
                self._character_level = str(char_level)
                for tab in self._loaded_tabs.values():
                    if hasattr(tab, 'set_character_level'):
                        tab.set_character_level(char_level)
                self.log(f"  - Character level ({char_level}) synced to editor tabs.")
            yaml_tab = self._loaded_tab('yaml_editor')
            if yaml_tab is not None:
                yaml_tab.sync_from_controller()
                self._dirty_item_views.discard("yaml")
                self.log("  - YAML editor tab refreshed.")
            loadout_tab = self._loaded_tab('loadout_manager')
            if loadout_tab is not None:
                save_path = str(self.controller.save_path) if self.controller.save_path else None
                loadout_tab.set_data(self.controller.yaml_obj, save_path,
                                     dirty_callback=self.controller.mark_dirty)
                self.log("  - Loadout manager tab data set.")
        except Exception as e:
            self.log(f"CRITICAL: An exception occurred during refresh_all_tabs: {e}", force_popup=True)
        self._refresh_inventory_view(self.content_stack.currentIndex())
        self.log("Main window: Finished refreshing all tabs.")

    # ------------------------------------------------------------------
    # live (online) mode
    # ------------------------------------------------------------------
    def _live_text(self, key, fallback, **values):
        text = self.loc.get('live', {}).get(key, fallback)
        return text.format(**values) if values else text

    def _update_live_header_text(self):
        if not hasattr(self, 'live_toggle_button'):
            return
        if self._live_connecting:
            symbol, state = "…", self._live_text('connecting', 'Connecting…')
        elif self._live_active:
            symbol, state = "●", self._live_text('online', 'Online')
        else:
            symbol, state = "○", self._live_text('offline', 'Offline')
        self.live_toggle_button.setText(f"{symbol} {state}")
        self.live_toggle_button.setToolTip(self._live_text(
            'toggle_tooltip',
            'Connect to the running game (127.0.0.1:28777) to read and edit inventory items.',
        ))
        self.live_toggle_button.setAccessibleName(self._live_text('mode_accessible', 'Live mode'))
        active_changed = self.live_toggle_button.property('liveActive') != self._live_active
        self.live_toggle_button.setProperty('liveActive', self._live_active)
        if active_changed:
            self.live_toggle_button.style().unpolish(self.live_toggle_button)
            self.live_toggle_button.style().polish(self.live_toggle_button)
        self.live_refresh_button.setText(f"↻ {self._live_text('refresh', 'Refresh')}")
        self.live_refresh_button.setToolTip(self._live_text(
            'refresh_tooltip', 'Refresh items from the running game (live mode only).'
        ))
        self.live_refresh_button.setAccessibleName(self._live_text('refresh_accessible', 'Refresh live items'))

    def _toggle_live_mode(self):
        if not self._live_active:
            self._enter_live_mode()
        else:
            self._exit_live_mode()

    def _track_live_worker(self, worker):
        self._live_workers.add(worker)
        worker.finished.connect(lambda worker=worker: self._on_live_worker_finished(worker))
        worker.finished.connect(worker.deleteLater)

    def _track_god_roll_worker(self, worker):
        self._god_roll_worker = worker
        worker.finished.connect(lambda worker=worker: self._on_god_roll_worker_finished(worker))

    def _on_god_roll_worker_finished(self, worker):
        if self._god_roll_worker is worker:
            self._god_roll_worker = None
        if self._close_when_live_idle and not any(
            item.isRunning() for item in self._live_workers
        ):
            QTimer.singleShot(0, self.close)

    def _on_live_worker_finished(self, worker):
        self._live_workers.discard(worker)
        if self._live_thread is worker:
            self._live_thread = None
        if self._live_runtime_worker is worker:
            self._live_runtime_worker = None
        if self._live_batch_spawn_worker is worker:
            self._live_batch_spawn_worker = None
            self._batch_add_active = False
            self._sync_live_action_buttons()
        if self._close_when_live_idle and not any(
            item.isRunning() for item in self._live_workers
        ):
            QTimer.singleShot(0, self.close)

    def _live_fetch_busy(self):
        return self._live_thread is not None

    def _live_runtime_busy(self):
        return self._live_runtime_worker is not None

    def _live_batch_busy(self):
        worker = self._live_batch_spawn_worker
        try:
            return worker is not None and worker.isRunning()
        except RuntimeError:
            return False

    def _live_any_busy(self):
        return self._live_fetch_busy() or self._live_runtime_busy() or self._live_batch_busy()

    def _remember_live_inventory_recovery(self, source):
        pending, reason = _live_inventory_recovery_state(source)
        if pending is not True and pending is not False:
            return
        self._live_recovery_pending = pending
        self._live_recovery_reason = (
            str(reason or '') if pending else ''
        )

    def _guard_live_inventory_mutation(self, reject=None):
        if getattr(self, '_live_recovery_pending', None) is not True:
            return True
        reason = str(getattr(self, '_live_recovery_reason', '') or self._live_text(
            'inventory_recovery_reason', 'unresolved loadout recovery requires review'
        ))
        message = self._live_text(
            'inventory_mutation_recovery_pending',
            'Inventory writes are locked until the pending recovery is reviewed or cleared: {reason}',
            reason=reason,
        )
        if callable(reject):
            reject(message)
        else:
            QMessageBox.warning(self, self._live_text('title', 'Live Mode'), message)
        return False

    def _sync_live_action_buttons(self):
        busy = self._live_any_busy()
        recovery_pending = getattr(self, '_live_recovery_pending', None) is True
        self.live_toggle_button.setEnabled(not busy)
        self.live_refresh_button.setEnabled(self._live_active and not busy)
        character_tab = self._loaded_tab('character')
        if character_tab is not None:
            character_tab.set_runtime_busy(busy)
            setter = getattr(character_tab, 'set_inventory_mutation_blocked', None)
            if callable(setter):
                setter(recovery_pending)
        loadout_tab = self._loaded_tab('loadout_manager')
        if loadout_tab is not None:
            loadout_tab.set_live_busy(busy)
            setter = getattr(loadout_tab, 'set_inventory_mutation_blocked', None)
            if callable(setter):
                setter(recovery_pending)

    def _clear_live_item_editor_selection(self):
        """Drop path-based editor state before a full live snapshot replaces slot mappings."""
        try:
            weapon_tab = self._loaded_tab('weapon_editor')
            if (
                weapon_tab is not None
                and getattr(weapon_tab, 'selected_weapon_path', None) is not None
            ):
                weapon_tab.clear_all_fields()
        except Exception:
            pass

    def _enter_live_mode(self):
        if self.controller.dirty and self.controller.yaml_obj is not None:
            QMessageBox.warning(
                self, self._live_text('title', 'Live Mode'),
                self._live_text(
                    'unsaved_changes_blocked',
                    'Save or discard the current offline changes before entering live mode.',
                ),
            )
            return
        if (
            self._batch_add_active
            or self._live_any_busy()
            or (self._god_roll_worker is not None and self._god_roll_worker.isRunning())
        ):
            QMessageBox.warning(
                self, self._live_text('title', 'Live Mode'),
                self._live_text('runtime_busy', 'Another live action is still running.'),
            )
            return
        try:
            from live.bridge import Bridge  # noqa
            from live.adapter import fetch_live_yaml  # noqa
        except Exception as e:
            self.log(self._live_text(
                'unavailable', 'Live mode is unavailable (live/ package): {error}', error=e
            ), force_popup=True)
            return

        self._live_bridge = Bridge()
        self._live_recovery_pending = None
        self._live_recovery_reason = ''
        if not self._live_bridge.ping():
            self._live_bridge = None
            QMessageBox.warning(
                self, self._live_text('title', 'Live Mode'),
                self._live_text(
                    'connection_failed',
                    'Could not connect to the game (127.0.0.1:28777).\n'
                    'Make sure the game is running, a character is loaded, and the bl4_live mod is active.',
                ),
            )
            return

        self._live_connecting = True
        self.live_toggle_button.setEnabled(False)
        self._update_live_header_text()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self._live_watchdog = QTimer(self)
        self._live_watchdog.setSingleShot(True)
        self._live_watchdog.timeout.connect(self._on_live_timeout)
        self._live_watchdog.start(15000)

        worker = _LiveFetchWorker(self._live_bridge, self)
        worker.loaded.connect(self._on_live_loaded)
        self._live_thread = worker
        self._track_live_worker(worker)
        self._sync_live_action_buttons()
        worker.start()

    def _on_live_loaded(self, yaml_like, err):
        worker = self.sender()
        if worker is not self._live_thread:
            return
        self._live_thread = None
        self._stop_live_watchdog()
        QApplication.restoreOverrideCursor()
        self._live_connecting = False
        self._sync_live_action_buttons()
        if err is not None or yaml_like is None:
            self._live_bridge = None
            self._update_live_header_text()
            self.log(self._live_text('fetch_failed', 'Live fetch failed: {error}', error=err), force_popup=True)
            return

        self._live_active = True
        self._clear_live_item_editor_selection()
        self.controller.yaml_obj = yaml_like
        self.controller.mark_clean()

        self.live_refresh_button.setEnabled(True)
        self._update_live_header_text()
        self._apply_live_ui_state()
        self.setWindowTitle(
            f"{self.loc['window_title']} V{VERSION} - [{self._live_text('online', 'Online')}]"
        )
        self.refresh_all_tabs()
        self.handle_live_runtime_action('state', {'_quiet': True})
        self.log(self._live_text('synced', 'Live backpack and bank items synchronized.'))

    def _stop_live_watchdog(self):
        wd = getattr(self, "_live_watchdog", None)
        if wd is not None:
            wd.stop()

    def _on_live_timeout(self):
        """Failsafe: if the worker never reports back, never leave the cursor spinning."""
        QApplication.restoreOverrideCursor()
        self._live_connecting = False
        self._sync_live_action_buttons()
        self._update_live_header_text()
        self.log(self._live_text(
            'timeout', 'Live fetch timed out after 15 seconds. The game or bl4_live may not be running.'
        ), force_popup=True)

    def _live_refresh(self):
        if not self._live_active or self._live_bridge is None:
            return
        if self._live_any_busy():
            return
        self.live_toggle_button.setEnabled(False)
        self.live_refresh_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self._live_watchdog = QTimer(self)
        self._live_watchdog.setSingleShot(True)
        self._live_watchdog.timeout.connect(self._on_live_timeout)
        self._live_watchdog.start(15000)

        worker = _LiveFetchWorker(self._live_bridge, self)
        worker.loaded.connect(self._on_live_refreshed)
        self._live_thread = worker
        self._track_live_worker(worker)
        self._sync_live_action_buttons()
        worker.start()

    def _on_live_refreshed(self, yaml_like, err):
        worker = self.sender()
        if worker is not self._live_thread:
            return
        self._live_thread = None
        self._stop_live_watchdog()
        QApplication.restoreOverrideCursor()
        self._sync_live_action_buttons()
        if not self._live_active:
            return
        if err is not None or yaml_like is None:
            self.log(self._live_text('refresh_failed', 'Live refresh failed: {error}', error=err), force_popup=True)
            return
        self._clear_live_item_editor_selection()
        self.controller.yaml_obj = yaml_like
        self.controller.mark_clean()
        self.refresh_all_tabs()
        self.handle_live_runtime_action('state', {'_quiet': True})
        self.log(self._live_text('refreshed', 'Live items refreshed.'))

    def _commit_live_inventory_patch(
        self,
        records,
        *,
        require_existing=False,
        expected_serials=None,
    ):
        """Patch a verified write response locally, or fall back to one live read."""
        from live.adapter import items_to_yaml, patch_live_yaml_items

        records = list(records or [])
        paths = patch_live_yaml_items(
            self.controller.yaml_obj,
            records,
            require_existing=require_existing,
            expected_serials=expected_serials,
        )
        if paths is None:
            self._live_refresh()
            return False

        # Preserve the already-decoded inventory cache: decode only changed
        # serials, then let the current view rebuild from that patched list.
        if self._items_snapshot is not None:
            raw_records = [
                {
                    "ok": True,
                    "container": record["container"],
                    "idx": record.get("idx", record.get("index")),
                    "serial": record["serial"],
                }
                for record in records
            ]
            changed_items = bl4f.process_and_load_items(items_to_yaml(raw_records))
            changed_by_path = {
                tuple(item.get("original_path") or ()): item for item in changed_items
            }
            if len(changed_by_path) == len(paths):
                snapshot_by_path = {
                    tuple(item.get("original_path") or ()): index
                    for index, item in enumerate(self._items_snapshot)
                }
                for path in map(tuple, paths):
                    item = changed_by_path.get(path)
                    old_index = snapshot_by_path.get(path)
                    if item is None or (require_existing and old_index is None):
                        self._items_snapshot = None
                        break
                    if old_index is None:
                        self._items_snapshot.append(item)
                    else:
                        self._items_snapshot[old_index] = item
            else:
                self._items_snapshot = None

        self.controller.mark_clean()
        self._dirty_item_views.update(("items", "weapon", "yaml"))
        self._refresh_inventory_view(self.content_stack.currentIndex())
        return True

    def _exit_live_mode(self):
        if self._live_any_busy():
            character_tab = self._loaded_tab('character')
            if character_tab is not None:
                character_tab.set_runtime_result(
                    self._live_text('runtime_busy', 'Another live action is still running.'),
                    False,
                )
            return
        self._live_active = False
        self._live_connecting = False
        self._live_bridge = None
        self._live_recovery_pending = None
        self._live_recovery_reason = ''
        self.controller.yaml_obj = None
        self.controller.save_path = None
        self.controller.mark_clean()
        self.invalidate_items_snapshot()

        self.live_refresh_button.setEnabled(False)
        self._update_live_header_text()
        self._apply_live_ui_state()
        loadout_tab = self._loaded_tab('loadout_manager')
        if loadout_tab is not None:
            loadout_tab.set_data(None, None, dirty_callback=None)
        self.update_action_states()
        self.setWindowTitle(f"{self.loc['window_title']} V{VERSION}")
        self.switch_to_tab(0)
        self.log(self._live_text('exited', 'Live mode exited.'))

    def _apply_live_ui_state(self, tab_only=None):
        """Disable save-only inputs while the controller holds a live snapshot."""
        is_live = self._live_active
        self._update_live_header_text()
        for btn in (self.save_button, self.save_as_button):
            btn.setEnabled(not is_live)
            btn.setToolTip(self._live_text(
                'save_disabled', 'Unavailable in live mode (no save file).'
            ) if is_live else "")
        self.save_action.setEnabled(not is_live and self.controller.yaml_obj is not None)
        self.save_as_action.setEnabled(not is_live and self.controller.yaml_obj is not None)
        if hasattr(self, 'autosave_checkbox'):
            self.autosave_checkbox.setEnabled(not is_live)
        character_tab = self._loaded_tab('character')
        if character_tab is not None:
            character_tab.set_live_mode(is_live)
            character_tab.set_inventory_mutation_blocked(
                getattr(self, '_live_recovery_pending', None) is True
            )
        loadout_tab = self._loaded_tab('loadout_manager')
        if loadout_tab is not None and (tab_only is None or tab_only[0] == 'loadout_manager'):
            loadout_tab.set_live_mode(is_live)
            loadout_tab.set_inventory_mutation_blocked(
                getattr(self, '_live_recovery_pending', None) is True
            )
        god_roll_tab = self._loaded_tab('god_roll')
        if god_roll_tab is not None and (tab_only is None or tab_only[0] == 'god_roll'):
            god_roll_tab.set_live_mode(is_live)

        # Flags belong to serialized save entries. The live bridge materializes
        # runtime items directly and intentionally ignores them, so leaving the
        # selectors active would promise an effect that cannot exist online.
        owners = dict(self._loaded_tabs)
        if tab_only is not None:
            owners = {tab_only[0]: tab_only[1]}
        flag_widgets = tuple(
            (owners.get(key), widget_name)
            for key, widget_names in {
                'items': ('add_flag_combo',), 'class_mod': ('flag_combo',),
                'enhancement': ('flag_var',), 'weapon_editor': ('flag_combo',),
                'weapon_generator': ('flag_combo',), 'god_roll': ('flag_combo',), 'grenade': ('flag_combo',),
                'shield': ('flag_combo',), 'repkit': ('flag_combo',),
                'heavy_weapon': ('flag_combo',),
                'converter': ('batch_add_flag_combo', 'yaml_flag_combo'),
            }.items()
            for widget_name in widget_names
        )
        for owner, name in flag_widgets:
            widget = getattr(owner, name, None) if owner is not None else None
            if widget is not None:
                if widget.property('offlineToolTip') is None:
                    widget.setProperty('offlineToolTip', widget.toolTip())
                widget.setEnabled(not is_live)
                widget.setToolTip(
                    self._live_text('flag_disabled', 'Save flags are not used in live mode.')
                    if is_live else str(widget.property('offlineToolTip') or "")
                )

    def _start_live_loadout_worker(self, operation, slot, context):
        tab = self._loaded_tab('loadout_manager')
        if not self._live_active or self._live_bridge is None:
            if tab is not None:
                if operation == 'save':
                    tab.finish_live_snapshot(slot, str(context.get('config_name') or ''), None,
                                             'live mode is unavailable')
                elif operation == 'apply':
                    tab.finish_live_apply(slot, None, 'live mode is unavailable')
                else:
                    tab.finish_live_recovery(operation, None, 'live mode is unavailable')
            return
        if self._live_any_busy():
            if tab is not None:
                error = self._live_text('runtime_busy', 'Another live action is still running.')
                if operation == 'save':
                    tab.finish_live_snapshot(slot, str(context.get('config_name') or ''), None, error)
                elif operation == 'apply':
                    tab.finish_live_apply(slot, None, error)
                else:
                    tab.finish_live_recovery(operation, None, error)
            return
        if operation == 'apply' and not self._guard_live_inventory_mutation(
            lambda message: tab.finish_live_apply(slot, None, message) if tab is not None else None
        ):
            return

        worker = _LiveLoadoutWorker(
            self._live_bridge, operation, slot, context, parent=self,
        )
        worker.completed.connect(self._on_live_loadout_finished)
        self._live_runtime_worker = worker
        self._track_live_worker(worker)
        self._sync_live_action_buttons()
        worker.start()

    @pyqtSlot(int, str)
    def handle_live_loadout_snapshot(self, slot, config_name):
        self._start_live_loadout_worker(
            'save', slot, {'config_name': str(config_name or '')},
        )

    @pyqtSlot(int, object)
    def handle_live_loadout_apply(self, slot, payload):
        self._start_live_loadout_worker('apply', slot, dict(payload or {}))

    @pyqtSlot(str)
    def handle_live_loadout_recovery(self, operation):
        operation = 'clear_recovery' if str(operation) == 'clear' else 'recovery'
        self._start_live_loadout_worker(operation, 0, {})

    @pyqtSlot(str, int, object, object, object)
    def _on_live_loadout_finished(self, operation, slot, context, result, err):
        worker = self.sender()
        if operation == 'apply':
            MainWindow._remember_live_inventory_recovery(
                self, getattr(worker, 'mutation_preflight', None)
            )
            MainWindow._remember_live_inventory_recovery(self, result)
        elif isinstance(result, dict):
            if operation == 'recovery' and (
                result.get('pending') is True or result.get('pending') is False
            ):
                MainWindow._remember_live_inventory_recovery(self, result)
                recovery = result.get('recovery')
                reason = recovery.get('reason') if isinstance(recovery, dict) else ''
                MainWindow._remember_live_inventory_recovery(self, {
                    'recovery_pending': result['pending'], 'reason': reason,
                })
            elif operation == 'clear_recovery' and result.get('ok'):
                MainWindow._remember_live_inventory_recovery(
                    self, {'recovery_pending': False}
                )
        if worker is self._live_runtime_worker:
            self._live_runtime_worker = None
        self._sync_live_action_buttons()
        if not self._live_active:
            return
        tab = self._loaded_tab('loadout_manager')
        if tab is None:
            return
        if operation == 'save':
            tab.finish_live_snapshot(
                slot, str((context or {}).get('config_name') or ''), result, err,
            )
        elif operation == 'apply':
            tab.finish_live_apply(slot, result, err)
            self._live_refresh()
        else:
            tab.finish_live_recovery(operation, result, err)
            if operation == 'clear_recovery':
                self._live_refresh()
        if isinstance(result, dict) and result.get('ok'):
            self.log(self._live_text(
                'runtime_action_done', 'Live runtime action completed: {action}',
                action={
                    'save': 'loadout_snapshot',
                    'apply': 'apply_loadout',
                    'recovery': 'loadout_recovery',
                    'clear_recovery': 'clear_loadout_recovery',
                }.get(operation, operation),
            ))

    @pyqtSlot(str, object)
    def handle_live_runtime_action(self, action: str, params=None):
        if not self._live_active or self._live_bridge is None:
            return
        character_tab = self._ensure_tab('character')
        request_params = dict(params or {})
        quiet = bool(request_params.pop('_quiet', False))
        if self._live_any_busy():
            if not quiet:
                character_tab.set_runtime_result(
                    self._live_text('runtime_busy', 'Another live action is still running.'),
                    False,
                )
            return
        if action in _LIVE_INVENTORY_MUTATION_ACTIONS and not self._guard_live_inventory_mutation(
            lambda message: character_tab.set_runtime_result(message, False)
        ):
            return

        button = getattr(character_tab, 'live_runtime_buttons', {}).get(action)
        label = button.text() if button is not None else action
        try:
            if action == 'toggle_dedicated_drop_100' and request_params.get('enabled'):
                catalog = resource_loader.load_json_resource('core/data/dedicated_drop_pools.json')
                if not catalog:
                    raise RuntimeError('dedicated_drop_pools.json missing or invalid')
                request_params['catalog'] = catalog
        except Exception as exc:
            if not quiet:
                character_tab.set_runtime_result(f"{label}: {exc}", False)
            if action in character_tab.live_runtime_toggle_actions:
                self.handle_live_runtime_action('state', {'_quiet': True})
            return

        if button is not None:
            button.setEnabled(False)
        worker = _LiveRuntimeWorker(
            self._live_bridge,
            action,
            request_params,
            quiet=quiet,
            parent=self,
        )
        worker.completed.connect(self._on_live_runtime_action_finished)
        self._live_runtime_worker = worker
        self._track_live_worker(worker)
        self._sync_live_action_buttons()
        worker.start()

    @pyqtSlot(str, object, object, bool)
    def _on_live_runtime_action_finished(self, action, result, err, quiet=False):
        worker = self.sender()
        if action in _LIVE_INVENTORY_MUTATION_ACTIONS:
            MainWindow._remember_live_inventory_recovery(
                self, getattr(worker, 'mutation_preflight', None)
            )
            MainWindow._remember_live_inventory_recovery(self, result)
        if worker is self._live_runtime_worker:
            self._live_runtime_worker = None
        if not self._live_active:
            return

        character_tab = self._ensure_tab('character')
        button = getattr(character_tab, 'live_runtime_buttons', {}).get(action)
        label = button.text() if button is not None else action
        character_tab.set_runtime_busy(False)

        if err is not None or not isinstance(result, dict):
            if not quiet:
                character_tab.set_runtime_result(f"{label}: {err or 'invalid response'}", False)
            if action == 'claim_lost_loot':
                self._live_refresh()
            elif action != 'state':
                self.handle_live_runtime_action('state', {'_quiet': True})
            else:
                self._sync_live_action_buttons()
            return

        state = result.get('state')
        if isinstance(state, dict):
            character_tab.apply_runtime_state(state)

        delta = result.get('inventory_delta')
        changed_count = int(result.get('claimed_count', result.get('claimed', 0)) or 0)
        needs_full_refresh = bool(result.get('changed')) or changed_count > 0
        if isinstance(delta, dict):
            records = delta.get('records')
            incremental_safe = bool(result.get('incremental_safe', True))
            if incremental_safe and isinstance(records, list) and records:
                normalized = []
                container = str(delta.get('container') or 'BackpackItems')
                for record in records:
                    if not isinstance(record, dict):
                        normalized = []
                        break
                    row = dict(record)
                    row.setdefault('container', container)
                    row.setdefault('idx', row.get('index'))
                    normalized.append(row)
                if normalized:
                    self._commit_live_inventory_patch(normalized)
                    needs_full_refresh = False
                else:
                    needs_full_refresh = True
            elif not incremental_safe or changed_count > 0 or result.get('changed'):
                needs_full_refresh = True
        if needs_full_refresh:
            self._live_refresh()

        if not self._live_fetch_busy():
            self._sync_live_action_buttons()

        if quiet:
            return
        if result.get('ok'):
            character_tab.set_runtime_result(f"{label}: OK", True)
            self.log(self._live_text(
                'runtime_action_done', 'Live runtime action completed: {action}', action=action
            ))
        else:
            character_tab.set_runtime_result(
                f"{label}: {str(result.get('error', 'failed'))}",
                False,
            )
            if not isinstance(state, dict) and action in character_tab.live_runtime_toggle_actions:
                self.handle_live_runtime_action('state', {'_quiet': True})

    def log(self, message, force_popup=False):
        print(message)
        if force_popup:
            QMessageBox.critical(self, self.loc['dialogs']['critical'], str(message))

    # ------------------------------------------------------------------
    # 自动保存：脏标记驱动 + 静默期防抖 + 原子写盘 + 崩溃恢复副本
    # ------------------------------------------------------------------
    def _init_autosave(self, footer_layout):
        self._autosave_suspend = 0
        self._autosave_status_message = ""
        self._autosave_status_failed = False
        self.autosave_enabled = self._settings.value('autosave_enabled', True, type=bool)
        self.autosave_interval_ms = max(5, int(self._settings.value('autosave_interval_sec', 30, type=int))) * 1000
        self.recover_interval_ms = 5000

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._perform_autosave)
        self._recover_timer = QTimer(self)
        self._recover_timer.setSingleShot(True)
        self._recover_timer.timeout.connect(self._write_recovery)

        self.autosave_checkbox = QCheckBox(self.loc['status'].get('autosave', "自动保存"))
        self.autosave_checkbox.setChecked(self.autosave_enabled)
        self.autosave_checkbox.setToolTip(self.loc['status'].get('autosave_tip', "停止修改约30秒后自动写盘（原子写入，旧文件轮转为 .prev.bak）"))
        self.autosave_checkbox.toggled.connect(self._toggle_autosave)
        footer_layout.addWidget(self.autosave_checkbox)
        self._set_autosave_indicator()

        self.controller.add_dirty_listener(self._on_controller_dirty)

    def _set_autosave_indicator(self, message=None, failed=None):
        if message is not None:
            self._autosave_status_message = message
        if failed is not None:
            self._autosave_status_failed = failed

        label = self.loc['status'].get('autosave', "自动保存")
        self.autosave_checkbox.setText(
            f"⚠ {label}" if self._autosave_status_failed else label
        )
        tooltip = self.loc['status'].get(
            'autosave_tip',
            "停止修改约30秒后自动写盘（原子写入，旧文件轮转为 .prev.bak）",
        )
        if self._autosave_status_message:
            tooltip += f"\n{self._autosave_status_message}"
        self.autosave_checkbox.setToolTip(tooltip)

        if self.autosave_checkbox.property('autosaveError') != self._autosave_status_failed:
            self.autosave_checkbox.setProperty('autosaveError', self._autosave_status_failed)
            self.autosave_checkbox.style().unpolish(self.autosave_checkbox)
            self.autosave_checkbox.style().polish(self.autosave_checkbox)
            self.autosave_checkbox.update()

    def _toggle_autosave(self, on):
        self.autosave_enabled = on
        self._settings.setValue('autosave_enabled', on)
        self._set_autosave_indicator("", False)
        if not on:
            self._autosave_timer.stop()
            self._recover_timer.stop()
        elif self.controller.dirty:
            self._on_controller_dirty()

    def _suspend_autosave(self, suspend: bool):
        """后台 worker（批量添加/迭代器）运行期间挂起自动保存，避免序列化中间态。"""
        self._autosave_suspend = max(0, self._autosave_suspend + (1 if suspend else -1))
        if not suspend and self._autosave_suspend == 0 and self.controller.dirty:
            self._on_controller_dirty()

    def _on_controller_dirty(self):
        if not self.autosave_enabled:
            return
        # 静默期防抖：持续修改只会在停手后触发一次
        self._autosave_timer.start(self.autosave_interval_ms)
        self._recover_timer.start(self.recover_interval_ms)

    def _recovery_path(self, save_path=None) -> Path | None:
        save_path = save_path or self.controller.save_path
        if not save_path:
            return None
        sp = Path(save_path)
        return sp.with_name(sp.name + ".recover")

    def _write_recovery(self):
        """轻量保险：把当前 YAML 明文写入 .recover，崩溃后可恢复。"""
        if not self.controller.dirty or self.controller.yaml_obj is None:
            return
        if self._autosave_suspend > 0:
            self._recover_timer.start(self.recover_interval_ms)
            return
        rp = self._recovery_path()
        if rp is None:
            return
        try:
            tmp = rp.with_name(rp.name + ".tmp")
            tmp.write_text(self.controller.get_yaml_string(), encoding="utf-8")
            os.replace(tmp, rp)
        except Exception as e:
            self.log(f"Recovery write failed: {e}")

    def _remove_recovery(self, save_path=None):
        rp = self._recovery_path(save_path)
        if rp and rp.exists():
            try:
                rp.unlink()
            except OSError:
                pass

    def _perform_autosave(self):
        if not self.controller.dirty or self.controller.yaml_obj is None:
            return
        if self._autosave_suspend > 0:
            # worker 还在跑，稍后重试
            self._autosave_timer.start(self.recover_interval_ms)
            return
        if not self.controller.save_path:
            return
        # 内容摘要与上次写盘一致 → 无实际变化，直接标干净，不重复写盘
        if self.controller.is_content_saved():
            self.controller.mark_clean()
            self._remove_recovery()
            self._set_autosave_indicator("", False)
            return
        try:
            target = self.controller.save_to_disk()
            self._remove_recovery()
            self._set_autosave_indicator(
                self.loc['status'].get('autosaved', "已自动保存 {time}").format(
                    time=time.strftime("%H:%M:%S")
                ),
                False,
            )
            self.log(f"Auto-saved to {target}")
        except Exception as e:
            self.log(f"Auto-save failed: {e}")
            self._set_autosave_indicator(
                self.loc['status'].get('autosave_failed', "自动保存失败，请手动保存"),
                True,
            )
            # 失败则稍后重试，避免静默丢数据
            self._autosave_timer.start(self.recover_interval_ms)

    def _maybe_restore_recovery(self, file_path: Path):
        """打开存档时：若存在更新的 .recover（上次崩溃/异常退出残留），询问是否恢复。"""
        rp = Path(str(file_path) + ".recover")
        try:
            if not rp.exists() or rp.stat().st_mtime <= file_path.stat().st_mtime:
                if rp.exists():
                    rp.unlink()
                return
        except OSError:
            return
        reply = QMessageBox.question(
            self,
            self.loc['dialogs'].get('recover_title', "恢复未保存的修改"),
            self.loc['dialogs'].get('recover_msg', "检测到上次有未保存的修改（可能因意外退出残留）。是否恢复？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                text = rp.read_text(encoding="utf-8")
                if self.controller.update_yaml_object(text):
                    self._set_autosave_indicator(
                        self.loc['status'].get('recovered', "已恢复未保存的修改（尚未写盘）"),
                        False,
                    )
                    return
            except Exception as e:
                self.log(f"Recovery restore failed: {e}")
        self._remove_recovery()

    def closeEvent(self, event):
        god_roll_running = self._god_roll_worker is not None and self._god_roll_worker.isRunning()
        if any(worker.isRunning() for worker in self._live_workers) or god_roll_running:
            self._close_when_live_idle = True
            if god_roll_running and hasattr(self._god_roll_worker, 'cancel'):
                self._god_roll_worker.cancel()
            event.ignore()
            return
        # 退出时若有未保存修改，确保恢复副本是最新的
        if self.controller.dirty and self.controller.yaml_obj is not None:
            self._write_recovery()
        super().closeEvent(event)

    @pyqtSlot(str, str)
    def handle_add_to_backpack(self, serial_input: str, flag: str):
        if not self.controller.yaml_obj: 
            QMessageBox.warning(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['load_save_first'])
            return

        # --- online (live) mode: spawn a new item into the game's backpack ---
        if getattr(self, '_live_active', False) and getattr(self, '_live_bridge', None) is not None:
            self._live_add_to_backpack(serial_input)
            return

        try:
            if serial_input.strip().startswith('@U'):
                final_serial = serial_input
            else:
                encoded_serial, err = b_encoder.encode_to_base85(serial_input)
                if err:
                    QMessageBox.critical(self, self.loc['dialogs']['encode_failed'], 
                                         self.loc['dialogs']['encode_failed_msg'].format(error=err))
                    return
                final_serial = encoded_serial
            
            path = self.controller.add_item_to_backpack(final_serial, flag)
            if path:
                QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['add_success'])
                self.invalidate_items_snapshot()
                self._refresh_inventory_view(self.content_stack.currentIndex())
            else:
                QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['add_fail'])

        except Exception as e:
            self.log(self.loc['dialogs']['add_error'].format(error=e), force_popup=True)

    def _live_add_to_backpack(self, serial_input: str):
        """Online add: spawn a new item into the running game's backpack."""
        if self._live_any_busy():
            QMessageBox.warning(
                self, self._live_text('title', 'Live Mode'),
                self._live_text('runtime_busy', 'Another live action is still running.'),
            )
            return
        if not self._guard_live_inventory_mutation():
            return
        preflight = _live_inventory_mutation_preflight(self._live_bridge)
        MainWindow._remember_live_inventory_recovery(self, preflight)
        self._sync_live_action_buttons()
        if preflight['blocked']:
            self._guard_live_inventory_mutation()
            return
        try:
            if serial_input.strip().startswith('@U'):
                final_serial = serial_input.strip()
            else:
                encoded_serial, err = b_encoder.encode_to_base85(serial_input)
                if err:
                    QMessageBox.critical(self, self.loc['dialogs']['encode_failed'],
                                         self.loc['dialogs']['encode_failed_msg'].format(error=err))
                    return
                final_serial = encoded_serial
        except Exception as e:
            self.log(self._live_text(
                'add_encode_failed', 'Failed to encode the live item: {error}', error=e
            ), force_popup=True)
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = self._live_bridge.spawn(final_serial, "BackpackItems")
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.log(self._live_text(
                'spawn_failed', 'Live item spawn failed: {error}',
                error=f"{type(e).__name__}: {e}",
            ), force_popup=True)
            return
        QApplication.restoreOverrideCursor()
        MainWindow._remember_live_inventory_recovery(self, res)
        self._sync_live_action_buttons()

        if res.get('ok'):
            QMessageBox.information(
                self,
                self._live_text('title', 'Live Mode'),
                self._live_text('spawn_success', 'A new item was spawned into the game backpack.'),
            )
            spawned = res.get('items')
            if isinstance(spawned, list) and len(spawned) == 1:
                record = dict(spawned[0])
                record['container'] = 'BackpackItems'
                record['idx'] = record.get('index')
                self._commit_live_inventory_patch([record])
            else:
                self._live_refresh()
        else:
            self.log(self._live_text(
                'spawn_rejected', 'The game rejected the live item spawn: {error}',
                error=res.get('error'),
            ), force_popup=True)
    
    @pyqtSlot(dict)
    def handle_update_item(self, payload: dict):
        if not self.controller.yaml_obj:
            QMessageBox.warning(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['load_save_first'])
            return
        # --- online (live) mode: write straight into the running game ---
        if self._live_active and self._live_bridge is not None:
            self._live_update_item(payload)
            return
        try:
            # The controller's update_item method is designed to handle the logic 
            # of whether to re-encode based on changed data.
            msg = self.controller.update_item(
                item_path=payload['item_path'],
                original_item_data=payload['original_item_data'],
                new_item_data=payload['new_item_data']
            )
            final_msg = payload.get("success_msg", msg)
            QMessageBox.information(self, self.loc['dialogs']['success'], final_msg)
            self.invalidate_items_snapshot()
            self._refresh_inventory_view(self.content_stack.currentIndex())
        except Exception as e:
            # Catch potential crashes from C-extensions and show an error dialog
            self.log(self.loc['dialogs']['update_error'].format(error=e), force_popup=True)

    def _live_update_item(self, payload: dict):
        """Online overwrite: apply the new serial to the live game item."""
        if self._live_any_busy():
            QMessageBox.warning(
                self, self._live_text('title', 'Live Mode'),
                self._live_text('runtime_busy', 'Another live action is still running.'),
            )
            return
        if not self._guard_live_inventory_mutation():
            return
        new_serial = (payload.get('new_item_data') or {}).get('serial', '')
        if not new_serial.startswith('@U'):
            QMessageBox.critical(
                self,
                self._live_text('title', 'Live Mode'),
                self._live_text('invalid_serial', 'Invalid serial: {serial}', serial=new_serial[:40]),
            )
            return
        # item_path ends with 'slot_<n>' -> backpack index n
        path = payload.get('item_path') or []
        idx = None
        for part in reversed(path):
            if isinstance(part, str) and part.startswith('slot_'):
                try:
                    idx = int(part.split('_', 1)[1])
                except ValueError:
                    idx = None
                break
        if idx is None:
            QMessageBox.critical(
                self,
                self._live_text('title', 'Live Mode'),
                self._live_text(
                    'slot_missing', 'Could not locate the inventory slot (item_path has no slot_N).'
                ),
            )
            return
        container = "BankItems" if any(p == "bank" for p in path) else "BackpackItems"

        self.log(self._live_text(
            'overwrite_started', 'Live overwrite: {container}[{slot}] -> {serial}...',
            container=container, slot=idx, serial=new_serial[:40],
        ))
        try:
            current_node = self.controller.get_node(path)
            old_serial = current_node.get('serial') if isinstance(current_node, dict) else None
            live_handle = (
                current_node.get('_live_handle') if isinstance(current_node, dict) else None
            )
            live_instance_id = (
                current_node.get('_live_instance_id') if isinstance(current_node, dict) else None
            )
            live_identity_supported = (
                current_node.get('_live_identity_supported')
                if isinstance(current_node, dict) else None
            )
        except Exception:
            old_serial = None
            live_handle = None
            live_instance_id = None
            live_identity_supported = None
        if not isinstance(old_serial, str) or not old_serial.startswith('@U'):
            self.log(self._live_text(
                'overwrite_source_missing',
                'The current live snapshot no longer has a valid source serial for this slot. Refresh and retry.',
            ), force_popup=True)
            return
        context = {
            'idx': idx,
            'container': container,
            'serial': new_serial,
            'old_serial': old_serial,
            'live_handle': live_handle,
            'live_instance_id': live_instance_id,
            'live_identity_supported': live_identity_supported,
            'item_path': list(path),
        }
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        worker = _LiveItemApplyWorker(self._live_bridge, context, parent=self)
        worker.completed.connect(self._on_live_item_apply_finished)
        self._live_runtime_worker = worker
        self._track_live_worker(worker)
        self._sync_live_action_buttons()
        worker.start()

    @pyqtSlot(object, object, object)
    def _on_live_item_apply_finished(self, context, result, err):
        worker = self.sender()
        if worker is not self._live_runtime_worker:
            return
        self._live_runtime_worker = None
        QApplication.restoreOverrideCursor()
        MainWindow._remember_live_inventory_recovery(self, result)
        self._sync_live_action_buttons()
        if not self._live_active:
            return

        context = dict(context or {})
        result = result if isinstance(result, dict) else {}
        applied = result.get('apply') if isinstance(result.get('apply'), dict) else {}
        cache = (
            result.get('cache_rebuild')
            if isinstance(result.get('cache_rebuild'), dict) else {}
        )
        if result.get('failed_stage') == 'recovery_gate':
            self.log(self._live_text(
                'inventory_mutation_recovery_pending',
                'Inventory writes are locked until the pending recovery is reviewed or cleared: {reason}',
                reason=result.get('error') or self._live_recovery_reason,
            ), force_popup=True)
            return
        persistent_ok = bool(applied.get('ok'))
        relocated = bool(context.get('relocated') or applied.get('relocated'))
        conflict = (
            str(applied.get('code') or '').startswith('optimistic_lock_')
            or str(applied.get('error') or '').strip().lower()
            == 'optimistic-lock mismatch'
        )
        if relocated or conflict:
            self._clear_live_item_editor_selection()
        refresh_needed = bool(err) or not persistent_ok or relocated
        if cache.get('supported') and not cache.get('ok'):
            refresh_needed = True

        idx = context.get('idx')
        actual_idx = context.get('actual_idx', idx)
        container = context.get('container')
        serial = context.get('applied_serial') or context.get('serial')
        coordinates_ok = (
            applied.get('container') == container
            and applied.get('idx') == actual_idx
        )
        if persistent_ok and not coordinates_ok:
            refresh_needed = True

        refresh_started = False
        if persistent_ok and not refresh_needed:
            expected = (
                {(container, idx): context.get('old_serial')}
                if context.get('old_serial') else None
            )
            refresh_started = not self._commit_live_inventory_patch(
                [{"container": container, "idx": idx, "serial": serial}],
                require_existing=True,
                expected_serials=expected,
            )
        if refresh_needed and not refresh_started:
            self._live_refresh()

        if not persistent_ok:
            error = err or applied.get('error') or 'invalid live apply response'
            if conflict:
                message = self._live_text(
                    'overwrite_conflict_refreshed',
                    'The target item changed or moved in the game. The live inventory was refreshed; reopen the item and retry.',
                )
                self.log(message)
                QMessageBox.warning(
                    self, self._live_text('title', 'Live Mode'), message,
                )
                return
            self.log(self._live_text(
                'overwrite_rejected' if applied else 'overwrite_failed',
                'The game rejected the live overwrite: {error}' if applied
                else 'Live overwrite failed: {error}',
                error=error,
            ), force_popup=True)
            return

        warn = ""
        if applied.get('missing_parts'):
            warn = "\n\n" + self._live_text(
                'missing_parts', 'Warning: {count} part(s) could not be mapped.',
                count=len(applied['missing_parts']),
            )
        message = self._live_text(
            'overwrite_persistent_success',
            'Slot {slot}: serial and part array verified.',
            slot=actual_idx,
        )
        if cache.get('skipped') == 'already_consistent':
            message += "\n" + self._live_text(
                'cache_rebuild_already_current',
                'The equipped runtime actor is already current; no rebuild was needed.',
            )
        elif cache.get('skipped'):
            message += "\n" + self._live_text(
                'cache_rebuild_not_needed',
                'The item is not equipped; no runtime actor rebuild was needed.',
            )
        elif err:
            message += "\n" + self._live_text(
                'cache_rebuild_failed',
                'Runtime cache rebuild was not verified: {error}. The live inventory was refreshed; reload if needed.',
                error=err,
            )
        elif cache.get('attempted') and cache.get('ok'):
            if cache.get('mode') == 'unequipped_backpack':
                message += "\n" + self._live_text(
                    'backpack_publication_success',
                    "The unequipped backpack item's full runtime identity was published and refreshed.",
                )
            else:
                message += "\n" + self._live_text(
                    'cache_rebuild_success',
                    'The equipped item full runtime identity and actor cache were rebuilt.',
                )
        elif cache.get('supported') or cache.get('error'):
            message += "\n" + self._live_text(
                'cache_rebuild_failed',
                'Runtime cache rebuild was not verified: {error}. The live inventory was refreshed; reload if needed.',
                error=cache.get('error') or 'unknown error',
            )
        elif cache.get('availability') == 'temporarily_unavailable':
            message += "\n" + self._live_text(
                'cache_rebuild_unavailable',
                'Immediate cache rebuilding is temporarily unavailable: {reason}. The persistent overwrite succeeded; reload if needed.',
                reason=cache.get('capability_reason') or 'runtime write path unavailable',
            )
        else:
            message += "\n" + self._live_text(
                'cache_rebuild_unsupported',
                'This live mod does not support immediate cache rebuilding; reload if needed.',
            )
        if cache.get('uncertain'):
            message += "\n" + self._live_text(
                'cache_rebuild_recovery',
                'The backend reported an uncertain transaction. Check the equipped item and review the recovery lock before another write.',
            )
            QMessageBox.warning(
                self, self._live_text('title', 'Live Mode'), message + warn,
            )
        else:
            QMessageBox.information(
                self, self._live_text('title', 'Live Mode'), message + warn,
            )

    @pyqtSlot(dict)
    def handle_character_update(self, data: dict):
        if not self.controller.yaml_obj: return
        paths = data.pop('cur_paths', {})
        if self.controller.apply_character_data(data, paths):
            QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['char_applied'])
            self.refresh_all_tabs()
        else:
            QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['char_apply_error'])

    @pyqtSlot()
    def handle_sync_levels(self):
        if not self.controller.yaml_obj: return
        reply = QMessageBox.question(self, self.loc['dialogs']['warning'], self.loc['dialogs']['confirm_sync'], QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success, fail, info = self.controller.sync_inventory_levels()
            msg = self.loc['dialogs']['sync_msg'].format(success=success, fail=fail)
            if fail > 0:
                details = '\n'.join(info)
                QMessageBox.warning(self, self.loc['dialogs']['sync_partial'], f"{msg}{self.loc['dialogs']['sync_fail_details'].format(details=details)}")
            else:
                QMessageBox.information(self, self.loc['dialogs']['sync_title'], msg)
            
            if success > 0: self.refresh_all_tabs()

    @pyqtSlot(str, dict)
    def handle_unlock_request(self, preset_name: str, params: dict):
        if not self.controller.yaml_obj: 
            QMessageBox.warning(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['load_save_first'])
            return
        
        # Ask for confirmation? Maybe not for all, but "unlock_max_everything" is big.
        # For now, direct apply as in original tool.
        
        if self.controller.apply_unlock_preset(preset_name, params):
            QMessageBox.information(self, self.loc['dialogs']['success'], self.loc['dialogs']['preset_applied'].format(name=preset_name))
            self.refresh_all_tabs()
        else:
            QMessageBox.critical(self, self.loc['dialogs']['error'], self.loc['dialogs']['preset_fail'].format(name=preset_name))

    @pyqtSlot(str)
    def handle_yaml_update(self, yaml_string: str):
        """源码编辑回写：只更新对象 + 轻量刷新，不再全量刷新所有 tab。"""
        if self.controller.update_yaml_object(yaml_string):
            self.invalidate_items_snapshot()
            try:
                character_tab = self._loaded_tab('character')
                if character_tab is not None:
                    self._character_data = self.controller.get_character_data()
                    character_tab.update_fields(self._character_data)
            except Exception:
                pass
            self._refresh_inventory_view(self.content_stack.currentIndex())

    @pyqtSlot()
    def handle_yaml_structure_changed(self):
        """YAML 树编辑后的联动：失效物品快照 + 轻量刷新当前视图。"""
        self.invalidate_items_snapshot()
        try:
            character_tab = self._loaded_tab('character')
            if character_tab is not None:
                self._character_data = self.controller.get_character_data()
                character_tab.update_fields(self._character_data)
        except Exception:
            pass
        self._refresh_inventory_view(self.content_stack.currentIndex())

    @pyqtSlot(dict)
    def handle_open_item_from_yaml(self, item: dict):
        """从 YAML 编辑器跳转：按物品类型路由到对应编辑器 tab，失败回退物品总览。"""
        if not item:
            return
        from core.item_display_resolver import WEAPON_TYPES
        type_en = (item.get('type_en') or '').strip()
        route = {
            'Heavy Weapon': 'heavy_weapon_tab',
            'Shield': 'shield_tab',
            'Grenade': 'grenade_tab',
            'Repkit': 'repkit_tab',
            'Class Mod': 'class_mod_tab',
            'Enhancement': 'enhancement_tab',
        }
        try:
            if type_en in WEAPON_TYPES:
                weapon_tab = self._ensure_tab('weapon_editor')
                weapon_tab.refresh_backpack_items(self.get_items_snapshot())
                self._dirty_item_views.discard("weapon")
                self._switch_to_widget(weapon_tab)
                weapon_tab.load_weapon_data(item)
                return
            key_by_attr = {attr: key for key, (attr, *_rest) in self._lazy_tab_specs.items()}
            target_attr = route.get(type_en, '')
            tab = self._ensure_tab(key_by_attr[target_attr]) if target_attr in key_by_attr else None
            if tab is not None and hasattr(tab, 'open_item_serial'):
                self._switch_to_widget(tab)
                tab.open_item_serial(item)
                return
        except Exception as e:
            self.log(f"Open item in editor failed, fallback to items tab: {e}")
        # 回退：物品总览页选中
        items_tab = self._ensure_tab('items')
        items_tab.update_tree(self.get_items_snapshot())
        self._dirty_item_views.discard("items")
        self._switch_to_widget(items_tab)
        if not items_tab.select_item_by_path(item.get("original_path")):
            QMessageBox.warning(
                self,
                self.loc.get('dialogs', {}).get('warning', "Warning"),
                self.loc['status'].get('item_not_found', "未找到对应物品"),
            )

    @pyqtSlot(dict)
    def handle_open_generated_weapon(self, result: dict):
        """Open a detached God Roll result in Weapon Editor without overwriting an item."""
        if not isinstance(result, dict) or not result.get("serial"):
            return
        try:
            weapon_tab = self._ensure_tab('weapon_editor')
            self._switch_to_widget(weapon_tab)
            weapon_tab.load_weapon_data({
                "serial": result.get("serial", ""),
                "decoded_full": result.get("decoded", ""),
                "name": result.get("name", ""),
                "type_en": result.get("weapon_type_key") or result.get("weapon_type", ""),
                "manufacturer_en": result.get("manufacturer_key") or result.get("manufacturer", ""),
                "rarity": result.get("rarity_key") or result.get("rarity", ""),
                "level": result.get("level", ""),
                "original_path": None,
            })
            if hasattr(weapon_tab, "update_weapon_btn"):
                weapon_tab.update_weapon_btn.setEnabled(False)
        except Exception as exc:
            self.log(f"Open God Roll result in weapon editor failed: {exc}")
            QMessageBox.warning(
                self,
                self.loc.get('dialogs', {}).get('warning', "Warning"),
                str(exc),
            )

    def _switch_to_widget(self, widget):
        index = self.content_stack.indexOf(widget)
        if index >= 0:
            self.switch_to_tab(index)


    @pyqtSlot(list, str)
    def handle_batch_add(self, lines: list, flag: str):
        if not self.controller.yaml_obj:
            QMessageBox.critical(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['decrypt_save_first'])
            self.converter_tab.finalize_batch_add(0, 0)
            return
        started = self._start_batch_add_worker(
            lines, flag, self.converter_tab.update_batch_add_status, self.on_batch_add_finished
        )
        if started is False:
            self.converter_tab.finalize_batch_add(0, 0)
            QMessageBox.warning(
                self,
                self.loc['dialogs']['warning'],
                self.loc['dialogs'].get(
                    'batch_busy', 'Another batch-add task is already running.'
                ),
            )

    def _start_batch_add_worker(self, lines, flag, progress_slot, finished_slot):
        if getattr(self, '_batch_add_active', False):
            return False
        current_thread = getattr(self, 'batch_add_thread', None)
        try:
            if current_thread is not None and current_thread.isRunning():
                return False
        except RuntimeError:
            # The previous Qt wrapper may already be scheduled for deletion.
            pass
        self.batch_add_thread = QThread()
        self.batch_add_worker = BatchAddWorker(self.controller, lines, flag)
        self.batch_add_worker.moveToThread(self.batch_add_thread)

        self.batch_add_thread.started.connect(self.batch_add_worker.run)
        self.batch_add_worker.finished.connect(finished_slot)
        self.batch_add_worker.progress.connect(progress_slot)

        self.batch_add_worker.finished.connect(self.batch_add_thread.quit)
        self.batch_add_worker.finished.connect(self.batch_add_worker.deleteLater)
        self.batch_add_thread.finished.connect(self.batch_add_thread.deleteLater)

        self._suspend_autosave(True)
        self._batch_add_active = True
        self.batch_add_thread.start()
        return True

    @pyqtSlot(list, str)
    def handle_roll_batch_add(self, lines: list, flag: str):
        source_tab = self.sender()
        if not hasattr(source_tab, 'finalize_roll_batch_add'):
            return
        if getattr(self, '_live_active', False) and getattr(self, '_live_bridge', None) is not None:
            busy_check = getattr(self, '_live_any_busy', None)
            if callable(busy_check) and busy_check():
                message = self.loc['dialogs'].get(
                    'batch_busy', 'Another batch-add task is already running.'
                )
                source_tab.reject_roll_batch_add(message)
                QMessageBox.warning(self, self.loc['dialogs']['warning'], message)
                return
            guard = getattr(self, '_guard_live_inventory_mutation', None)
            if callable(guard):
                def reject_recovery(message):
                    source_tab.reject_roll_batch_add(message)
                    QMessageBox.warning(self, self.loc['dialogs']['warning'], message)
                if not guard(reject_recovery):
                    return
            self._roll_batch_source_tab = source_tab
            self._batch_add_active = True
            worker = _LiveBatchSpawnWorker(self._live_bridge, lines, self)
            worker.progress.connect(source_tab.update_roll_add_progress)
            worker.batch_finished.connect(self._on_live_roll_batch_finished)
            self._live_batch_spawn_worker = worker
            track_worker = getattr(self, '_track_live_worker', None)
            if callable(track_worker):
                track_worker(worker)
            sync_buttons = getattr(self, '_sync_live_action_buttons', None)
            if callable(sync_buttons):
                sync_buttons()
            worker.start()
            return
        if not self.controller.yaml_obj:
            QMessageBox.critical(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['decrypt_save_first'])
            source_tab.finalize_roll_batch_add(0, len(lines))
            return
        started = self._start_batch_add_worker(
            lines,
            flag,
            source_tab.update_roll_add_progress,
            self.on_roll_batch_add_finished,
        )
        if started is False:
            message = self.loc['dialogs'].get(
                'batch_busy', 'Another batch-add task is already running.'
            )
            source_tab.reject_roll_batch_add(message)
            QMessageBox.warning(self, self.loc['dialogs']['warning'], message)
            return
        self._roll_batch_source_tab = source_tab

    def _on_live_roll_batch_finished(self, success_count, fail_count):
        self._batch_add_active = False
        source_tab = getattr(self, '_roll_batch_source_tab', None)
        self._roll_batch_source_tab = None
        worker = self._live_batch_spawn_worker
        MainWindow._remember_live_inventory_recovery(self,
            getattr(worker, 'mutation_preflight', None)
        )
        MainWindow._remember_live_inventory_recovery(self,
            getattr(worker, 'mutation_results', None)
        )
        self._live_batch_spawn_worker = None
        self._sync_live_action_buttons()
        if source_tab is not None:
            if worker is not None and worker.blocked_reason:
                message = self._live_text(
                    'inventory_mutation_recovery_pending',
                    'Inventory writes are locked until the pending recovery is reviewed or cleared: {reason}',
                    reason=worker.blocked_reason,
                )
                source_tab.reject_roll_batch_add(message)
                QMessageBox.warning(self, self.loc['dialogs']['warning'], message)
            else:
                source_tab.finalize_roll_batch_add(success_count, fail_count)
        if success_count > 0:
            if (
                worker is not None
                and worker.incremental_safe
                and len(worker.spawned_records) == success_count
            ):
                self._commit_live_inventory_patch(worker.spawned_records)
            else:
                self._live_refresh()

    def on_roll_batch_add_finished(self, success_count, fail_count):
        self._batch_add_active = False
        self._suspend_autosave(False)
        source_tab = getattr(self, '_roll_batch_source_tab', None)
        self._roll_batch_source_tab = None
        if source_tab is not None:
            source_tab.finalize_roll_batch_add(success_count, fail_count)
        if success_count > 0:
            self.invalidate_items_snapshot()
            self._refresh_inventory_view(self.content_stack.currentIndex())

    def on_batch_add_finished(self, success_count, fail_count):
        self._batch_add_active = False
        self._suspend_autosave(False)
        self.converter_tab.finalize_batch_add(success_count, fail_count)
        if success_count > 0:
            QMessageBox.information(self, self.loc['dialogs']['batch_complete'], 
                                    self.loc['dialogs']['batch_success'].format(count=success_count))
            self.refresh_all_tabs()
        else:
            QMessageBox.warning(self, self.loc['dialogs']['batch_fail'], 
                                self.loc['dialogs']['batch_fail_msg'].format(count=fail_count))

    def _start_iterator_worker(self, params, add_to_backpack=False):
        if not self.controller.yaml_obj and add_to_backpack:
            QMessageBox.critical(self, self.loc['dialogs']['no_save'], self.loc['dialogs']['decrypt_save_first'])
            self.converter_tab.finalize_iterator_add_to_backpack(0,0)
            return

        params['add_to_backpack'] = add_to_backpack
        self.iterator_thread = QThread()
        self.iterator_worker = IteratorWorker(self.controller, params, self.loc['worker'])
        self.iterator_worker.moveToThread(self.iterator_thread)

        self.iterator_thread.started.connect(self.iterator_worker.run)
        self.iterator_worker.status_update.connect(self.converter_tab.update_iterator_status)

        if add_to_backpack:
            self._suspend_autosave(True)

        if add_to_backpack:
            self.iterator_worker.finished_add_to_backpack.connect(self.on_iterator_add_finished)
        else:
            self.iterator_worker.finished_generation.connect(self.converter_tab.finalize_iterator_processing)

        self.iterator_worker.finished_generation.connect(self.iterator_thread.quit)
        self.iterator_worker.finished_add_to_backpack.connect(self.iterator_thread.quit)
        self.iterator_worker.finished_generation.connect(self.iterator_worker.deleteLater)
        self.iterator_worker.finished_add_to_backpack.connect(self.iterator_worker.deleteLater)
        self.iterator_thread.finished.connect(self.iterator_thread.deleteLater)
        
        self.iterator_thread.start()

    @pyqtSlot(dict)
    def handle_iterator_request(self, params: dict):
        self._start_iterator_worker(params, add_to_backpack=False)

    @pyqtSlot(dict)
    def handle_iterator_add_to_backpack(self, params: dict):
        self._start_iterator_worker(params, add_to_backpack=True)

    def on_iterator_add_finished(self, success, fail):
        self._suspend_autosave(False)
        self.converter_tab.finalize_iterator_add_to_backpack(success, fail)
        if success > 0:
            QMessageBox.information(self, self.loc['dialogs']['iter_complete'], 
                                    self.loc['dialogs']['iter_success'].format(count=success))
            self.refresh_all_tabs()
        else:
            QMessageBox.warning(self, self.loc['dialogs']['iter_fail'], 
                                self.loc['dialogs']['iter_fail_msg'].format(count=fail))
            
    @pyqtSlot(bool)
    def encrypt_and_save(self, save_as=False):
        if self.controller.yaml_obj is None: return

        original_save_path = self.controller.save_path
        path_to_save = original_save_path
        if save_as or not path_to_save:
            path, _ = QFileDialog.getSaveFileName(
                self,
                self.loc['dialogs']['save_encrypted_title'],
                str(path_to_save),
                self.loc['dialogs'].get('save_filter', "Borderlands 4 Saves (*.sav);;All Files (*.*)"),
            )
            if not path: return
            path_to_save = Path(path)

        try:
            # 原子写入（临时文件 + os.replace，旧文件轮转为 .prev.bak）
            saved_path = self.controller.save_to_disk(path_to_save)
            if save_as or original_save_path is None:
                self._remove_recovery(original_save_path)
                self.controller.save_path = saved_path
                self.setWindowTitle(f"{self.loc['window_title']} V{VERSION} - {saved_path.name}")
            self._autosave_timer.stop()
            self._recover_timer.stop()
            self._remove_recovery()
            self._set_autosave_indicator("", False)
            QMessageBox.information(self, self.loc['dialogs']['success'],
                                    self.loc['dialogs']['save_saved'].format(path=saved_path))
        except Exception as e:
            QMessageBox.critical(self, self.loc['dialogs']['encrypt_failed'], str(e))

    def _get_lang_button_text(self):
        code_map = {
            'zh-CN': "CN",
            'en-US': "EN",
            'ru': "RU",
            'ua': "UA"
        }
        return f"🌐 {code_map.get(self.current_language, 'EN')}"

    def change_language(self, lang_code):
        if self.current_language == lang_code:
            return

        self.current_language = lang_code
        self._settings.setValue('language', lang_code)
        
        # Update backend localization
        bl4f.set_language(self.current_language)
        self.invalidate_items_snapshot()

        self.lang_button.setText(self._get_lang_button_text())
        
        self._load_localization()
        self.update_ui_text()
        
        # Update tabs
        for tab in self._all_content_tabs():
            if hasattr(tab, 'update_language'):
                try:
                    tab.update_language(self.current_language)
                except Exception as e:
                    print(f"Warning: failed to update {tab.__class__.__name__} language: {e}")
        if self._live_active:
            self._apply_live_ui_state()
        
        # Refresh all tabs to re-fetch items with new localization
        self.refresh_all_tabs(invalidate_items=False)
        
    def update_ui_text(self):
        if self._live_active:
            self.setWindowTitle(
                f"{self.loc['window_title']} V{VERSION} - [{self._live_text('online', 'Online')}]"
            )
        elif getattr(self.controller, 'save_path', None):
            self.setWindowTitle(f"{self.loc['window_title']} V{VERSION} - {self.controller.save_path.name}")
        else:
            self.setWindowTitle(f"{self.loc['window_title']} V{VERSION}")
        self.header_bar.findChild(QLabel, "titleLabel").setText(self.loc['header']['title'])
        self.header_bar.findChild(QLabel, "subtitleLabel").setText(self.loc['subtitle'])
        self.open_button.setText(self.loc['header']['open'])
        self.save_button.setText(self.loc['header']['save'])
        self.save_as_button.setText(self.loc['header']['save_as'])
        self.open_action.setText(self.loc['menu']['open_selector'])
        self.save_action.setText(self.loc['menu']['save'])
        self.save_as_action.setText(self.loc['menu']['save_as'])
        if hasattr(self, 'autosave_checkbox'):
            self._autosave_status_message = (
                self.loc['status'].get('autosave_failed', "自动保存失败，请手动保存")
                if self._autosave_status_failed else ""
            )
            self._set_autosave_indicator()
        self.lang_button.setText(self._get_lang_button_text())
        self._update_live_header_text()
        # Update tooltips for theme and background buttons
        self.theme_button.setToolTip(self._get_theme_tooltip())
        self.bg_button.setToolTip(self.loc.get('header', {}).get('change_bg', 'Change Background'))
        
        # Update tab titles
        # Order must match the add_tab() call order in _add_tabs(); index i is
        # looked up directly in nav_button_group.
        tab_keys = [
            'select_save', 'character', 'items', 'serial_inspector',
            'yaml_editor', 'class_mod', 'enhancement', 'weapon_editor', 'weapon_generator', 'god_roll',
            'grenade', 'shield', 'repkit', 'heavy_weapon', 'loadout_manager', 'converter'
        ]

        for i, key in enumerate(tab_keys):
            button = self.nav_button_group.button(i)
            if button:
                icon_char = button.property("iconChar")
                label = self.loc['tabs'][key]
                new_full_text = f"{icon_char}  {label}"
                button.setProperty("fullText", new_full_text)
                button.setProperty("navLabel", label)
                button.setToolTip(label)
                button.setAccessibleName(label)

        self._refresh_nav_bar()

    def _apply_themed_stylesheet(self):
        """Apply the themed stylesheet from ThemeManager."""
        stylesheet = self.theme_manager.get_stylesheet()
        if stylesheet:
            self.setStyleSheet(stylesheet)
            if hasattr(self, 'nav_button_group'):
                self._refresh_nav_bar()
        else:
            print("Warning: stylesheet.qss not found or failed to load.")

    def toggle_theme(self):
        """Toggle between dark and light themes."""
        self.theme_manager.toggle_theme()
        self._apply_themed_stylesheet()
        self._update_theme_button()
        yaml_tab = self._loaded_tab('yaml_editor')
        if yaml_tab is not None:
            yaml_tab.apply_theme(self.theme_manager.is_dark())

    def _get_theme_tooltip(self):
        """Get the tooltip text for the theme button."""
        if self.theme_manager.is_dark():
            return self.loc.get('header', {}).get('theme_light', 'Switch to Light Mode')
        else:
            return self.loc.get('header', {}).get('theme_dark', 'Switch to Dark Mode')

    def _update_theme_button(self):
        """Update the theme button icon and tooltip."""
        self.theme_button.setText(self.theme_manager.get_theme_icon())
        self.theme_button.setToolTip(self._get_theme_tooltip())

def main():
    app = QApplication(sys.argv)
    icon_path = resource_loader.get_resource_path("assets/BL4.ico")
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
