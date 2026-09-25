"""应用壳桥接层：导航、主题、语言、背景、打开/保存、自动保存与崩溃恢复。

controller-first 架构：不再隐藏 MainWindow 做控件投影，而是直接持有
SaveGameController，把主线 main_window.py 中与 QWidget 无关的编排逻辑
（解密重试、.recover 恢复、自动保存防抖、原子写盘）移植到这里，
用户反馈全部以信号形式交给 QML（HusNotification / 模态框）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from core import bl4_functions as bl4f
from core import resource_loader
from core.save_game_controller import SaveGameController
from core.theme_manager import ThemeManager

from .i18n import DEFAULT_LANGUAGE, LANGUAGES, Localizer, normalize_language

PAGE_KEYS = (
    "select_save", "character", "game_progress", "items", "serial_inspector", "yaml_editor",
    "class_mod", "enhancement", "weapon_editor", "weapon_generator", "god_roll",
    "grenade", "shield", "repkit", "heavy_weapon", "loadout_manager", "converter",
)
# HuskarUI HusIcon 字体码点（与主线 nav 按钮一一对应）
PAGE_ICONS = {
    "select_save": 0xEAE5, "character": 0xED31, "game_progress": 0xED09, "items": 0xEA0C,
    "serial_inspector": 0xEAB8, "yaml_editor": 0xE9BF, "class_mod": 0xEA52,
    "enhancement": 0xECFB, "weapon_editor": 0xE966, "weapon_generator": 0xEC64,
    "god_roll": 0xEC8D, "grenade": 0xE9A6, "shield": 0xED65,
    "repkit": 0xECFB, "heavy_weapon": 0xEC64, "loadout_manager": 0xEC88,
    "converter": 0xE9BF,
}
# 主线导航在这两组之间有分隔线
PAGE_GROUPS = (("select_save", "character", "game_progress", "items", "serial_inspector", "yaml_editor"),
               ("class_mod", "enhancement", "weapon_editor", "weapon_generator", "god_roll",
                "grenade", "shield", "repkit", "heavy_weapon"),
               ("loadout_manager", "converter"))


class AppBridge(QObject):
    pageChanged = pyqtSignal()
    languageChanged = pyqtSignal()
    themeChanged = pyqtSignal()
    animationsChanged = pyqtSignal()
    statusChanged = pyqtSignal()
    navigationChanged = pyqtSignal()
    saveStateChanged = pyqtSignal()
    autosaveChanged = pyqtSignal()
    backgroundChanged = pyqtSignal()
    liveChanged = pyqtSignal()

    toastRequested = pyqtSignal(str, str)                 # text, kind: success|error|warning|info
    confirmRequested = pyqtSignal(int, str, str, bool)    # id, title, text, isWarning
    userIdRequired = pyqtSignal(str, str)                 # file_path, last_error
    controllerDirty = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None, settings: Optional[QSettings] = None):
        super().__init__(parent)
        # 测试可注入临时 QSettings，避免污染真实用户配置
        self._settings = settings or QSettings("SuperExboom", "BL4SaveEditor")
        self.controller = SaveGameController()
        self.theme_manager = ThemeManager()
        lang = normalize_language(self._settings.value("language", DEFAULT_LANGUAGE))
        # Persist the canonical code so a legacy alias cannot reappear on the
        # next startup and silently select the Chinese fallback catalog.
        self._settings.setValue("language", lang)
        self.localizer = Localizer(lang)
        if lang != DEFAULT_LANGUAGE:
            bl4f.set_language(lang)

        self._page_index = 0
        self._animations = True
        self._status = ""
        from ui_huskar.live_support import LiveManager
        self.live = LiveManager(self)
        self._confirm_callbacks: dict[int, Callable[[bool], None]] = {}
        self._confirm_seq = 0
        self._vms: dict[str, Any] = {}
        self._vm_factory: Optional[Callable[[str], Any]] = None

        self._autosave_suspend = 0
        self._autosave_failed = False
        self._autosave_message = ""
        self._autosave_enabled = self._settings.value("autosave_enabled", True, type=bool)
        self._autosave_interval_ms = max(5, int(self._settings.value("autosave_interval_sec", 30, type=int))) * 1000
        self._recover_interval_ms = 5000
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._perform_autosave)
        self._recover_timer = QTimer(self)
        self._recover_timer.setSingleShot(True)
        self._recover_timer.timeout.connect(self._write_recovery)
        # 与主线一致：脏标记经信号队列回 GUI 线程，避免 worker 线程直接调槽
        self.controller.add_dirty_listener(self.controllerDirty.emit)
        self.controllerDirty.connect(self._on_controller_dirty)

        self._status = self.tr("main_window.status.welcome")

    # ------------------------------------------------------------------
    # 视图模型注册
    # ------------------------------------------------------------------
    def register_vm(self, key: str, vm: Any) -> None:
        self._vms[key] = vm

    def vm(self, key: str) -> Any:
        return self._vms.get(key)

    def set_vm_factory(self, factory: Callable[[str], Any]) -> None:
        """lazy 启动：由启动器提供"创建+注册+暴露给 QML"的工厂。"""
        self._vm_factory = factory

    def ensure_vm(self, key: str) -> Any:
        """取页面 VM，未创建时按需创建。

        lazy 启动只实例化进入过的页面；God Roll→武器编辑器、YAML→各编辑器这类
        跨页跳转要先把数据灌进目标页 VM，不能假设用户之前打开过目标页。
        """
        vm = self._vms.get(key)
        if vm is None and self._vm_factory is not None and key in PAGE_KEYS:
            vm = self._vm_factory(key)
        return vm

    def _mark_all_stale(self) -> None:
        for vm in self._vms.values():
            vm.mark_stale()

    # ------------------------------------------------------------------
    # 本地化
    # ------------------------------------------------------------------
    def tr(self, path: str, *args: Any, **kwargs: Any) -> str:
        return self.localizer.tr(path, *args, **kwargs)

    @pyqtSlot(str, result=str)
    def trText(self, path: str) -> str:
        return self.localizer.tr(path)

    @pyqtSlot(str, "QVariantMap", result=str)
    def trFormat(self, path: str, params) -> str:
        return self.localizer.tr(path, **dict(params or {}))

    @pyqtProperty(str, notify=languageChanged)
    def language(self) -> str:
        return self.localizer.lang

    @pyqtProperty(list, notify=languageChanged)
    def languages(self) -> list[dict[str, str]]:
        return [{"label": label, "value": code} for code, label in LANGUAGES]

    @pyqtProperty("QVariantMap", notify=languageChanged)
    def pageFiles(self) -> dict[str, str]:
        """key → QML 页面文件名；未注册的页由 Main.qml 落到占位页。"""
        from ui_huskar.viewmodels.base import REGISTRY
        return {key: qml for key, (_cls, qml) in REGISTRY.items()}

    @pyqtSlot(str)
    def setLanguage(self, lang: str) -> None:
        lang = normalize_language(lang)
        if lang == self.localizer.lang or lang not in dict(LANGUAGES):
            return
        self._settings.setValue("language", lang)
        self.localizer.set_language(lang)
        bl4f.set_language(lang)
        for vm in self._vms.values():
            vm.on_language_changed()
        self._status = self.tr("main_window.status.welcome") if not self.saveLoaded else self._status
        self.languageChanged.emit()
        self.navigationChanged.emit()
        self.statusChanged.emit()
        # windowTitle is notified by saveStateChanged because its value also
        # includes the current filename. Emit it here as well so the title
        # binding refreshes when only the language changes.
        self.saveStateChanged.emit()

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    @pyqtProperty(list, notify=navigationChanged)
    def navigation(self) -> list[dict[str, Any]]:
        items = []
        for key in PAGE_KEYS:
            items.append({
                "key": key,
                "label": self.tr(f"main_window.tabs.{key}"),
                "iconSource": PAGE_ICONS[key],
                "group": next(i for i, g in enumerate(PAGE_GROUPS) if key in g),
            })
        return items

    @pyqtProperty(int, notify=pageChanged)
    def pageIndex(self) -> int:
        return self._page_index

    @pyqtProperty(str, notify=pageChanged)
    def pageKey(self) -> str:
        return PAGE_KEYS[self._page_index]

    @pyqtSlot(int)
    @pyqtSlot(str)
    def navigate(self, target) -> None:
        index = PAGE_KEYS.index(target) if isinstance(target, str) else int(target)
        if not 0 <= index < len(PAGE_KEYS):
            return
        vm = self.ensure_vm(PAGE_KEYS[index])
        if index == self._page_index:
            # 已在目标页（例如停在角色页时从标题栏重新打开存档）：不换页，
            # 但数据已被标记过期，需要就地刷新，否则页面一直显示上一个存档。
            if vm is not None:
                vm.on_activated()
            return
        self._page_index = index
        if vm is not None:
            vm.on_activated()
        self.pageChanged.emit()

    # ------------------------------------------------------------------
    # 主题 / 动效 / 背景
    # ------------------------------------------------------------------
    @pyqtProperty(bool, notify=themeChanged)
    def dark(self) -> bool:
        return self.theme_manager.is_dark()

    @pyqtSlot()
    def toggleTheme(self) -> None:
        self.theme_manager.toggle_theme()
        self.themeChanged.emit()

    @pyqtProperty(bool, notify=animationsChanged)
    def animations(self) -> bool:
        return self._animations

    @pyqtSlot()
    def toggleAnimations(self) -> None:
        self._animations = not self._animations
        self.animationsChanged.emit()

    @pyqtProperty(str, notify=backgroundChanged)
    def backgroundUrl(self) -> str:
        custom = str(self._settings.value("custom_background", "") or "")
        candidates = [custom] if custom else []
        candidates.append(str(resource_loader.get_resource_path("assets/bg.jpg")))
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file():
                return path.as_uri()
        return ""

    @pyqtProperty(bool, notify=backgroundChanged)
    def hasCustomBackground(self) -> bool:
        custom = str(self._settings.value("custom_background", "") or "")
        return bool(custom) and Path(custom).is_file()

    @pyqtProperty(int, notify=backgroundChanged)
    def blurStrength(self) -> int:
        return int(self._settings.value("ui/blur_strength", 48))

    @pyqtSlot(int)
    def setBlurStrength(self, value: int) -> None:
        value = max(0, min(64, int(value)))
        self._settings.setValue("ui/blur_strength", value)
        self.backgroundChanged.emit()

    @pyqtSlot()
    def changeBackground(self) -> None:
        if self.hasCustomBackground:
            self._request_confirm(
                self.tr("main_window.dialogs.clear_bg_title"),
                self.tr("main_window.dialogs.clear_bg_prompt"),
                lambda accepted: self._clear_background() if accepted else self._pick_background(),
            )
        else:
            self._pick_background()

    def _pick_background(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, self.tr("main_window.dialogs.change_bg_title"), "",
            f"{self.tr('main_window.dialogs.image_files')} (*.png *.jpg *.jpeg *.bmp);;All Files (*.*)",
        )
        if path:
            self._settings.setValue("custom_background", path)
            self.backgroundChanged.emit()

    @pyqtSlot()
    def clearBackground(self) -> None:
        self._clear_background()

    def _clear_background(self) -> None:
        self._settings.remove("custom_background")
        self.backgroundChanged.emit()

    # ------------------------------------------------------------------
    # 状态 / 存档状态
    # ------------------------------------------------------------------
    @pyqtProperty(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @pyqtSlot(str, str)
    def toast(self, text: str, kind: str = "info") -> None:
        self.toastRequested.emit(text, kind)

    def set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    @pyqtProperty(bool, notify=saveStateChanged)
    def saveLoaded(self) -> bool:
        return self.controller.yaml_obj is not None

    @pyqtProperty(bool, notify=saveStateChanged)
    def canSave(self) -> bool:
        return self.controller.yaml_obj is not None and not self.live.active

    @pyqtProperty(bool, notify=saveStateChanged)
    def dirty(self) -> bool:
        return self.controller.dirty

    @pyqtProperty(str, notify=saveStateChanged)
    def fileName(self) -> str:
        path = self.controller.save_path
        if path:
            return Path(path).name
        if self.live.active:
            return "LIVE"
        return ""

    @pyqtProperty(str, notify=saveStateChanged)
    def windowTitle(self) -> str:
        title = self.tr("main_window.window_title")
        return f"{title} - {self.fileName}" if self.fileName else title

    # ------------------------------------------------------------------
    # 打开 / 保存
    # ------------------------------------------------------------------
    @pyqtSlot()
    def browseSave(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from core.save_game_controller import infer_user_id_from_save_path
        initial = ""
        selector = self._vms.get("select_save")
        if selector is not None:
            initial = selector.get_open_initial_dir()
        if not initial:
            initial = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            None, self.tr("main_window.menu.open_selector"), initial,
            self.tr("main_window.dialogs.save_filter"),
        )
        if path:
            user_id = ""
            if selector is not None:
                user_id = selector.userId.strip()
            self.openSave(path, user_id or infer_user_id_from_save_path(path))

    @pyqtSlot(str, str)
    def openSave(self, file_path: str, user_id: str) -> None:
        if not file_path:
            return
        if self.live.active:
            self.toast(self.tr("main_window.dialogs.live_mode_active", default="Live 模式下无法打开存档"), "warning")
            return
        backup_dir = None
        selector = self._vms.get("select_save")
        if selector is not None:
            backup_dir = selector.get_custom_backup_path()
        try:
            _plain, platform, backup_name = self.controller.decrypt_save(
                Path(file_path), user_id, backup_dir)
        except ValueError as exc:
            self.userIdRequired.emit(file_path, str(exc))
            return
        except Exception as exc:  # 读文件等意外错误
            self.toast(self.tr("main_window.dialogs.decrypt_failed_reason") + f" ({exc})", "error")
            return
        self.toast(self.tr("main_window.dialogs.decrypt_success",
                           platform=platform, backup_name=backup_name), "success")
        self._set_autosave_indicator("", False)
        self._mark_all_stale()
        self.saveStateChanged.emit()
        selector = self._vms.get("select_save")
        if selector is not None:
            selector.on_save_opened()
        self._maybe_restore_recovery(Path(file_path))
        self.navigate("character")

    @pyqtSlot()
    @pyqtSlot(bool)
    def save(self, _checked: bool = False) -> None:
        self._save_impl(save_as=False)

    @pyqtSlot()
    def saveAs(self) -> None:
        self._save_impl(save_as=True)

    def _save_impl(self, save_as: bool) -> None:
        if self.controller.yaml_obj is None or self.live.active:
            return
        path_to_save = self.controller.save_path
        if save_as or not path_to_save:
            from PyQt6.QtWidgets import QFileDialog
            picked, _ = QFileDialog.getSaveFileName(
                None, self.tr("main_window.menu.save_as"),
                str(path_to_save or ""),
                self.tr("main_window.dialogs.save_filter"),
            )
            if not picked:
                return
            path_to_save = picked
        try:
            saved = self.controller.save_to_disk(path_to_save)
        except Exception as exc:
            self.toast(f"{self.tr('main_window.dialogs.critical')}: {exc}", "error")
            return
        self._autosave_timer.stop()
        self._recover_timer.stop()
        self._remove_recovery()
        self._set_autosave_indicator("", False)
        self.toast(f"{self.tr('main_window.dialogs.success')}: {saved.name}", "success")
        self.saveStateChanged.emit()

    # ------------------------------------------------------------------
    # 自动保存 + 崩溃恢复（移植自 main_window.py，行为一致）
    # ------------------------------------------------------------------
    @pyqtProperty(bool, notify=autosaveChanged)
    def autosaveEnabled(self) -> bool:
        return self._autosave_enabled

    @pyqtProperty(bool, notify=autosaveChanged)
    def autosaveFailed(self) -> bool:
        return self._autosave_failed

    @pyqtSlot(bool)
    def setAutosaveEnabled(self, on: bool) -> None:
        self._autosave_enabled = bool(on)
        self._settings.setValue("autosave_enabled", self._autosave_enabled)
        self._set_autosave_indicator("", False)
        if not on:
            self._autosave_timer.stop()
            self._recover_timer.stop()
        elif self.controller.dirty:
            self._on_controller_dirty()
        self.autosaveChanged.emit()

    def suspend_autosave(self, suspend: bool) -> None:
        """后台 worker 运行期间挂起自动保存，避免序列化中间态。"""
        self._autosave_suspend = max(0, self._autosave_suspend + (1 if suspend else -1))
        if not suspend and self._autosave_suspend == 0 and self.controller.dirty:
            self._on_controller_dirty()

    def _set_autosave_indicator(self, message: str, failed: bool) -> None:
        self._autosave_message = message
        self._autosave_failed = failed
        self.autosaveChanged.emit()

    @pyqtProperty(str, notify=autosaveChanged)
    def autosaveMessage(self) -> str:
        return self._autosave_message

    def _on_controller_dirty(self) -> None:
        self.saveStateChanged.emit()
        if not self._autosave_enabled:
            return
        self._autosave_timer.start(self._autosave_interval_ms)
        self._recover_timer.start(self._recover_interval_ms)

    def _recovery_path(self, save_path=None) -> Optional[Path]:
        save_path = save_path or self.controller.save_path
        if not save_path:
            return None
        sp = Path(save_path)
        return sp.with_name(sp.name + ".recover")

    def _write_recovery(self) -> None:
        if not self.controller.dirty or self.controller.yaml_obj is None:
            return
        if self._autosave_suspend > 0:
            self._recover_timer.start(self._recover_interval_ms)
            return
        rp = self._recovery_path()
        if rp is None:
            return
        try:
            tmp = rp.with_name(rp.name + ".tmp")
            tmp.write_text(self.controller.get_yaml_string(), encoding="utf-8")
            os.replace(tmp, rp)
        except OSError:
            pass

    def _remove_recovery(self, save_path=None) -> None:
        rp = self._recovery_path(save_path)
        if rp and rp.exists():
            try:
                rp.unlink()
            except OSError:
                pass

    def _perform_autosave(self) -> None:
        if not self.controller.dirty or self.controller.yaml_obj is None:
            return
        if self._autosave_suspend > 0:
            self._autosave_timer.start(self._recover_interval_ms)
            return
        if not self.controller.save_path:
            return
        if self.controller.is_content_saved():
            self.controller.mark_clean()
            self._remove_recovery()
            self._set_autosave_indicator("", False)
            return
        try:
            target = self.controller.save_to_disk()
            self._remove_recovery()
            self._set_autosave_indicator(
                self.tr("main_window.status.autosaved").format(time=time.strftime("%H:%M:%S")),
                False,
            )
            self.set_status(f"{self.tr('main_window.status.autosave')} → {target.name}")
        except Exception:
            self._set_autosave_indicator(
                self.tr("main_window.status.autosave_failed"), True)
            self._autosave_timer.start(self._recover_interval_ms)
        self.saveStateChanged.emit()

    def _maybe_restore_recovery(self, file_path: Path) -> None:
        rp = Path(str(file_path) + ".recover")
        try:
            if not rp.exists() or rp.stat().st_mtime <= file_path.stat().st_mtime:
                if rp.exists():
                    rp.unlink()
                return
        except OSError:
            return

        def _decide(accepted: bool) -> None:
            if accepted:
                try:
                    text = rp.read_text(encoding="utf-8")
                    if self.controller.update_yaml_object(text):
                        self._set_autosave_indicator(
                            self.tr("main_window.status.recovered"), False)
                        self.saveStateChanged.emit()
                        # 恢复发生在确认框回调里，此时当前页早已按原存档刷新过；
                        # 不重新标记过期的话会一直显示恢复前的数据。
                        self._mark_all_stale()
                        current = self._vms.get(PAGE_KEYS[self._page_index])
                        if current is not None:
                            current.on_activated()
                        return
                except OSError:
                    pass
            self._remove_recovery(file_path)

        self._request_confirm(
            self.tr("main_window.dialogs.recover_title"),
            self.tr("main_window.dialogs.recover_msg"),
            _decide,
        )

    # ------------------------------------------------------------------
    # 确认框路由
    # ------------------------------------------------------------------
    def _request_confirm(self, title: str, text: str, callback: Callable[[bool], None],
                         warning: bool = False) -> None:
        self._confirm_seq += 1
        self._confirm_callbacks[self._confirm_seq] = callback
        self.confirmRequested.emit(self._confirm_seq, title, text, warning)

    @pyqtSlot(int, bool)
    def resolveConfirm(self, confirm_id: int, accepted: bool) -> None:
        callback = self._confirm_callbacks.pop(confirm_id, None)
        if callback is not None:
            callback(accepted)

    # ------------------------------------------------------------------
    # 物品写入编排（移植自 main_window.handle_add_to_backpack / handle_update_item，
    # QMessageBox 换成 toast；live 分支在 live 阶段接入）
    # ------------------------------------------------------------------
    @pyqtSlot(str, str, result=bool)
    def addSerialToBackpack(self, serial_input: str, flag: str) -> bool:
        if not self.controller.yaml_obj:
            self.toast(self.tr("main_window.dialogs.load_save_first"), "warning")
            return False
        if self.live.active:
            return self._live_add_to_backpack(serial_input)
        try:
            from core import b_encoder
            serial_input = serial_input.strip()
            if serial_input.startswith("@U"):
                final_serial = serial_input
            else:
                encoded_serial, err = b_encoder.encode_to_base85(serial_input)
                if err:
                    self.toast(self.tr("main_window.dialogs.encode_failed_msg", error=err), "error")
                    return False
                final_serial = encoded_serial
            path = self.controller.add_item_to_backpack(final_serial, flag)
        except Exception as exc:
            self.toast(self.tr("main_window.dialogs.add_error", error=exc), "error")
            return False
        if not path:
            self.toast(self.tr("main_window.dialogs.add_fail"), "error")
            return False
        self.toast(self.tr("main_window.dialogs.add_success"), "success")
        self._mark_items_stale()
        return True

    @pyqtSlot("QVariantMap", result=bool)
    def updateItem(self, payload: dict) -> bool:
        """payload: {item_path, original_item_data, new_item_data, success_msg?}"""
        if not self.controller.yaml_obj:
            self.toast(self.tr("main_window.dialogs.load_save_first"), "warning")
            return False
        if self.live.active:
            return self._live_update_item(dict(payload))
        try:
            msg = self.controller.update_item(
                item_path=list(payload["item_path"]),
                original_item_data=dict(payload["original_item_data"]),
                new_item_data=dict(payload["new_item_data"]),
            )
        except Exception as exc:
            self.toast(self.tr("main_window.dialogs.update_error", error=exc), "error")
            return False
        self.toast(str(payload.get("success_msg") or msg), "success")
        self._mark_items_stale()
        return True

    def _mark_items_stale(self) -> None:
        for key in ("items", "weapon_editor", "yaml_editor", "loadout_manager", "serial_inspector"):
            vm = self._vms.get(key)
            if vm is not None:
                vm.mark_stale()
        current = self._vms.get(PAGE_KEYS[self._page_index])
        if current is not None:
            current.on_activated()

    def _live_add_to_backpack(self, serial_input: str) -> bool:
        return self.live.add_to_backpack(serial_input)

    def _live_update_item(self, payload: dict) -> bool:
        return self.live.update_item(dict(payload))

    def runtime_action(self, action: str, params: Optional[dict] = None) -> None:
        """live 运行时操作入口（character 页）。"""
        self.live.runtime_action(action, params)

    @pyqtSlot("QVariantMap")
    def openGeneratedWeapon(self, result: dict) -> None:
        """God Roll 结果 → 武器编辑器（对齐主线 handle_open_generated_weapon）。"""
        vm = self.ensure_vm("weapon_editor")
        if vm is None or not hasattr(vm, "open_roll_result"):
            self.toast(self.tr("main_window.dialogs.item_not_found"), "warning")
            return
        try:
            vm.open_roll_result(dict(result))
            self.navigate("weapon_editor")
        except Exception as exc:
            self.toast(f"{type(exc).__name__}: {exc}", "error")

    @pyqtSlot("QVariantMap")
    def openItemFromYaml(self, item: dict) -> None:
        """YAML 编辑器跳转：按物品类型路由（对齐主线 handle_open_item_from_yaml）。"""
        if not item:
            return
        from core.item_display_resolver import WEAPON_TYPES
        type_en = str(item.get("type_en") or "").strip()
        route = {
            "Heavy Weapon": "heavy_weapon", "Shield": "shield", "Grenade": "grenade",
            "Repkit": "repkit", "Class Mod": "class_mod", "Enhancement": "enhancement",
        }
        try:
            if type_en in WEAPON_TYPES:
                vm = self.ensure_vm("weapon_editor")
                if vm is not None:
                    vm.load_weapon_data(dict(item))
                    self.navigate("weapon_editor")
                    return
            key = route.get(type_en)
            vm = self.ensure_vm(key) if key else None
            if vm is not None and hasattr(vm, "open_item_serial"):
                vm.open_item_serial(dict(item))
                self.navigate(key)
                return
        except Exception as exc:
            self.toast(f"{type(exc).__name__}: {exc}", "warning")
        # 回退：物品总览页选中
        items_vm = self.ensure_vm("items")
        if items_vm is not None:
            self.navigate("items")
            if not items_vm.selectByPath(list(item.get("original_path") or [])):
                self.toast(self.tr("main_window.status.item_not_found"), "warning")

    # ------------------------------------------------------------------
    # live 联机（LiveManager 承载全部编排，见 live_support.py）
    # ------------------------------------------------------------------
    @pyqtProperty(bool, notify=liveChanged)
    def liveActive(self) -> bool:
        return self.live.active

    @pyqtProperty(bool, notify=liveChanged)
    def liveBusy(self) -> bool:
        return self.live.any_busy()

    @pyqtProperty(str, notify=liveChanged)
    def liveStatusText(self) -> str:
        if self.live.connecting:
            return "… " + self.tr("main_window.live.connecting", default="Connecting…")
        if self.live.active:
            return "● " + self.tr("main_window.live.online", default="Online")
        return "○ " + self.tr("main_window.live.offline", default="Offline")

    @pyqtSlot()
    def toggleLive(self) -> None:
        self.live.toggle()

    @pyqtSlot()
    def liveRefresh(self) -> None:
        self.live.refresh()

    # ------------------------------------------------------------------
    # 退出清理
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """应用退出前：live 模式先退出；有未保存修改时补写 .recover。"""
        if self.live.active and not self.live.any_busy():
            self.live.exit()
        if self.controller.dirty and self.controller.yaml_obj is not None:
            self._write_recovery()
