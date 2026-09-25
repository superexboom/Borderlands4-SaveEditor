"""物品总览 VM：移植 QtItemsTab 的全部非渲染逻辑。

分组树（容器→类型→物品）在 VM 侧扁平化为行模型供 QML ListView 使用；
筛选复用 core.item_filter；悬停卡片复用 tabs/qt_items_tab 的模块级
HTML 渲染函数（武器/装备/职业模组/强化模组四种卡片），并经
core.card_image 离屏渲染成 PNG 供 QML Image 显示（QML Text 的富文本
无法绘制表格单元格 background-image，会渲染成黑底）。
悬停防抖状态机也在 VM 侧（对齐主线 QtItemsTab 的 viewport MouseMove
语义），QML 只负责转发 enter/exit/scroll 事件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from core import card_image, item_card_model, resource_loader
from core.item_filter import matches_item_search, prepare_item_search
from tabs.qt_items_tab import (
    classmod_card_html,
    enhancement_card_html,
    equipment_card_html,
    weapon_card_html,
)

from .base import PageViewModel, register

_FLAG_CODE_ORDER = ("1", "3", "5", "17", "33", "65", "129")
_FILTER_KEYS = ("container", "type", "manufacturer", "rarity", "flags")
#: 与主线一致的悬停唤醒延迟（QStyle.SH_ToolTip_WakeUpDelay 缺省 700ms）
_HOVER_DELAY_MS = 700
#: 可复制单元格列 → 行模型字段（与 ItemsPage 列顺序一致）
_COPY_COLUMNS = ("name", "type", "manufacturer", "rarity", "level", "flags", "serial")
#: 悬停卡片 PNG 落盘目录（相对项目根 / 打包后的 CWD），与序列检视器共用
CARDS_DIR = ".local/huskar_cards"


@register("items", "ItemsPage.qml")
class ItemsViewModel(PageViewModel):
    STRINGS_SECTION = "items_tab"

    dataChanged = pyqtSignal()
    #: 悬停定时器到期且光标仍在同一行：QML 打开卡片弹层（row + 图片信息）
    hoverCardRequested = pyqtSignal(int, "QVariantMap")
    #: 悬停目标失效（移出/滚动/换行）：QML 关闭卡片弹层
    hoverCardDismissed = pyqtSignal()

    def __init__(self, app, parent=None, cards_dir: str = CARDS_DIR):
        super().__init__(app, parent)
        self.current_lang = str(app.language)
        self._all_items: list[dict[str, Any]] = []
        self._rows: list[dict[str, Any]] = []
        self._collapsed: set[str] = set()
        self._search_text = ""
        self._filter_values: dict[str, Any] = {key: None for key in _FILTER_KEYS}
        self._level_min = 0
        self._level_max = 0
        self._add_serial = ""
        self._flag_index = 0
        self._card_cache: dict[tuple, str] = {}
        self._card_model_cache: dict[tuple, dict[str, Any] | None] = {}
        self._card_image_cache: dict[tuple, dict[str, Any]] = {}
        self._cards_dir = Path(cards_dir)
        self._card_seq = 0
        self._hover_pending_row = -1
        self._hover_shown_row = -1
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._fire_hover_card)
        self.character_level: int | None = None
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        self._flag_index = self._default_flag_index()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(100)
        self._search_timer.timeout.connect(self._rebuild_rows)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self.current_lang = str(self.app.language)
        self._flags = resource_loader.get_flag_labels(self.current_lang)
        self._flag_labels = [self._flags[k] for k in _FLAG_CODE_ORDER if k in self._flags]
        try:
            data = self.controller.get_character_data() or {}
            level = data.get("角色等级")
            self.character_level = int(level) if str(level).isdigit() else None
        except (TypeError, ValueError):
            self.character_level = None
        try:
            self._all_items = self.controller.get_all_items() or []
        except Exception:
            self._all_items = []
        self._card_cache.clear()
        self._card_model_cache.clear()
        self._card_image_cache.clear()
        self._prune_card_files()
        self.hoverCanceled()
        self._defaults_collapsed = False
        self._rebuild_rows()

    def on_language_changed(self) -> None:
        super().on_language_changed()
        self._card_cache.clear()
        self._card_model_cache.clear()
        self._card_image_cache.clear()
        self.refresh()

    # ------------------------------------------------------------------ #
    # 本地化辅助
    # ------------------------------------------------------------------ #
    def _container_display(self, container_raw: Any) -> str:
        defaults = self.strings.get("defaults", {})
        if not container_raw:
            return defaults.get("unknown_container", "Unknown")
        return self.strings.get("containers", {}).get(container_raw, str(container_raw))

    def _flag_display(self, flag: Any) -> str:
        text = self.strings.get("add_item", {}).get("flags", {}).get(str(flag), str(flag or ""))
        if "(" in text and ")" in text:
            return text.split("(", 1)[1].split(")", 1)[0]
        return text

    def _canonical_item_value(self, item: dict[str, Any], key: str) -> str:
        if key == "container":
            return str(item.get("container") or "")
        if key == "type":
            return str(item.get("type_en") or item.get("type") or "")
        if key == "manufacturer":
            return str(item.get("manufacturer_en") or item.get("manufacturer") or "")
        if key == "rarity":
            return str(item.get("rarity_en") or item.get("rarity") or "")
        return str(item.get(key) or "")

    def _filter_display_value(self, item: dict[str, Any], key: str, value: str) -> str:
        if key == "container":
            return self._container_display(value)
        display_key = {"type": "type", "manufacturer": "manufacturer", "rarity": "rarity"}.get(key)
        return str(item.get(display_key) or value) if display_key else value

    # ------------------------------------------------------------------ #
    # QML 属性
    # ------------------------------------------------------------------ #
    @pyqtProperty(list, notify=dataChanged)
    def rows(self) -> list[dict[str, Any]]:
        return self._rows

    @pyqtProperty(str, notify=dataChanged)
    def searchText(self) -> str:
        return self._search_text

    @pyqtProperty(str, notify=dataChanged)
    def filterCountText(self) -> str:
        shown = sum(1 for row in self._rows if row["rowType"] == "item")
        return self.strings.get("filters", {}).get("count", "{shown}/{total}").format(
            shown=shown, total=len(self._all_items))

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def filterOptions(self) -> dict[str, list]:
        all_text = self.strings.get("filters", {}).get("all", "All")
        options: dict[str, list] = {}
        for key in ("container", "type", "manufacturer", "rarity"):
            values: dict[str, str] = {}
            for item in self._all_items:
                value = self._canonical_item_value(item, key)
                if value and value not in values:
                    values[value] = self._filter_display_value(item, key, value)
            options[key] = [{"label": all_text, "value": None}] + [
                {"label": values[v], "value": v} for v in sorted(values, key=str.casefold)]
        flags_loc = self.strings.get("add_item", {}).get("flags", {})
        options["flags"] = [{"label": all_text, "value": None}] + [
            {"label": flags_loc.get(v, v), "value": v} for v in _FLAG_CODE_ORDER]
        return options

    @pyqtProperty("QVariantMap", notify=dataChanged)
    def filterValues(self) -> dict[str, Any]:
        return dict(self._filter_values)

    @pyqtProperty(int, notify=dataChanged)
    def levelMin(self) -> int:
        return self._level_min

    @pyqtProperty(int, notify=dataChanged)
    def levelMax(self) -> int:
        return self._level_max

    @pyqtProperty(list, notify=dataChanged)
    def flagOptions(self) -> list[dict[str, Any]]:
        return [{"label": label, "value": label.split(" ", 1)[0]} for label in self._flag_labels]

    @pyqtProperty(int, notify=dataChanged)
    def flagIndex(self) -> int:
        return self._flag_index

    @pyqtProperty(str, notify=dataChanged)
    def addSerial(self) -> str:
        return self._add_serial

    @pyqtProperty(bool, notify=dataChanged)
    def saveLoaded(self) -> bool:
        return self.app.saveLoaded

    # ------------------------------------------------------------------ #
    # QML 槽
    # ------------------------------------------------------------------ #
    @pyqtSlot(str)
    def setSearchText(self, text: str) -> None:
        if text == self._search_text:
            return
        self._search_text = text
        self._search_timer.start()  # 100ms 防抖，与主线一致

    @pyqtSlot(str, "QVariant")
    def setFilter(self, key: str, value: Any) -> None:
        if key not in _FILTER_KEYS:
            return
        self._filter_values[key] = value if value not in ("", "None") else None
        self._rebuild_rows()

    @pyqtSlot(int)
    def setLevelMin(self, value: int) -> None:
        self._level_min = max(0, int(value))
        self._rebuild_rows()

    @pyqtSlot(int)
    def setLevelMax(self, value: int) -> None:
        self._level_max = max(0, int(value))
        self._rebuild_rows()

    @pyqtSlot()
    def clearFilters(self) -> None:
        self._search_text = ""
        self._filter_values = {key: None for key in _FILTER_KEYS}
        self._level_min = 0
        self._level_max = 0
        self._rebuild_rows()

    @pyqtSlot(str)
    def toggleGroup(self, key: str) -> None:
        if key in self._collapsed:
            self._collapsed.discard(key)
        else:
            self._collapsed.add(key)
        self._rebuild_rows()

    @pyqtSlot(str)
    def setAddSerial(self, text: str) -> None:
        self._add_serial = text

    @pyqtSlot(int)
    def setFlagIndex(self, index: int) -> None:
        if 0 <= index < len(self._flag_labels):
            self._flag_index = index
            self.dataChanged.emit()

    @pyqtSlot()
    def addItem(self) -> None:
        serial = self._add_serial.strip()
        if not serial:
            self.app.toast(self.strings.get("dialogs", {}).get("enter_serial", "Enter serial"), "warning")
            return
        if self.app.addSerialToBackpack(serial, self._flag_value()):
            self._add_serial = ""
            self.dataChanged.emit()

    @pyqtSlot(int, result=str)
    def hoverCardHtml(self, row: int) -> str:
        """悬停卡片 HTML（防抖/弹层由 hoverEntered/hoverExited 状态机负责）。"""
        item = self._item_at(row)
        if item is None:
            return ""
        cache_key = self._card_cache_key(item)
        if cache_key not in self._card_cache:
            columns = self.strings.get("columns", {})
            level_label = columns.get("level", "Level")
            card = (
                weapon_card_html(item, self.current_lang, level_label, columns)
                or equipment_card_html(item, self.current_lang, level_label, columns)
                or classmod_card_html(item, self.current_lang, level_label, columns,
                                      self.character_level, 4)
                or enhancement_card_html(item, self.current_lang, level_label, columns)
            )
            self._card_cache[cache_key] = card or ""
        return self._card_cache[cache_key]

    @pyqtSlot(int, result="QVariantMap")
    def hoverCardModel(self, row: int) -> dict[str, Any]:
        """Card data for the QML ItemCard (the game's card fields); {} when the item has none."""
        item = self._item_at(row)
        if item is None:
            return {}
        cache_key = self._card_cache_key(item)
        if cache_key not in self._card_model_cache:
            level_label = self.strings.get("columns", {}).get("level", "Level")
            self._card_model_cache[cache_key] = item_card_model.build_card(
                item, self.current_lang, level_label, self.character_level)
        return self._card_model_cache[cache_key] or {}

    @pyqtSlot(int, result="QVariantMap")
    def hoverCardImage(self, row: int) -> dict[str, Any]:
        """悬停卡片渲染图：与主线 QToolTip 同一 QTextDocument 绘制路径。

        QML Text 的富文本走 scene graph 绘制，表格单元格的 background-image
        会变成黑底且 <img> 定位偏移，因此这里离屏渲染成 PNG 交给 QML Image。
        """
        item = self._item_at(row)
        if item is None:
            return {}
        cache_key = self._card_cache_key(item)
        cached = self._card_image_cache.get(cache_key)
        if cached is not None and Path(cached.get("path", "")).is_file():
            return {"url": cached["url"], "width": cached["width"], "height": cached["height"]}
        html = self.hoverCardHtml(row)
        if not html:
            return {}
        pixmap = card_image.html_to_pixmap(html, scale=2.0)
        if pixmap.isNull():
            return {}
        try:
            self._cards_dir.mkdir(parents=True, exist_ok=True)
            # 递增文件名：QML Image 仅在 source 变化时重载，覆盖同名文件不刷新
            self._card_seq += 1
            path = self._cards_dir / f"item_hover_card_{self._card_seq}.png"
            if not pixmap.save(str(path), "PNG"):
                return {}
        except OSError:
            return {}
        info = {
            "path": str(path),
            "url": path.resolve().as_uri(),
            "width": pixmap.width() / pixmap.devicePixelRatio(),
            "height": pixmap.height() / pixmap.devicePixelRatio(),
        }
        self._card_image_cache[cache_key] = info
        return {"url": info["url"], "width": info["width"], "height": info["height"]}

    # ------------------------------------------------------------------ #
    # 悬停防抖状态机（对齐主线 QtItemsTab._update_hover_card 语义）
    # ------------------------------------------------------------------ #
    @pyqtSlot(int)
    def hoverEntered(self, row: int) -> None:
        """光标进入/移动到物品行：换行即作废旧卡片并重启 700ms 定时器。

        行的 onPositionChanged 每次移动都调本槽（对齐主线 viewport MouseMove
        重评估），因此进入新行后旧行的迟到 onExited 不会误杀新行的定时器
        （见 hoverExited 的行校验）。
        """
        if self._item_at(row) is None:
            self.hoverCanceled()
            return
        if row == self._hover_pending_row and self._hover_timer.isActive():
            return
        if row == self._hover_shown_row:
            return
        if self._hover_shown_row >= 0:
            self._hover_shown_row = -1
            self.hoverCardDismissed.emit()
        self._hover_pending_row = row
        self._hover_timer.start()

    @pyqtSlot(int)
    def hoverExited(self, row: int) -> None:
        """光标离开某行：仅当该行仍是悬停目标时才取消，忽略旧行的迟到事件。"""
        if row == self._hover_pending_row:
            self._hover_timer.stop()
            self._hover_pending_row = -1
        if row == self._hover_shown_row:
            self._hover_shown_row = -1
            self.hoverCardDismissed.emit()

    @pyqtSlot()
    def hoverCanceled(self) -> None:
        """滚动/筛选重建/离开列表：无条件取消悬停。"""
        self._hover_timer.stop()
        self._hover_pending_row = -1
        if self._hover_shown_row >= 0:
            self._hover_shown_row = -1
        self.hoverCardDismissed.emit()

    def _fire_hover_card(self) -> None:
        row = self._hover_pending_row
        self._hover_pending_row = -1
        # QML ItemCard from the card model; the old HTML->PNG card only as a fallback.
        model = self.hoverCardModel(row)
        info = {"card": model} if model else self.hoverCardImage(row)
        if not info:
            return
        self._hover_shown_row = row
        self.hoverCardRequested.emit(row, info)

    def _prune_card_files(self) -> None:
        try:
            for stale in self._cards_dir.glob("item_hover_card_*.png"):
                stale.unlink(missing_ok=True)
        except OSError:
            pass

    def _card_cache_key(self, item: dict[str, Any]) -> tuple:
        return (self.current_lang, str(self.character_level or ""),
                str(item.get("serial") or item.get("decoded_full") or ""))

    @pyqtSlot(int, result="QVariantMap")
    def itemAt(self, row: int) -> dict[str, Any]:
        item = self._item_at(row)
        return dict(item) if item else {}

    @pyqtSlot(int, str)
    def copyItemField(self, row: int, field: str) -> None:
        item = self._item_at(row)
        if item is None:
            return
        key = {"name": "name", "serial": "serial", "decoded": "decoded_full",
               "parts": "decoded_parts"}.get(field)
        if key:
            QApplication.clipboard().setText(str(item.get(key, "") or ""))

    @pyqtSlot(int, str)
    def copyCell(self, row: int, column: str) -> None:
        """Ctrl+C 复制选中行焦点列的显示文本（对齐主线点选单元格复制）。"""
        if column not in _COPY_COLUMNS or not (0 <= row < len(self._rows)):
            return
        row_data = self._rows[row]
        if row_data["rowType"] != "item":
            return
        QApplication.clipboard().setText(str(row_data.get(column, "") or ""))

    @pyqtSlot("QVariantList", result=bool)
    def selectByPath(self, original_path) -> bool:
        """按 YAML 原始路径定位物品行（供 YAML 编辑器跳转）。"""
        target = tuple(str(p) for p in (original_path or []))
        if not target:
            return False
        for index, row in enumerate(self._rows):
            if row["rowType"] != "item":
                continue
            item = self._all_items[row["itemIndex"]]
            if tuple(str(p) for p in (item.get("original_path") or [])) == target:
                # 确保祖先组展开
                changed = False
                for key in (row["containerKey"], row["typeKey"]):
                    if key in self._collapsed:
                        self._collapsed.discard(key)
                        changed = True
                if changed:
                    self._rebuild_rows()
                    for new_index, new_row in enumerate(self._rows):
                        if new_row["rowType"] == "item" and new_row["itemIndex"] == row["itemIndex"]:
                            index = new_index
                            break
                self.selectedRowChanged.emit(index)
                return True
        # 物品存在但被筛选隐藏：清筛选后重试一次
        if any(tuple(str(p) for p in (item.get("original_path") or [])) == target
               for item in self._all_items):
            self.clearFilters()
            return self.selectByPath(original_path)
        return False

    selectedRowChanged = pyqtSignal(int)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _flag_value(self) -> str:
        if 0 <= self._flag_index < len(self._flag_labels):
            return self._flag_labels[self._flag_index].split(" ", 1)[0]
        return "3"

    def _default_flag_index(self) -> int:
        target = self._flags.get("3")
        for index, label in enumerate(self._flag_labels):
            if label == target:
                return index
        return 0

    def _item_at(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows) and self._rows[row]["rowType"] == "item":
            return self._all_items[self._rows[row]["itemIndex"]]
        return None

    @staticmethod
    def _slot_sort_key(item: dict[str, Any]):
        slot = str(item.get("slot", ""))
        if slot.startswith("slot_"):
            try:
                return (0, int(slot.removeprefix("slot_")))
            except ValueError:
                pass
        return (1, str(item.get("name", "")))

    def _filter_state(self):
        active = [(key, str(value)) for key, value in self._filter_values.items() if value is not None]
        return (self._search_text.strip().casefold(), active, self._level_min, self._level_max)

    def _rebuild_rows(self) -> None:
        state = self._filter_state()
        defaults = self.strings.get("defaults", {})
        items_by_container: dict[str, dict[str, list[int]]] = {}
        for index, item in enumerate(self._all_items):
            container_name = self._container_display(item.get("container"))
            item_type = str(item.get("type") or defaults.get("unknown_type", "Unknown"))
            items_by_container.setdefault(container_name, {}).setdefault(item_type, []).append(index)

        collapsed_defaults = {
            self.strings.get("containers", {}).get("Lost Loot", "Lost Loot"),
            self.strings.get("containers", {}).get("Equipped", "Equipped"),
        }
        # 与主线一致：仅在数据重载时默认折叠，用户手动展开不被筛选重建撤销
        if not getattr(self, "_defaults_collapsed", False):
            for name in collapsed_defaults:
                self._collapsed.add(f"c:{name}")
            self._defaults_collapsed = True
        rows: list[dict[str, Any]] = []
        for container_name in sorted(items_by_container):
            container_key = f"c:{container_name}"
            container_shown = 0
            container_rows: list[dict[str, Any]] = []
            for item_type in sorted(items_by_container[container_name]):
                indices = items_by_container[container_name][item_type]
                visible_indices = []
                for index in sorted(indices, key=lambda i: self._slot_sort_key(self._all_items[i])):
                    item = self._all_items[index]
                    values = prepare_item_search(
                        item, container_name, self._flag_display(item.get("state_flags")))
                    if matches_item_search(values, *state):
                        visible_indices.append(index)
                if not visible_indices:
                    continue
                type_key = f"t:{container_name}/{item_type}"
                container_rows.append({
                    "rowType": "type", "key": type_key,
                    "text": f"{item_type} ({len(visible_indices)})",
                    "depth": 1, "expanded": type_key not in self._collapsed,
                    "containerKey": container_key, "typeKey": type_key,
                })
                if type_key not in self._collapsed:
                    for index in visible_indices:
                        item = self._all_items[index]
                        container_rows.append({
                            "rowType": "item", "key": f"i:{index}",
                            "depth": 2, "itemIndex": index,
                            "name": str(item.get("name", "") or ""),
                            "type": str(item.get("type", "") or ""),
                            "manufacturer": str(item.get("manufacturer", "") or ""),
                            "rarity": str(item.get("rarity", "") or ""),
                            "level": str(item.get("level", "") or ""),
                            "flags": self._flag_display(item.get("state_flags", "")),
                            "serial": str(item.get("serial", "") or ""),
                            "containerKey": container_key, "typeKey": type_key,
                        })
                container_shown += len(visible_indices)
            if container_shown:
                rows.append({
                    "rowType": "container", "key": container_key,
                    "text": container_name, "depth": 0,
                    "expanded": container_key not in self._collapsed,
                    "containerKey": container_key, "typeKey": "",
                })
                if container_key not in self._collapsed:
                    rows.extend(container_rows)
        self._rows = rows
        self.dataChanged.emit()
