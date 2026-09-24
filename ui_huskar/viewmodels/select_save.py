"""选择存档页视图模型：移植 SaveSelectorWidget 的全部非渲染逻辑。

保持与主线一致的行为：扫描存档目录、自定义存档/备份/游戏目录并持久化到
config.json、选中行自动跟随 User ID（手动编辑后不再跟随）、双击/按钮打开。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QStandardPaths, pyqtProperty, pyqtSignal, pyqtSlot

from core.save_game_controller import infer_user_id_from_save_path

from .base import PageViewModel, register

CONFIG_FILE = "config.json"


@register("select_save", "SelectSavePage.qml")
class SelectSaveViewModel(PageViewModel):
    STRINGS_SECTION = "save_selector"

    dataChanged = pyqtSignal()

    def __init__(self, app, parent=None, config_file: str = CONFIG_FILE):
        super().__init__(app, parent)
        self._config_file = config_file
        self._saves: list[dict[str, Any]] = []
        self._selected_row = -1
        self._user_id = ""
        self._auto_user_id = ""
        self.custom_save_path: str | None = None
        self.custom_backup_path: str | None = None
        self.game_install_path: str | None = None
        self._load_config()

    # -- 配置持久化（与主线同一份 config.json） --------------------------
    def _load_config(self) -> None:
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, "r", encoding="utf-8") as fh:
                    config = json.load(fh)
                self.custom_save_path = config.get("custom_save_path")
                self.custom_backup_path = config.get("custom_backup_path")
                self.game_install_path = config.get("game_install_path")
            except (OSError, json.JSONDecodeError):
                pass

    def _save_config(self) -> None:
        config = {
            "custom_save_path": self.custom_save_path,
            "custom_backup_path": self.custom_backup_path,
            "game_install_path": self.game_install_path,
        }
        try:
            with open(self._config_file, "w", encoding="utf-8") as fh:
                json.dump(config, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # -- 路径推导 ---------------------------------------------------------
    def _derive_save_path_from_game_dir(self) -> str | None:
        if self.game_install_path:
            game_dir = Path(self.game_install_path)
            for root in (game_dir, *list(game_dir.parents)[:4]):
                for candidate in (root / "OakGame" / "Saved" / "SaveGames",
                                  root / "Saved" / "SaveGames"):
                    if candidate.is_dir():
                        return str(candidate)
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation)
        documents_save = Path(documents) / "My Games" / "Borderlands 4" / "Saved" / "SaveGames"
        if documents and documents_save.is_dir():
            return str(documents_save)
        return None

    def get_custom_save_path(self) -> str | None:
        return self.custom_save_path or self._derive_save_path_from_game_dir()

    def get_custom_backup_path(self) -> str | None:
        return self.custom_backup_path

    def get_open_initial_dir(self) -> str:
        resolved = self.get_custom_save_path()
        return resolved if resolved and os.path.exists(resolved) else ""

    # -- QML 暴露 ---------------------------------------------------------
    @pyqtProperty(list, notify=dataChanged)
    def saves(self) -> list[dict[str, Any]]:
        return self._saves

    @pyqtProperty(int, notify=dataChanged)
    def selectedRow(self) -> int:
        return self._selected_row

    @pyqtProperty(str, notify=dataChanged)
    def userId(self) -> str:
        return self._user_id

    @pyqtProperty(str, notify=dataChanged)
    def statusText(self) -> str:
        labels = self.strings.get("labels", {})
        if not self._saves:
            return labels.get("status_no_saves", "No save files found.")
        return labels.get("status_found_saves", "Found {count} save files.").format(
            count=len(self._saves))

    @pyqtProperty(str, notify=dataChanged)
    def gameDirText(self) -> str:
        labels = self.strings.get("labels", {})
        value = self.game_install_path or labels.get("not_set", "Not Set")
        return labels.get("current_game_dir", "Game Directory: {path}").format(path=value)

    @pyqtProperty(str, notify=dataChanged)
    def savePathText(self) -> str:
        labels = self.strings.get("labels", {})
        value = self.get_custom_save_path() or labels.get("not_set", "Not Set")
        return labels.get("current_save_path", "Current Save Path: {path}").format(path=value)

    @pyqtProperty(str, notify=dataChanged)
    def backupPathText(self) -> str:
        labels = self.strings.get("labels", {})
        value = self.custom_backup_path or labels.get("not_set", "Not Set")
        return labels.get("current_backup_path", "Current Backup Path: {path}").format(path=value)

    # -- 行为 -------------------------------------------------------------
    @pyqtSlot()
    def refresh(self) -> None:
        scanned = self.controller.scan_save_folders(self.get_custom_save_path())
        self._saves = [dict(info, key=str(i)) for i, info in enumerate(scanned)]
        self._selected_row = min(self._selected_row, len(self._saves) - 1)
        self.dataChanged.emit()

    @pyqtSlot(int)
    def selectRow(self, row: int) -> None:
        if not 0 <= row < len(self._saves):
            return
        self._selected_row = row
        row_id = str(self._saves[row].get("id", ""))
        # 跟随选中账号，直到用户手动编辑过输入框
        if not self._user_id.strip() or self._auto_user_id:
            self._user_id = row_id
            self._auto_user_id = row_id
        self.dataChanged.emit()

    @pyqtSlot(str)
    def setUserId(self, text: str) -> None:
        self._user_id = text
        self._auto_user_id = ""
        self.dataChanged.emit()

    @pyqtSlot(int)
    def openRow(self, row: int) -> None:
        """打开指定行存档：优先手动输入的 ID，否则用该行推断的 ID。"""
        if not 0 <= row < len(self._saves):
            return
        info = self._saves[row]
        user_id = self._user_id.strip() or str(info.get("id", ""))
        if not user_id:
            self.app.toast(self.tr("main_window.dialogs.enter_user_id"), "warning")
            return
        self.app.openSave(str(info.get("full_path", "")), user_id)

    @pyqtSlot()
    def openSelected(self) -> None:
        if self._selected_row >= 0:
            self.openRow(self._selected_row)
        else:
            self.app.browseSave()

    @pyqtSlot()
    def selectGameDir(self) -> None:
        path = self._pick_dir(self.strings.get("buttons", {}).get("select_game_dir",
                                                                  "Set Game Directory"))
        if not path:
            return
        self.game_install_path = path
        derived = self._derive_save_path_from_game_dir()
        dialogs = self.strings.get("dialogs", {})
        if derived:
            self.app.toast(dialogs.get("game_dir_found",
                                       "Save folder auto-detected at:\n{path}").format(path=derived),
                           "success")
        else:
            self.app.toast(dialogs.get("game_dir_not_found",
                                       "Could not auto-detect save folder from the selected directory."),
                           "warning")
        self._save_config()
        self.refresh()

    @pyqtSlot()
    def selectSaveFolder(self) -> None:
        path = self._pick_dir(self.strings.get("buttons", {}).get("select_save_folder",
                                                                  "Select Save Folder"))
        if path:
            self.custom_save_path = path
            self._save_config()
            self.refresh()

    @pyqtSlot()
    def selectBackupFolder(self) -> None:
        path = self._pick_dir(self.strings.get("buttons", {}).get("select_backup_folder",
                                                                  "Select Backup Folder"))
        if path:
            self.custom_backup_path = path
            self._save_config()
            self.dataChanged.emit()

    def _pick_dir(self, title: str) -> str:
        from PyQt6.QtWidgets import QFileDialog
        picked = QFileDialog.getExistingDirectory(None, title)
        return str(Path(picked)) if picked else ""

    def check_initial_game_dir(self) -> bool:
        """启动时是否需要提示设置游戏目录（QML 侧据此弹通知）。"""
        return not (self.custom_save_path or self._derive_save_path_from_game_dir())

    def game_dir_prompt(self) -> str:
        return self.strings.get("dialogs", {}).get(
            "game_dir_needed",
            "Game save location has been changed in a recent update.\n"
            "Please set your Borderlands 4 game directory to locate saves.")
