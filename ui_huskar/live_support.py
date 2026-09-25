"""live 联机管理器：移植 main_window 的全部 live 编排逻辑。

worker 类直接复用 main_window（_LiveFetchWorker / _LiveRuntimeWorker /
_LiveItemApplyWorker / _LiveLoadoutWorker / _LiveBatchSpawnWorker），
本类负责进入/退出/刷新、恢复锁状态机、写操作路由（spawn/update/批量）、
运行时动作与配装快照/应用/恢复，反馈经 AppBridge.toast 与 VM 回调给出。
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QObject, QTimer

from core import b_encoder, bl4_functions as bl4f, resource_loader
from main_window import (
    _LIVE_INVENTORY_MUTATION_ACTIONS,
    _LiveBatchSpawnWorker,
    _LiveFetchWorker,
    _LiveItemApplyWorker,
    _LiveLoadoutWorker,
    _LiveRuntimeWorker,
    _live_inventory_mutation_preflight,
    _live_inventory_recovery_state,
)


class LiveManager(QObject):
    """AppBridge 的 live 子系统（controller-first 复刻 main_window 行为）。"""

    def __init__(self, app, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.app = app
        self.active = False
        self.connecting = False
        self.bridge = None
        self.recovery_pending: bool | None = None
        self.recovery_reason = ""
        # 最近一次 runtime 响应里的 state（position / currencies / ...），供各页面只读取用
        self.runtime_state: dict = {}
        self._fetch_thread = None
        self._runtime_worker = None
        self._batch_spawn_worker = None
        self._workers: set = set()
        self._watchdog: QTimer | None = None

    # ------------------------------------------------------------------ #
    # 本地化 / 反馈
    # ------------------------------------------------------------------ #
    def _text(self, key: str, fallback: str, **values) -> str:
        text = self.app.localizer.section("main_window").get("live", {}).get(key, fallback)
        return text.format(**values) if values else text

    def _toast(self, text: str, kind: str = "info") -> None:
        self.app.toast(text, kind)

    def _character_vm(self):
        return self.app.vm("character")

    def _loadout_vm(self):
        return self.app.vm("loadout_manager")

    def _sync_vms(self) -> None:
        busy = self.any_busy()
        recovery = self.recovery_pending is True
        vm = self._character_vm()
        if vm is not None:
            vm.set_runtime_busy(busy)
            vm.set_inventory_mutation_blocked(recovery)
        loadout = self._loadout_vm()
        if loadout is not None:
            loadout.set_live_busy(busy)
            loadout.set_inventory_mutation_blocked(recovery)
        self.app.liveChanged.emit()

    def _refresh_all(self) -> None:
        self.app._mark_all_stale()
        current = self.app._vms.get(self.app.pageKey)
        if current is not None:
            current.on_activated()
        self.app.saveStateChanged.emit()
        self._sync_vms()

    # ------------------------------------------------------------------ #
    # worker 管理
    # ------------------------------------------------------------------ #
    def _track(self, worker) -> None:
        self._workers.add(worker)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.finished.connect(worker.deleteLater)

    def _on_worker_finished(self, worker) -> None:
        self._workers.discard(worker)
        if self._fetch_thread is worker:
            self._fetch_thread = None
        if self._runtime_worker is worker:
            self._runtime_worker = None
        if self._batch_spawn_worker is worker:
            self._batch_spawn_worker = None
        self._sync_vms()

    def any_busy(self) -> bool:
        fetch_busy = self._fetch_thread is not None
        runtime_busy = self._runtime_worker is not None
        batch_busy = self._batch_spawn_worker is not None and self._batch_spawn_worker.isRunning()
        return fetch_busy or runtime_busy or batch_busy

    def _start_watchdog(self) -> None:
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_timeout)
        self._watchdog.start(15000)

    def _stop_watchdog(self) -> None:
        if self._watchdog is not None:
            self._watchdog.stop()

    def _on_timeout(self) -> None:
        self.connecting = False
        self._sync_vms()
        self._toast(self._text("timeout",
                               "Live fetch timed out after 15 seconds. The game or bl4_live may not be running."),
                    "error")

    # ------------------------------------------------------------------ #
    # 恢复锁
    # ------------------------------------------------------------------ #
    def _remember_recovery(self, source) -> None:
        pending, reason = _live_inventory_recovery_state(source)
        if pending is not True and pending is not False:
            return
        self.recovery_pending = pending
        self.recovery_reason = str(reason or "") if pending else ""
        self._sync_vms()

    def _guard_mutation(self, reject=None) -> bool:
        if self.recovery_pending is not True:
            return True
        reason = str(self.recovery_reason or self._text(
            "inventory_recovery_reason", "unresolved loadout recovery requires review"))
        message = self._text(
            "inventory_mutation_recovery_pending",
            "Inventory writes are locked until the pending recovery is reviewed or cleared: {reason}",
            reason=reason)
        if callable(reject):
            reject(message)
        else:
            self._toast(message, "warning")
        return False

    # ------------------------------------------------------------------ #
    # 进入 / 退出 / 刷新
    # ------------------------------------------------------------------ #
    def toggle(self) -> None:
        if not self.active:
            self.enter()
        else:
            self.exit()

    def enter(self) -> None:
        controller = self.app.controller
        if controller.dirty and controller.yaml_obj is not None:
            self._toast(self._text(
                "unsaved_changes_blocked",
                "Save or discard the current offline changes before entering live mode."), "warning")
            return
        if self.any_busy():
            self._toast(self._text("runtime_busy", "Another live action is still running."), "warning")
            return
        try:
            from live.bridge import Bridge  # noqa
            from live.adapter import fetch_live_yaml  # noqa
        except Exception as exc:
            self._toast(self._text("unavailable", "Live mode is unavailable (live/ package): {error}",
                                   error=exc), "error")
            return

        self.bridge = Bridge()
        self.recovery_pending = None
        self.recovery_reason = ""
        if not self.bridge.ping():
            self.bridge = None
            self._toast(self._text(
                "connection_failed",
                "Could not connect to the game (127.0.0.1:28777).\n"
                "Make sure the game is running, a character is loaded, and the bl4_live mod is active."),
                "warning")
            return
        try:
            live_info = self.bridge.info()
            from live.bridge import EXPECTED_LIVE_VERSION
            live_version = str(live_info.get("version") or "").strip()
            if live_version != EXPECTED_LIVE_VERSION:
                self.bridge = None
                self._toast(self._text(
                    "version_mismatch",
                    "bl4_live version mismatch: editor expects {expected}, game reports {actual}.\n"
                    "Install the matching bl4_live package for this game build.",
                    expected=EXPECTED_LIVE_VERSION, actual=live_version or "unknown"), "warning")
                return
        except Exception as exc:
            self.bridge = None
            self._toast(self._text("version_check_failed",
                                   "Could not verify bl4_live compatibility: {error}", error=exc),
                        "warning")
            return

        self.connecting = True
        self._sync_vms()
        self._start_watchdog()
        worker = _LiveFetchWorker(self.bridge, self)
        worker.loaded.connect(self._on_loaded)
        self._fetch_thread = worker
        self._track(worker)
        worker.start()

    def _on_loaded(self, yaml_like, err) -> None:
        worker = self.sender()
        if worker is not self._fetch_thread:
            return
        self._fetch_thread = None
        self._stop_watchdog()
        self.connecting = False
        if err is not None or yaml_like is None:
            self.bridge = None
            self._sync_vms()
            self._toast(self._text("fetch_failed", "Live fetch failed: {error}", error=err), "error")
            return

        self.active = True
        self.runtime_state = {}
        controller = self.app.controller
        controller.yaml_obj = yaml_like
        controller.save_path = None
        controller.mark_clean()
        self.app.set_status(self._text("synced", "Live backpack and bank items synchronized."))
        self._refresh_all()
        self.runtime_action("state", {"_quiet": True})

    def refresh(self) -> None:
        if not self.active or self.bridge is None or self.any_busy():
            return
        self._start_watchdog()
        worker = _LiveFetchWorker(self.bridge, self)
        worker.loaded.connect(self._on_refreshed)
        self._fetch_thread = worker
        self._track(worker)
        self._sync_vms()
        worker.start()

    def _on_refreshed(self, yaml_like, err) -> None:
        worker = self.sender()
        if worker is not self._fetch_thread:
            return
        self._fetch_thread = None
        self._stop_watchdog()
        if not self.active:
            return
        if err is not None or yaml_like is None:
            self._sync_vms()
            self._toast(self._text("refresh_failed", "Live refresh failed: {error}", error=err), "error")
            return
        self._clear_editor_selection()
        self.app.controller.yaml_obj = yaml_like
        self.app.controller.mark_clean()
        self.app.set_status(self._text("refreshed", "Live items refreshed."))
        self._refresh_all()
        self.runtime_action("state", {"_quiet": True})

    def exit(self) -> None:
        if self.any_busy():
            vm = self._character_vm()
            if vm is not None:
                vm.set_runtime_result(
                    self._text("runtime_busy", "Another live action is still running."), False)
            return
        self.active = False
        self.connecting = False
        self.bridge = None
        self.runtime_state = {}
        self.recovery_pending = None
        self.recovery_reason = ""
        controller = self.app.controller
        controller.yaml_obj = None
        controller.save_path = None
        controller.mark_clean()
        loadout = self._loadout_vm()
        if loadout is not None:
            loadout.set_data(None, None)
        self.app.set_status(self._text("exited", "Live mode exited."))
        self._refresh_all()
        self.app.navigate("select_save")

    def _clear_editor_selection(self) -> None:
        vm = self.app.vm("weapon_editor")
        if vm is not None and vm.selected_weapon_path is not None:
            vm.clear_all_fields()

    def _apply_ui_state(self) -> None:
        vm = self._character_vm()
        loadout = self._loadout_vm()
        if vm is not None:
            vm.set_inventory_mutation_blocked(self.recovery_pending is True)
        if loadout is not None:
            loadout.set_live_mode(self.active)
            loadout.set_inventory_mutation_blocked(self.recovery_pending is True)
        self._sync_vms()

    # ------------------------------------------------------------------ #
    # 增量补丁
    # ------------------------------------------------------------------ #
    def _commit_inventory_patch(self, records, *, require_existing=False, expected_serials=None) -> bool:
        from live.adapter import patch_live_yaml_items

        records = list(records or [])
        paths = patch_live_yaml_items(
            self.app.controller.yaml_obj,
            records,
            require_existing=require_existing,
            expected_serials=expected_serials,
        )
        if paths is None:
            self.refresh()
            return False
        self.app.controller.mark_clean()
        self._refresh_all()
        return True

    # ------------------------------------------------------------------ #
    # 写操作：单件添加 / 批量（roll）
    # ------------------------------------------------------------------ #
    def add_to_backpack(self, serial_input: str) -> bool:
        if self.any_busy():
            self._toast(self._text("runtime_busy", "Another live action is still running."), "warning")
            return False
        if not self._guard_mutation():
            return False
        preflight = _live_inventory_mutation_preflight(self.bridge)
        self._remember_recovery(preflight)
        if preflight["blocked"]:
            self._guard_mutation()
            return False
        try:
            serial_input = serial_input.strip()
            if serial_input.startswith("@U"):
                final_serial = serial_input
            else:
                encoded_serial, err = b_encoder.encode_to_base85(serial_input)
                if err:
                    self._toast(self.app.tr("main_window.dialogs.encode_failed_msg", error=err), "error")
                    return False
                final_serial = encoded_serial
        except Exception as exc:
            self._toast(self._text("add_encode_failed", "Failed to encode the live item: {error}",
                                   error=exc), "error")
            return False

        try:
            res = self.bridge.spawn(final_serial, "BackpackItems")
        except Exception as exc:
            self._toast(self._text("spawn_failed", "Live item spawn failed: {error}",
                                   error=f"{type(exc).__name__}: {exc}"), "error")
            return False
        self._remember_recovery(res)

        if res.get("ok"):
            self._toast(self._text("spawn_success", "A new item was spawned into the game backpack."),
                        "success")
            spawned = res.get("items")
            if isinstance(spawned, list) and len(spawned) == 1:
                record = dict(spawned[0])
                record["container"] = "BackpackItems"
                record["idx"] = record.get("index")
                self._commit_inventory_patch([record])
            else:
                self.refresh()
            return True
        self._toast(self._text("spawn_rejected", "The game rejected the live item spawn: {error}",
                               error=res.get("error")), "error")
        return False

    def batch_spawn(self, lines: list[str], on_finished) -> None:
        """批量 roll 写入（live）：callback(success, fail)。"""
        worker = _LiveBatchSpawnWorker(self.bridge, lines, self)
        worker.progress.connect(lambda *_args: None)
        worker.batch_finished.connect(lambda s, f: on_finished(s, f, worker))
        self._batch_spawn_worker = worker
        self._track(worker)
        self._sync_vms()
        worker.start()

    # ------------------------------------------------------------------ #
    # 写操作：更新物品
    # ------------------------------------------------------------------ #
    def update_item(self, payload: dict) -> bool:
        if self.any_busy():
            self._toast(self._text("runtime_busy", "Another live action is still running."), "warning")
            return False
        if not self._guard_mutation():
            return False
        new_serial = (payload.get("new_item_data") or {}).get("serial", "")
        if not new_serial.startswith("@U"):
            self._toast(self._text("invalid_serial", "Invalid serial: {serial}",
                                   serial=new_serial[:40]), "error")
            return False
        path = payload.get("item_path") or []
        idx = None
        for part in reversed(path):
            if isinstance(part, str) and part.startswith("slot_"):
                try:
                    idx = int(part.split("_", 1)[1])
                except ValueError:
                    idx = None
                break
        if idx is None:
            self._toast(self._text(
                "slot_missing", "Could not locate the inventory slot (item_path has no slot_N)."),
                "error")
            return False
        container = "BankItems" if any(p == "bank" for p in path) else "BackpackItems"

        self.app.set_status(self._text(
            "overwrite_started", "Live overwrite: {container}[{slot}] -> {serial}...",
            container=container, slot=idx, serial=new_serial[:40]))
        try:
            current_node = self.app.controller.get_node(path)
            old_serial = current_node.get("serial") if isinstance(current_node, dict) else None
            live_handle = current_node.get("_live_handle") if isinstance(current_node, dict) else None
            live_instance_id = (
                current_node.get("_live_instance_id") if isinstance(current_node, dict) else None)
            live_identity_supported = (
                current_node.get("_live_identity_supported") if isinstance(current_node, dict) else None)
        except Exception:
            old_serial = live_handle = live_instance_id = live_identity_supported = None
        if not isinstance(old_serial, str) or not old_serial.startswith("@U"):
            self._toast(self._text(
                "overwrite_source_missing",
                "The current live snapshot no longer has a valid source serial for this slot. Refresh and retry."),
                "error")
            return False
        context = {
            "idx": idx,
            "container": container,
            "serial": new_serial,
            "old_serial": old_serial,
            "live_handle": live_handle,
            "live_instance_id": live_instance_id,
            "live_identity_supported": live_identity_supported,
            "item_path": list(path),
        }
        worker = _LiveItemApplyWorker(self.bridge, context, self)
        worker.completed.connect(self._on_item_apply_finished)
        self._runtime_worker = worker
        self._track(worker)
        self._sync_vms()
        worker.start()
        return True

    def _on_item_apply_finished(self, context, result, err) -> None:
        worker = self.sender()
        if worker is not self._runtime_worker:
            return
        self._runtime_worker = None
        self._remember_recovery(result)
        self._sync_vms()
        if not self.active:
            return

        context = dict(context or {})
        result = result if isinstance(result, dict) else {}
        applied = result.get("apply") if isinstance(result.get("apply"), dict) else {}
        cache = result.get("cache_rebuild") if isinstance(result.get("cache_rebuild"), dict) else {}
        if result.get("failed_stage") == "recovery_gate":
            self._toast(self._text(
                "inventory_mutation_recovery_pending",
                "Inventory writes are locked until the pending recovery is reviewed or cleared: {reason}",
                reason=result.get("error") or self.recovery_reason), "error")
            return
        persistent_ok = bool(applied.get("ok"))
        relocated = bool(context.get("relocated") or applied.get("relocated"))
        conflict = (
            str(applied.get("code") or "").startswith("optimistic_lock_")
            or str(applied.get("error") or "").strip().lower() == "optimistic-lock mismatch"
        )
        if relocated or conflict:
            self._clear_editor_selection()
        refresh_needed = bool(err) or not persistent_ok or relocated
        if cache.get("supported") and not cache.get("ok"):
            refresh_needed = True

        idx = context.get("idx")
        actual_idx = context.get("actual_idx", idx)
        container = context.get("container")
        serial = context.get("applied_serial") or context.get("serial")
        coordinates_ok = applied.get("container") == container and applied.get("idx") == actual_idx
        if persistent_ok and not coordinates_ok:
            refresh_needed = True

        refresh_started = False
        if persistent_ok and not refresh_needed:
            expected = (
                {(container, idx): context.get("old_serial")}
                if context.get("old_serial") else None
            )
            refresh_started = not self._commit_inventory_patch(
                [{"container": container, "idx": idx, "serial": serial}],
                require_existing=True,
                expected_serials=expected,
            )
        if refresh_needed and not refresh_started:
            self.refresh()

        if not persistent_ok:
            error = err or applied.get("error") or "invalid live apply response"
            if conflict:
                self._toast(self._text(
                    "overwrite_conflict_refreshed",
                    "The target item changed or moved in the game. The live inventory was refreshed; reopen the item and retry."),
                    "warning")
                return
            self._toast(self._text(
                "overwrite_rejected" if applied else "overwrite_failed",
                "The game rejected the live overwrite: {error}" if applied
                else "Live overwrite failed: {error}",
                error=error), "error")
            return

        warn = ""
        if applied.get("missing_parts"):
            warn = "\n\n" + self._text(
                "missing_parts", "Warning: {count} part(s) could not be mapped.",
                count=len(applied["missing_parts"]))
        message = self._text(
            "overwrite_persistent_success",
            "Slot {slot}: serial and part array verified.",
            slot=actual_idx)
        if cache.get("skipped") == "already_consistent":
            message += "\n" + self._text(
                "cache_rebuild_already_current",
                "The equipped runtime actor is already current; no rebuild was needed.")
        elif cache.get("skipped"):
            message += "\n" + self._text(
                "cache_rebuild_not_needed",
                "The item is not equipped; no runtime actor rebuild was needed.")
        elif err:
            message += "\n" + self._text(
                "cache_rebuild_failed",
                "Runtime cache rebuild was not verified: {error}. The live inventory was refreshed; reload if needed.",
                error=err)
        elif cache.get("attempted") and cache.get("ok"):
            if cache.get("mode") == "unequipped_backpack":
                message += "\n" + self._text(
                    "backpack_publication_success",
                    "The unequipped backpack item's full runtime identity was published and refreshed.")
            else:
                message += "\n" + self._text(
                    "cache_rebuild_success",
                    "The equipped item full runtime identity and actor cache were rebuilt.")
        elif cache.get("supported") or cache.get("error"):
            message += "\n" + self._text(
                "cache_rebuild_failed",
                "Runtime cache rebuild was not verified: {error}. The live inventory was refreshed; reload if needed.",
                error=cache.get("error") or "unknown error")
        elif cache.get("availability") == "temporarily_unavailable":
            message += "\n" + self._text(
                "cache_rebuild_unavailable",
                "Immediate cache rebuilding is temporarily unavailable: {reason}. The persistent overwrite succeeded; reload if needed.",
                reason=cache.get("capability_reason") or "runtime write path unavailable")
        else:
            message += "\n" + self._text(
                "cache_rebuild_unsupported",
                "This live mod does not support immediate cache rebuilding; reload if needed.")
        if cache.get("uncertain"):
            message += "\n" + self._text(
                "cache_rebuild_recovery",
                "The backend reported an uncertain transaction. Check the equipped item and review the recovery lock before another write.")
            self._toast(message + warn, "warning")
        else:
            self._toast(message + warn, "success")

    # ------------------------------------------------------------------ #
    # 运行时动作（character 页）
    # ------------------------------------------------------------------ #
    def runtime_action(self, action: str, params: Optional[dict] = None) -> None:
        if not self.active or self.bridge is None:
            self.app.toast(self._text("offline", "Offline"), "warning")
            return
        vm = self._character_vm()
        request_params = dict(params or {})
        quiet = bool(request_params.pop("_quiet", False))
        if self.any_busy():
            if not quiet and vm is not None:
                vm.set_runtime_result(
                    self._text("runtime_busy", "Another live action is still running."), False)
            return
        if action in _LIVE_INVENTORY_MUTATION_ACTIONS and not self._guard_mutation(
            lambda message: vm.set_runtime_result(message, False) if vm is not None else None
        ):
            return

        label = action
        try:
            if action == "toggle_dedicated_drop_100" and request_params.get("enabled"):
                catalog = resource_loader.load_json_resource("core/data/dedicated_drop_pools.json")
                if not catalog:
                    raise RuntimeError("dedicated_drop_pools.json missing or invalid")
                request_params["catalog"] = catalog
        except Exception as exc:
            if not quiet and vm is not None:
                vm.set_runtime_result(f"{label}: {exc}", False)
            self.runtime_action("state", {"_quiet": True})
            return

        if vm is not None:
            vm.set_runtime_busy(True)
        worker = _LiveRuntimeWorker(self.bridge, action, request_params, quiet=quiet, parent=self)
        worker.completed.connect(self._on_runtime_action_finished)
        self._runtime_worker = worker
        self._track(worker)
        self._sync_vms()
        worker.start()

    def _on_runtime_action_finished(self, action, result, err, quiet=False) -> None:
        worker = self.sender()
        if action in _LIVE_INVENTORY_MUTATION_ACTIONS:
            self._remember_recovery(getattr(worker, "mutation_preflight", None))
            self._remember_recovery(result)
        if worker is self._runtime_worker:
            self._runtime_worker = None
        if not self.active:
            return

        vm = self._character_vm()
        if vm is not None:
            vm.set_runtime_busy(False)

        if err is not None or not isinstance(result, dict):
            self.app.runtimeActionFinished.emit(action, False, str(err or "invalid response"))
            if not quiet and vm is not None:
                vm.set_runtime_result(f"{action}: {err or 'invalid response'}", False)
            if action == "claim_lost_loot":
                self.refresh()
            elif action != "state":
                self.runtime_action("state", {"_quiet": True})
            else:
                self._sync_vms()
            return

        state = result.get("state")
        if isinstance(state, dict):
            self.runtime_state.update(state)
            if vm is not None:
                vm.apply_runtime_state(state)
        self.app.runtimeActionFinished.emit(
            action, bool(result.get("ok")), "" if result.get("ok") else str(result.get("error", "failed")))

        delta = result.get("inventory_delta")
        changed_count = int(result.get("claimed_count", result.get("claimed", 0)) or 0)
        needs_full_refresh = bool(result.get("changed")) or changed_count > 0
        if isinstance(delta, dict):
            records = delta.get("records")
            incremental_safe = bool(result.get("incremental_safe", True))
            if incremental_safe and isinstance(records, list) and records:
                normalized = []
                container = str(delta.get("container") or "BackpackItems")
                for record in records:
                    if not isinstance(record, dict):
                        normalized = []
                        break
                    row = dict(record)
                    row.setdefault("container", container)
                    row.setdefault("idx", row.get("index"))
                    normalized.append(row)
                if normalized:
                    self._commit_inventory_patch(normalized)
                    needs_full_refresh = False
                else:
                    needs_full_refresh = True
            elif not incremental_safe or changed_count > 0 or result.get("changed"):
                needs_full_refresh = True
        if needs_full_refresh:
            self.refresh()

        self._sync_vms()
        if quiet or vm is None:
            return
        if result.get("ok"):
            vm.set_runtime_result(f"{action}: OK", True)
        else:
            vm.set_runtime_result(f"{action}: {str(result.get('error', 'failed'))}", False)
            if not isinstance(state, dict):
                self.runtime_action("state", {"_quiet": True})

    # ------------------------------------------------------------------ #
    # 配装（loadout 页）
    # ------------------------------------------------------------------ #
    def start_loadout_worker(self, operation: str, slot: int, context: dict) -> None:
        loadout = self._loadout_vm()
        if not self.active or self.bridge is None:
            if loadout is not None:
                error = "live mode is unavailable"
                if operation == "save":
                    loadout.finish_live_snapshot(slot, str(context.get("config_name") or ""), None, error)
                elif operation == "apply":
                    loadout.finish_live_apply(slot, None, error)
                else:
                    loadout.finish_live_recovery(operation, None, error)
            return
        if self.any_busy():
            if loadout is not None:
                error = self._text("runtime_busy", "Another live action is still running.")
                if operation == "save":
                    loadout.finish_live_snapshot(slot, str(context.get("config_name") or ""), None, error)
                elif operation == "apply":
                    loadout.finish_live_apply(slot, None, error)
                else:
                    loadout.finish_live_recovery(operation, None, error)
            return
        if operation == "apply" and not self._guard_mutation(
            lambda message: loadout.finish_live_apply(slot, None, message) if loadout is not None else None
        ):
            return

        worker = _LiveLoadoutWorker(self.bridge, operation, slot, context, parent=self)
        worker.completed.connect(self._on_loadout_finished)
        self._runtime_worker = worker
        self._track(worker)
        self._sync_vms()
        worker.start()

    def _on_loadout_finished(self, operation, slot, context, result, err) -> None:
        worker = self.sender()
        if operation == "apply":
            self._remember_recovery(getattr(worker, "mutation_preflight", None))
            self._remember_recovery(result)
        elif isinstance(result, dict):
            if operation == "recovery" and (
                result.get("pending") is True or result.get("pending") is False
            ):
                recovery = result.get("recovery")
                reason = recovery.get("reason") if isinstance(recovery, dict) else ""
                self._remember_recovery({"recovery_pending": result["pending"], "reason": reason})
            elif operation == "clear_recovery" and result.get("ok"):
                self._remember_recovery({"recovery_pending": False})
        if worker is self._runtime_worker:
            self._runtime_worker = None
        self._sync_vms()
        if not self.active:
            return
        loadout = self._loadout_vm()
        if loadout is None:
            return
        if operation == "save":
            loadout.finish_live_snapshot(
                slot, str((context or {}).get("config_name") or ""), result, err)
        elif operation == "apply":
            loadout.finish_live_apply(slot, result, err)
            self.refresh()
        else:
            loadout.finish_live_recovery(operation, result, err)
            if operation == "clear_recovery":
                self.refresh()
