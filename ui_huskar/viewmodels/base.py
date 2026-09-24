"""页面视图模型基类。

每个页面对应一个 VM：持有 AppBridge（进而拿到 SaveGameController 与
Localizer），向 QML 暴露 strings（本页本地化文案）与页面数据。
生命周期：AppBridge.navigate 触发 on_activated；打开/关闭存档、切换语言时
由 AppBridge 统一 mark_stale / on_language_changed。
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

#: key → (VM 类, QML 页面文件名)。各页模块用 @register 自注册，
#: __main__.create_bridges 自动发现并实例化，避免并发修改共享文件。
REGISTRY: dict[str, tuple[type, str]] = {}


def register(key: str, qml: str):
    def wrap(cls):
        REGISTRY[key] = (cls, qml)
        cls.PAGE_KEY = key
        cls.QML_FILE = qml
        return cls
    return wrap


class PageViewModel(QObject):
    stringsChanged = pyqtSignal()
    dataChanged = pyqtSignal()

    #: 该页面在 ui_localization*.json 中的节名；None 表示无专属节
    STRINGS_SECTION: str | None = None

    def __init__(self, app, parent: QObject | None = None):
        super().__init__(parent)
        self.app = app
        self.controller = app.controller
        self._stale = True

    # -- 本地化 ----------------------------------------------------------
    def tr(self, path: str, *args: Any, **kwargs: Any) -> str:
        return self.app.tr(path, *args, **kwargs)

    @pyqtProperty("QVariantMap", notify=stringsChanged)
    def strings(self) -> dict[str, Any]:
        if self.STRINGS_SECTION:
            return self.app.localizer.section(self.STRINGS_SECTION)
        return {}

    def on_language_changed(self) -> None:
        self.stringsChanged.emit()
        self._stale = True
        self.dataChanged.emit()

    # -- 生命周期 ---------------------------------------------------------
    def mark_stale(self) -> None:
        self._stale = True

    def on_activated(self) -> None:
        if self._stale:
            self._stale = False
            self.refresh()

    def on_save_opened(self) -> None:
        """打开存档成功后调用（无论页面是否激活）。"""

    def refresh(self) -> None:
        """页面被激活且数据过期时重建数据。子类覆写后必须发 dataChanged。"""
        self.dataChanged.emit()

    @pyqtSlot()
    def forceRefresh(self) -> None:
        """QML 侧显式刷新入口（子类覆写 refresh 会丢失槽修饰，故提供此包装）。"""
        self._stale = False
        self.refresh()
