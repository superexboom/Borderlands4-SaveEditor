from PyQt6 import QtWidgets, QtCore, QtGui
import pandas as pd
import math
import random
import re
import sys
from functools import partial

from core import bl4_functions as bl4f
from core import b_encoder
from core import decoder_logic
from core import item_display_resolver
from core import resource_loader
from tabs.qt_catalog_picker import CatalogPicker, ContainedWheelListWidget, ContainedWheelScrollArea


# Rarity tier fills for the backpack row underlay. Keys match the base rarity
# emitted by _get_rarity_and_weapon_name (the weapon_rarity_df "Stat" value).
# This is the bottom layer: it shows as the thin border around the dark plate
# and through the weapon-shaped holes in the type icon.
# 背包行底衬的稀有度层级填充色。键名与 _get_rarity_and_weapon_name 返回的
# 基础稀有度（weapon_rarity_df 的 "Stat" 值）一致。此为底层：在暗色板四周
# 显示为细边框，并透过类型图标中武器形状的镂空显现。
_ROW_RARITY_COLORS = {
    "Common":    "#B0BEC5",
    "Uncommon":  "#4CAF50",
    "Rare":      "#2196F3",
    "Epic":      "#9C27B0",
    "Legendary": "#FF9800",
    "Pearl":     "#00E5FF",  # Pearlescent — one tier above Legendary in BL4
}

# Dark plate laid over the rarity fill: ~94% opaque so a hint of rarity bleeds
# through (matching the icon's α≈240 interior), inset a couple px so the fill
# rims it as a border. Keeps row text legible on every tier.
# 覆于稀有度填充之上的暗色板：约 94% 不透明，使少许稀有度色透出（与图标
# α≈240 的内部一致），并内缩数像素，使填充色沿边缘形成边框。让各等级的
# 行文字均保持清晰。
_ROW_PLATE_COLOR = QtGui.QColor(16, 22, 27, 240)
_ROW_PLATE_INSET = 2
_ROW_OUTER_RADIUS = 8
_ROW_INNER_RADIUS = 6
_ROW_ICON_MAX = 50  # cap the weapon icon so it stays reasonable on taller cards

# Pearlescent iridescent fill: the in-game Pearl palette (orange, teal,
# magenta, gold). Painted as a repeating gradient with a fixed pixel period,
# tilted so the bands run ~20° above horizontal regardless of row width.
# 珠光虹彩填充：游戏内 Pearl 色板（橙、青、洋红、金）。以固定像素周期的重复
# 渐变绘制，倾斜使色带无论行宽都约在水平线上方 20° 走向。
_PEARL_PALETTE = ("#FF8A65", "#4DD0E1", "#F06292", "#FFEE58")
_PEARL_BAND_DEG = 20      # band tilt above horizontal
_PEARL_BAND_PERIOD = 120  # px for one full 4-colour cycle along the gradient
_PEARL_PHASE = 0.5        # 0..1 shift of the bands along the vector, so teal
                          # (not gold) lands at the left edge under the weapon —
                          # keeps Pearl from reading gold like Legendary

# Weapon-type icon per type_en. These are dark plates with the weapon shape
# punched out as transparent holes, so over the rarity fill the weapon takes
# the rarity color while the plate stays dark.
# 按 type_en 对应的武器类型图标。这些是暗色板，武器形状镂空为透明孔洞，
# 因此覆于稀有度填充上时，武器呈现稀有度色，而板体保持深色。
_ROW_WEAPON_ICONS = {
    "Pistol":        "assets/icons/pistol.png",
    "Assault Rifle": "assets/icons/assault_rifle.png",
    "SMG":           "assets/icons/smg.png",
    "Sniper":        "assets/icons/sniper.png",
    "Shotgun":       "assets/icons/shotgun.png",
}

# Icons are read-only and shared across every row; cache the QPixmap per type so
# rebuilding the backpack list doesn't re-stat and re-decode the same few PNGs
# once per weapon.
# 图标为只读且被所有行共享；按类型缓存 QPixmap，使重建背包列表时不必为每把
# 武器重复读取并解码同几张 PNG。
_ICON_CACHE = {}


def _weapon_icon(type_en):
    """Cached weapon-type icon QPixmap for type_en, or None if there is none."""
    if type_en not in _ICON_CACHE:
        rel = _ROW_WEAPON_ICONS.get(type_en or "")
        path = resource_loader.get_resource_path(rel) if rel else None
        _ICON_CACHE[type_en] = QtGui.QPixmap(str(path)) if path and path.exists() else None
    return _ICON_CACHE[type_en]


def _pearl_brush():
    """Repeating Pearl gradient whose bands run ~20° above horizontal.

    Uses logical (pixel) coordinates with a fixed period and RepeatSpread so
    the bands stay tight and consistent on a wide row. The gradient vector is
    perpendicular to the bands (band angle − 90°).
    重复珠光渐变，色带约在水平线上方 20° 走向。采用逻辑（像素）坐标、固定
    周期与 RepeatSpread，使宽行上色带保持紧密一致；渐变向量垂直于色带
    （色带角度 − 90°）。
    """
    ang = math.radians(_PEARL_BAND_DEG - 90.0)
    ux, uy = math.cos(ang), math.sin(ang)
    off = _PEARL_PHASE * _PEARL_BAND_PERIOD  # phase shift along the vector
    sx, sy = -off * ux, -off * uy
    grad = QtGui.QLinearGradient(sx, sy, sx + ux * _PEARL_BAND_PERIOD, sy + uy * _PEARL_BAND_PERIOD)
    grad.setCoordinateMode(QtGui.QGradient.CoordinateMode.LogicalMode)
    grad.setSpread(QtGui.QGradient.Spread.RepeatSpread)
    n = len(_PEARL_PALETTE)
    for i in range(n + 1):
        grad.setColorAt(i / n, QtGui.QColor(_PEARL_PALETTE[i % n]))
    return QtGui.QBrush(grad)


class _RarityRow(QtWidgets.QWidget):
    """Backpack row painted as one dark plate over a rarity fill.

    The rarity fill (flat tier color, or the Pearl gradient) shows as the
    border around the inset plate and through the weapon shape, which is
    punched out of the single dark plate so the weapon reads in the tier
    color. Text/stat labels are child widgets laid over the plate.
    背包行绘制为覆于稀有度填充上的单块暗色板。稀有度填充（扁平层级色或珠光
    渐变）在内缩色板四周显现为边框，并透过从单块暗色板中镂空的武器形状显现，
    使武器呈现层级色。文字/属性标签为覆于色板之上的子部件。
    """

    def __init__(self, rarity, type_en, parent=None):
        super().__init__(parent)
        self._is_pearl = rarity == "Pearl"
        self._rarity_color = _ROW_RARITY_COLORS.get(rarity)
        self._icon = _weapon_icon(type_en) if (self._rarity_color or self._is_pearl) else None

    def paintEvent(self, event):
        if not (self._rarity_color or self._is_pearl):
            return
        w, h = self.width(), self.height()
        inset = _ROW_PLATE_INSET
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # 1. rarity fill (border + weapon-hole reveal layer)
        outer = QtCore.QRectF(0, 0, w, h)
        fill = _pearl_brush() if self._is_pearl else QtGui.QBrush(QtGui.QColor(self._rarity_color))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(outer, _ROW_OUTER_RADIUS, _ROW_OUTER_RADIUS)

        # 2. build the dark plate on its own layer with the weapon cut out, then
        #    lay it over the rarity fill. Cutting on a separate layer (rather
        #    than erasing the composited surface) means the weapon hole reveals
        #    the rarity fill beneath, not the widget's background.
        pw, ph = w - 2 * inset, h - 2 * inset
        plate = QtGui.QPixmap(pw, ph)
        plate.fill(QtCore.Qt.GlobalColor.transparent)
        pp = QtGui.QPainter(plate)
        pp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pp.setPen(QtCore.Qt.PenStyle.NoPen)
        pp.setBrush(_ROW_PLATE_COLOR)
        pp.drawRoundedRect(QtCore.QRectF(0, 0, pw, ph), _ROW_INNER_RADIUS, _ROW_INNER_RADIUS)
        if self._icon is not None and not self._icon.isNull():
            side = min(ph - 4, _ROW_ICON_MAX)
            icon = self._icon.scaled(
                side, side,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            # Icon is a dark plate with the weapon transparent. Source mode
            # replaces the plate pixels inside the icon rect with the icon's
            # own alpha: the dark surround stays, the weapon becomes a
            # transparent gap that reveals the rarity fill beneath. Clip to a
            # rounded rect so the icon art's corner-bracket flourishes fall
            # outside and stay dark — only the central weapon reveals rarity.
            ix = 6
            iy = (ph - icon.height()) / 2
            icon_rect = QtCore.QRectF(ix, iy, icon.width(), icon.height())
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(icon_rect, icon.width() * 0.30, icon.height() * 0.30)
            pp.save()
            pp.setClipPath(clip)
            pp.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)
            pp.drawPixmap(int(ix), int(iy), icon)
            pp.restore()
        pp.end()
        p.drawPixmap(inset, inset, plate)
        p.end()


class WeaponEditorTab(QtWidgets.QWidget):
    add_to_backpack_requested = QtCore.pyqtSignal(str, str)
    update_item_requested = QtCore.pyqtSignal(dict)
    
    # Part type color mapping based on QSS stylesheet
    PART_TYPE_COLORS = {
        # English
        "Barrel": "#B0BEC5",
        "Barrel Accessory": "#90A4AE",
        "Body": "#BCAAA4",
        "Body Accessory": "#A1887F",
        "Foregrip": "#9CCC65",
        "Grip": "#AED581",
        "Magazine": "#FFB300",
        "Magazine Accessory": "#FFCA28",
        "Manufacturer Part": "#9FA8DA",
        "Scope": "#4DD0E1",
        "Scope Accessory": "#26C6DA",
        "Stat Modifier": "#F06292",
        "Underbarrel": "#BCAAA4",
        "Underbarrel Accessory": "#A1887F",
        "Elemental": "#EF9A9A",
        "Element": "#EF9A9A",
        "Element Switch": "#EF9A9A",
        "Underbarrel Element Switch": "#EF9A9A",
        "Pearl Elements": "#80CBC4",
        "Pearl Stat": "#CE93D8",
        "Element": "#EF9A9A",
        "Skin": "#FFEA00",
        "Rarity": "#B39DDB",
        "Legendary": "#FF8A65",
        # Chinese
        "枪管": "#B0BEC5",
        "枪管附件": "#90A4AE",
        "枪身": "#BCAAA4",
        "枪身附属": "#A1887F",
        "前握把": "#9CCC65",
        "后握把/枪托": "#AED581",
        "弹匣": "#FFB300",
        "弹匣附件": "#FFCA28",
        "厂商授权部件": "#9FA8DA",
        "瞄准镜": "#4DD0E1",
        "瞄准镜附件": "#26C6DA",
        "属性修改组件": "#F06292",
        "下挂": "#BCAAA4",
        "下挂附件": "#A1887F",
        "元素": "#EF9A9A",
        "常规元素": "#EF9A9A",
        "元素切换": "#EF9A9A",
        "元素下挂切换": "#EF9A9A",
        "珠光元素": "#80CBC4",
        "珠光属性": "#CE93D8",
        "皮肤": "#FFEA00",
        "稀有度": "#B39DDB",
        "传奇": "#FF8A65",
        # Russian
        "Стихия": "#EF9A9A",
        "Скин": "#FFEA00",
        # Ukrainian  
        "Стихія": "#EF9A9A",
        "Скін": "#FFEA00",
    }

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.selected_weapon_path = None
        self.parts_data = []
        self.rarity_part = None
        
        self.all_weapon_parts_df = None
        self.elemental_df = None
        self.skin_df = None
        self.weapon_rarity_df = None
        self.weapon_localization = {}
        
        self.is_handling_change = False
        self.current_lang = 'zh-CN'
        
        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.content_widget = None

        self.load_data(self.current_lang)
        self.create_widgets()

    def load_data(self, lang='zh-CN'):
        try:
            suffix = "_EN" if lang in ['en-US', 'ru', 'ua'] else ""

            # Helper to get path with fallback
            def get_path(base_name):
                # Try with suffix first
                name_with_suffix = base_name.replace('.csv', f'{suffix}.csv')
                path = resource_loader.get_weapon_data_path(name_with_suffix)
                if path and path.exists():
                    return path
                # Fallback to base
                return resource_loader.get_weapon_data_path(base_name)

            self.all_weapon_parts_df = pd.read_csv(get_path('all_weapon_part.csv'))
            self.elemental_df = pd.read_csv(resource_loader.get_weapon_data_path('elemental.csv'))
            self.elemental_stat_col = 'Stat_ZH' if lang == 'zh-CN' else 'Stat'
            self.skin_df = pd.read_csv(resource_loader.get_weapon_data_path('skin.csv'))
            self.skin_df['Skin_ID'] = self.skin_df['Skin_ID'].astype(str)
            self.skin_stat_col = 'Stat_EN' if lang in ['en-US', 'ru', 'ua'] else 'Stat'
            self.weapon_rarity_df = pd.read_csv(get_path('weapon_rarity.csv'))
            self.rarity_desc_col = 'Description_ZH' if lang == 'zh-CN' else 'Description'
            
            self.weapon_localization = {}
            if lang == 'zh-CN':
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}
            
            # Load UI localization
            loc_file = resource_loader.get_ui_localization_file(lang)
            full_loc = resource_loader.load_json_resource(loc_file) or {}
            self.ui_localization = full_loc.get("weapon_editor_tab", {})
            
            # Re-enable if data loaded successfully (in case it was disabled previously)
            self.setEnabled(True)
            
        except FileNotFoundError as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Missing required file: {e}")
            self.setEnabled(False)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"An error occurred while loading data: {e}")
            self.setEnabled(False)

    def update_language(self, lang):
        print(f"DEBUG: Updating language for {self.__class__.__name__} to {lang}...")
        self.current_lang = lang
        self.load_data(lang)
        
        # Save current state
        current_decoded = self.serial_decoded_entry.text() if hasattr(self, 'serial_decoded_entry') else ""
        current_flag_idx = self.flag_combo.currentIndex() if hasattr(self, 'flag_combo') else 0
        current_weapon_path = self.selected_weapon_path
        
        # Clean up internal state
        self.parts_data = []
        self.rarity_part = None
        self.selected_weapon_path = current_weapon_path
        
        self.create_widgets()
        self.refresh_backpack_items()
        
        # Restore state
        if hasattr(self, 'flag_combo') and self.flag_combo.count() > current_flag_idx:
            self.flag_combo.setCurrentIndex(current_flag_idx)
            
        # If there was data loaded, reload it to refresh text
        if current_decoded:
             self.serial_decoded_entry.setText(current_decoded) # Set text first so it's available if parse fails
             self.parse_and_display_weapon(current_decoded)
        print(f"DEBUG: Finished updating language for {self.__class__.__name__}.")

    def create_widgets(self):
        # Clean up old content
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.content_widget = None

        # Create new content widget
        self.content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        self.main_layout.addWidget(self.content_widget)

        # Horizontal split: backpack browser as a tall vertical card column on
        # the left, the editor (serial / actions / meta / parts) scrollable on
        # the right. Draggable divider so the user can rebalance.
        # 水平分割：左侧为高的垂直卡片列（背包浏览器），右侧为可滚动的编辑器
        # （序列 / 操作 / 元数据 / 部件）。分隔条可拖动以重新分配空间。
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        content_layout.addWidget(splitter)

        # --- Left column: backpack browser ---
        bp_frame = QtWidgets.QFrame(); bp_frame.setObjectName("InnerFrame")
        bp_layout = QtWidgets.QVBoxLayout(bp_frame)
        bp_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("load_from_backpack")))
        self.weapon_search = QtWidgets.QLineEdit()
        self.weapon_search.setClearButtonEnabled(True)
        self.weapon_search.setPlaceholderText(self._loc('labels', 'search_weapon_placeholder', "Search name, manufacturer, type, level, or slot"))
        self.weapon_search.textChanged.connect(self._filter_backpack_items)
        bp_layout.addWidget(self.weapon_search)
        self.backpack_items_list = ContainedWheelListWidget()
        self.backpack_items_list.setObjectName("weaponBrowser")
        self.backpack_items_list.setMinimumWidth(300)
        self.backpack_items_list.itemActivated.connect(lambda item: self.load_weapon_data(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        self.backpack_items_list.itemClicked.connect(lambda item: self.load_weapon_data(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        bp_layout.addWidget(self.backpack_items_list, 1)  # fills the column height
        self.selected_weapon_summary = QtWidgets.QLabel()
        self.selected_weapon_summary.setObjectName("selectedWeaponSummary")
        self.selected_weapon_summary.setWordWrap(True)
        self._update_selected_weapon_summary()
        bp_layout.addWidget(self.selected_weapon_summary)
        splitter.addWidget(bp_frame)

        # --- Right: scrollable editor ---
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        splitter.addWidget(scroll_area)

        main_frame = QtWidgets.QFrame()
        scroll_area.setWidget(main_frame)
        layout = QtWidgets.QGridLayout(main_frame)
        layout.setColumnStretch(0, 1)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)  # Align all items to top

        splitter.setStretchFactor(0, 0)  # left column keeps its width
        splitter.setStretchFactor(1, 1)  # editor absorbs extra space
        splitter.setSizes([380, 820])

        s_frame = QtWidgets.QFrame(); s_frame.setObjectName("InnerFrame")
        s_layout = QtWidgets.QGridLayout(s_frame)
        s_layout.setColumnStretch(1, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_b85")), 0, 0)
        self.serial_b85_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_b85_entry, 0, 1)
        s_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("serial_decoded")), 1, 0)
        self.serial_decoded_entry = QtWidgets.QLineEdit()
        s_layout.addWidget(self.serial_decoded_entry, 1, 1)
        layout.addWidget(s_frame, 0, 0)

        act_frame = QtWidgets.QFrame()
        act_layout = QtWidgets.QGridLayout(act_frame)
        self.update_weapon_btn = QtWidgets.QPushButton(self.get_localized_string("update_weapon"))
        self.add_to_backpack_btn = QtWidgets.QPushButton(self.get_localized_string("add_to_backpack"))
        self.flag_combo = QtWidgets.QComboBox()
        
        # Load flags from UI localization
        flags = resource_loader.get_flag_labels(self.current_lang)
        self.flag_combo.addItems([flags[k] for k in ("1", "3", "5", "17", "33", "65", "129")])
            
        act_layout.addWidget(self.update_weapon_btn, 0, 0)
        act_layout.addWidget(self.add_to_backpack_btn, 0, 1)
        act_layout.addWidget(self.flag_combo, 0, 2)
        layout.addWidget(act_frame, 1, 0)
        
        editor_frame = QtWidgets.QFrame(); editor_frame.setObjectName("InnerFrame")
        editor_layout = QtWidgets.QGridLayout(editor_frame)
        for i in range(5): editor_layout.setColumnStretch(i, 1)
        
        labels = ["manufacturer", "weapon_type", "rarity", "level", "seed"]
        for i, lbl_key in enumerate(labels):
            editor_layout.addWidget(QtWidgets.QLabel(self.get_localized_string(lbl_key)), 0, i, QtCore.Qt.AlignmentFlag.AlignCenter)

        self.manufacturer_entry = QtWidgets.QLineEdit(); self.manufacturer_entry.setReadOnly(True)
        editor_layout.addWidget(self.manufacturer_entry, 1, 0)
        self.item_type_entry = QtWidgets.QLineEdit(); self.item_type_entry.setReadOnly(True)
        editor_layout.addWidget(self.item_type_entry, 1, 1)
        self.rarity_combo = QtWidgets.QComboBox()
        rarity_values = [self.get_localized_string(r) for r in ["Common", "Uncommon", "Rare", "Epic"]]
        self.rarity_combo.addItems(rarity_values)
        editor_layout.addWidget(self.rarity_combo, 1, 2)
        self.level_entry = QtWidgets.QLineEdit()
        self.level_entry.setValidator(QtGui.QIntValidator(1, 100))
        editor_layout.addWidget(self.level_entry, 1, 3)
        
        seed_layout = QtWidgets.QGridLayout()
        seed_frame = QtWidgets.QFrame(); seed_frame.setLayout(seed_layout)
        self.seed_entry = QtWidgets.QLineEdit(); self.seed_entry.setValidator(QtGui.QIntValidator())
        seed_layout.addWidget(self.seed_entry, 0, 0)
        self.random_seed_btn = QtWidgets.QPushButton("🎲"); self.random_seed_btn.setFixedWidth(40)
        seed_layout.addWidget(self.random_seed_btn, 0, 1)
        editor_layout.addWidget(seed_frame, 1, 4)
        
        self.weapon_name_label_str = self.get_localized_string("weapon_name_label")
        self.weapon_name_label = QtWidgets.QLabel(self.weapon_name_label_str)
        self.weapon_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        editor_layout.addWidget(self.weapon_name_label, 2, 0, 1, 5)

        stats_layout = QtWidgets.QGridLayout()
        stats_loc = self.ui_localization.get('stats', {})
        self.weapon_stat_value_labels = {}
        for index, key in enumerate(item_display_resolver.WEAPON_STAT_KEYS):
            row, column = divmod(index, 4)
            title_row = row * 2
            title = QtWidgets.QLabel(stats_loc.get(key, key.replace('_', ' ').title()))
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            title.setWordWrap(True)
            value = QtWidgets.QLabel("—")
            value.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            value.setMinimumWidth(72)
            value.setObjectName("WeaponStatValue")
            stats_layout.addWidget(title, title_row, column)
            stats_layout.addWidget(value, title_row + 1, column)
            stats_layout.setColumnStretch(column, 1)
            self.weapon_stat_value_labels[key] = value
        editor_layout.addLayout(stats_layout, 3, 0, 1, 5)
        layout.addWidget(editor_frame, 2, 0)
        
        parts_frame = QtWidgets.QFrame(); parts_frame.setObjectName("InnerFrame")
        parts_layout = QtWidgets.QVBoxLayout(parts_frame)
        
        parts_header_frame = QtWidgets.QFrame()
        parts_header_layout = QtWidgets.QGridLayout(parts_header_frame)
        parts_header_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("weapon_parts")), 0, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        parts_header_layout.setColumnStretch(0, 1)
        self.refresh_parts_btn = QtWidgets.QPushButton()
        self.refresh_parts_btn.setObjectName("PartActionButton")
        self.refresh_parts_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_parts_btn.setFixedSize(34, 34)
        self.refresh_parts_btn.setToolTip(self._loc('tooltips', 'refresh_parts', "Refresh parts"))
        parts_header_layout.addWidget(self.refresh_parts_btn, 0, 1, QtCore.Qt.AlignmentFlag.AlignRight)
        self.add_part_btn = QtWidgets.QPushButton(self.get_localized_string("add_part")); self.add_part_btn.setMinimumWidth(100)
        parts_header_layout.addWidget(self.add_part_btn, 0, 2, QtCore.Qt.AlignmentFlag.AlignRight)
        self.add_skin_btn = QtWidgets.QPushButton(self.get_localized_string("add_skin")); self.add_skin_btn.setMinimumWidth(100)
        parts_header_layout.addWidget(self.add_skin_btn, 0, 3, QtCore.Qt.AlignmentFlag.AlignRight)
        parts_layout.addWidget(parts_header_frame)
        
        # Parts list container - no independent scroll, uses page scroll
        parts_list_content = QtWidgets.QWidget()
        self.parts_list_layout = QtWidgets.QVBoxLayout(parts_list_content)
        self.parts_list_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.parts_list_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_list_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("parse_serial_to_show_parts")))
        parts_layout.addWidget(parts_list_content)
        layout.addWidget(parts_frame, 3, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        main_frame.setLayout(layout) # Set the grid layout to the main frame
        
        self.serial_b85_entry.textChanged.connect(self.handle_b85_change)
        self.serial_decoded_entry.textChanged.connect(self.handle_decoded_change)
        self.serial_decoded_entry.textChanged.connect(self._update_weapon_stats)
        self.rarity_combo.currentIndexChanged.connect(self.update_decoded_from_ui)
        self.level_entry.textChanged.connect(self.update_decoded_from_ui)
        self.seed_entry.textChanged.connect(self.update_decoded_from_ui)
        self.random_seed_btn.clicked.connect(self.randomize_seed)
        self.update_weapon_btn.clicked.connect(self.update_weapon)
        self.add_to_backpack_btn.clicked.connect(self.add_new_weapon_to_backpack)
        self.refresh_parts_btn.clicked.connect(self.force_refresh_parts)
        self.add_part_btn.clicked.connect(self.open_add_part_window)
        self.add_skin_btn.clicked.connect(lambda: self.open_select_skin_window(None))

    def _loc(self, section, key, en, **fmt):
        """Read weapon_editor_tab.<section>.<key> for the active language,
        falling back to the English literal (never Chinese or a raw key), then
        apply any format params. Used for strings that were previously inline
        zh-CN/else conditionals, so all four languages resolve from the JSON.
        按当前语言读取 weapon_editor_tab.<section>.<key>，缺失时回退到英文字面量
        （绝不显示中文或原始键），再套用格式参数。用于此前内联的 zh-CN/else
        条件字符串，使四种语言均从 JSON 解析。"""
        text = self.ui_localization.get(section, {}).get(key) or en
        return text.format(**fmt) if fmt else text

    def get_localized_string(self, key, default=''):
        # Check UI localization first (flattened check or mapped)
        # We map keys to sections in ui_localization
        if not self.ui_localization:
             return self.weapon_localization.get(key, default or key)
             
        # Map common keys to UI structure
        ui_map = {
            # Labels
            "load_from_backpack": self.ui_localization.get('labels', {}).get('load_from_backpack'),
            "decrypt_save_to_show_weapons": self.ui_localization.get('labels', {}).get('decrypt_save_to_show_weapons'),
            "serial_b85": self.ui_localization.get('labels', {}).get('serial_b85'),
            "serial_decoded": self.ui_localization.get('labels', {}).get('serial_decoded'),
            "manufacturer": self.ui_localization.get('labels', {}).get('manufacturer'),
            "weapon_type": self.ui_localization.get('labels', {}).get('weapon_type'),
            "rarity": self.ui_localization.get('labels', {}).get('rarity'),
            "level": self.ui_localization.get('labels', {}).get('level'),
            "seed": self.ui_localization.get('labels', {}).get('seed'),
            "weapon_name_label": self.ui_localization.get('labels', {}).get('weapon_name_label'),
            "weapon_parts": self.ui_localization.get('labels', {}).get('weapon_parts'),
            "parts_list": self.ui_localization.get('labels', {}).get('parts_list'),
            "parse_serial_to_show_parts": self.ui_localization.get('labels', {}).get('parse_serial_to_show_parts'),
            "level_label": self.ui_localization.get('labels', {}).get('level_label'),
            "slot_label": self.ui_localization.get('labels', {}).get('slot_label'),
            
            # Buttons
            "update_weapon": self.ui_localization.get('buttons', {}).get('update_weapon'),
            "add_to_backpack": self.ui_localization.get('buttons', {}).get('add_to_backpack'),
            "add_part": self.ui_localization.get('buttons', {}).get('add_part'),
            "add_skin": self.ui_localization.get('buttons', {}).get('add_skin'),
            "confirm_add": self.ui_localization.get('buttons', {}).get('confirm_add'),
            
            # Dialogs/Messages
            "error": self.ui_localization.get('dialogs', {}).get('error'),
            "no_weapons_in_backpack": self.ui_localization.get('dialogs', {}).get('no_weapons_in_backpack'),
            "no_valid_decoded_data": self.ui_localization.get('dialogs', {}).get('no_valid_decoded_data'),
            "parse_error": self.ui_localization.get('dialogs', {}).get('parse_error'),
            "parse_weapon_error": self.ui_localization.get('dialogs', {}).get('parse_weapon_error'),
            "parts_not_found": self.ui_localization.get('dialogs', {}).get('parts_not_found'),
            "no_selection": self.ui_localization.get('dialogs', {}).get('no_selection'),
            "select_weapon_first": self.ui_localization.get('dialogs', {}).get('select_weapon_first'),
            "encoding_fail": self.ui_localization.get('dialogs', {}).get('encoding_fail'),
            "cannot_reencode_serial": self.ui_localization.get('dialogs', {}).get('cannot_reencode_serial'),
            "cannot_encode_serial": self.ui_localization.get('dialogs', {}).get('cannot_encode_serial'),
            "success": self.ui_localization.get('dialogs', {}).get('success'),
            "no_input": self.ui_localization.get('dialogs', {}).get('no_input'),
            "serial_empty": self.ui_localization.get('dialogs', {}).get('serial_empty'),
            "no_weapon": self.ui_localization.get('dialogs', {}).get('no_weapon'),
            "load_weapon_first": self.ui_localization.get('dialogs', {}).get('load_weapon_first'),
            "add_part_title": self.ui_localization.get('dialogs', {}).get('add_part_title'),
            "select_parts_to_add": self.ui_localization.get('dialogs', {}).get('select_parts_to_add'),
            "cannot_determine_mfg": self.ui_localization.get('dialogs', {}).get('cannot_determine_mfg'),
            "Select Skin": self.ui_localization.get('dialogs', {}).get('select_skin_title'),
            "Select a skin to apply": self.ui_localization.get('dialogs', {}).get('select_skin_msg'),
            "update_success": self.ui_localization.get('dialogs', {}).get('update_success'),
            
            # Misc
            "Skin": self.ui_localization.get('misc', {}).get('skin'),
            "Elemental": self.ui_localization.get('misc', {}).get('elemental'),
            "elements": self.ui_localization.get('misc', {}).get('elements'),
            "element_switch": self.ui_localization.get('misc', {}).get('element_switch'),
        }
        
        if key in ui_map and ui_map[key]:
            return ui_map[key]
            
        return self.weapon_localization.get(key, default or key)

    def handle_b85_change(self, text):
        if self.is_handling_change or not self.serial_b85_entry.hasFocus():
            return

        self.is_handling_change = True
        if not text:
            self.clear_all_fields()
            self.is_handling_change = False
            return

        decoded_str, _, err = decoder_logic.decode_serial_to_string(text)
        if not err:
            self.serial_decoded_entry.blockSignals(True)
            self.serial_decoded_entry.setText(decoded_str)
            self.serial_decoded_entry.blockSignals(False)
            self.parse_and_display_weapon(decoded_str)
            self.serial_b85_entry.setReadOnly(True)
            self.update_weapon_btn.setEnabled(True)
        else:
            self.serial_decoded_entry.clear()
        self.is_handling_change = False

    def handle_decoded_change(self, text):
        if not self.serial_decoded_entry.hasFocus():
            return
        self.update_b85_from_decoded()
        if not text:
            self.clear_all_fields(clear_b85=False)
            return
        self.parse_and_display_weapon(text)

    def update_b85_from_decoded(self):
        decoded_str = self.serial_decoded_entry.text()
        if not decoded_str: return
        new_b85, err = b_encoder.encode_to_base85(decoded_str)
        if not err:
            self.serial_b85_entry.blockSignals(True)
            self.serial_b85_entry.setText(new_b85)
            self.serial_b85_entry.blockSignals(False)

    def _get_rarity_and_weapon_name(self, parts, m_id, decoded_str=""):
        rarity, weapon_name, rarity_part, display_rarity, remaining_parts = "Unknown", "Unknown", None, "Unknown", list(parts)
        for p in parts:
            if not isinstance(p, dict) or p.get('type') != 'simple':
                continue
            part_id = p.get('id')
            if not part_id:
                continue
            part_details = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) & (self.all_weapon_parts_df['Part ID'] == part_id)]
            if not part_details.empty and part_details.iloc[0]['Part Type'] == 'Barrel':
                part_name = item_display_resolver.weapon_part_name(m_id, part_id, self.current_lang, part_details.iloc[0])
                if part_name:
                    weapon_name = part_name
                    if weapon_name.endswith(' Barrel'):
                        weapon_name = weapon_name[:-len(' Barrel')]
                    break
        simple_parts = [p for p in parts if isinstance(p, dict) and p.get('type') == 'simple']
        if simple_parts and 'id' in simple_parts[0]:
            rarity_info = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Part ID'] == simple_parts[0]['id'] )]
            if not rarity_info.empty:
                details = rarity_info.iloc[0]; rarity, desc = details['Stat'], details[self.rarity_desc_col]
                display_rarity = f"{rarity} - {desc}" if rarity in {"Legendary", "Pearl"} and pd.notna(desc) and desc else rarity
                rarity_part = simple_parts[0]
        if not rarity_part: display_rarity = rarity = "Legendary"
        pearl_ids = set(range(51, 61))
        if any(
            p.get('id') == 1
            and (
                p.get('sub_id') in pearl_ids
                or bool(pearl_ids.intersection(p.get('sub_ids', [])))
            )
            for p in parts
            if isinstance(p, dict) and p.get('type') in {'elemental', 'group'}
        ):
            suffix = display_rarity.split(' - ', 1)[1] if ' - ' in display_rarity else ''
            rarity = "Pearl"
            display_rarity = f"Pearl - {suffix}" if suffix else "Pearl"
        if rarity_part: remaining_parts = [p for p in remaining_parts if p is not rarity_part]
        if decoded_str:
            m_rows = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id]
            if not m_rows.empty:
                m_info = m_rows.iloc[0]
                display = item_display_resolver.resolve_item_display(
                    m_id,
                    str(m_info['Manufacturer']),
                    str(m_info['Weapon Type']),
                    decoded_str,
                    self.current_lang,
                )
                if display.get("display_source") != "fallback" and display.get("display_name"):
                    weapon_name = display["display_name"]
        return display_rarity, weapon_name, rarity_part, remaining_parts

    def _parse_component_string(self, component_str):
        components, last_index = [], 0
        for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")', component_str):
            components.append(component_str[last_index:match.start()])
            part_data = {'raw': match.group(0)}
            if match.group(3): part_data.update({'type': 'skin', 'id': int(match.group(3))})
            elif match.group(4): part_data.update({'type': 'skin', 'id': match.group(4)})
            else:
                outer_id, inner = int(match.group(1)), match.group(2)
                if inner: part_data.update({'type': 'group', 'id': outer_id, 'sub_ids': [int(sid) for sid in inner.strip('[]').split()]} if '[' in inner else {'type': 'elemental', 'id': outer_id, 'sub_id': int(inner)})
                else: part_data.update({'type': 'simple', 'id': outer_id})
            components.append(part_data); last_index = match.end()
        components.append(component_str[last_index:])
        return [c for c in components if c]

    def clear_all_fields(self, clear_b85=True):
        self.is_handling_change = True
        if clear_b85: self.serial_b85_entry.clear()
        self.serial_decoded_entry.clear(); self.manufacturer_entry.clear(); self.item_type_entry.clear()
        self.rarity_combo.setCurrentIndex(-1); self.level_entry.clear(); self.seed_entry.clear()
        self.weapon_name_label.setText(self.weapon_name_label_str)
        self._update_weapon_stats("")

        while self.parts_list_layout.count():
            item = self.parts_list_layout.takeAt(0)
            if (widget := item.widget()):
                widget.deleteLater()
            elif (layout := item.layout()):
                while layout.count():
                    sub_item = layout.takeAt(0)
                    if (sub_widget := sub_item.widget()):
                        sub_widget.deleteLater()

        self.parts_list_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("parse_serial_to_show_parts")))
        self.serial_b85_entry.setReadOnly(False); self.update_weapon_btn.setEnabled(False)
        self.selected_weapon_path, self.parts_data, self.rarity_part = None, [], None
        self._select_current_backpack_item()
        self._update_selected_weapon_summary()
        self.is_handling_change = False

    def update_decoded_from_ui(self):
        if self.is_handling_change: return
        current_decoded = self.serial_decoded_entry.text()
        if not current_decoded: return
        try:
            updated_str = bl4f.update_level_in_decoded_str(current_decoded, self.level_entry.text())
            parts = updated_str.split('|')
            if len(parts) > 1 and len(parts[1].split(',')) > 1:
                seed_parts = parts[1].split(','); seed_parts[1] = f" {self.seed_entry.text()}"; parts[1] = ",".join(seed_parts)
                updated_str = "|".join(parts)

            if self.rarity_part and self.rarity_combo.isEnabled():
                rarity_map = {self.get_localized_string(k): k for k in ["Common", "Uncommon", "Rare", "Epic"]}
                if rarity_en := rarity_map.get(self.rarity_combo.currentText()):
                    m_id = int(updated_str.split('||')[0].strip().split('|')[0].strip().split(',')[0])
                    info = self.weapon_rarity_df[(self.weapon_rarity_df['Manufacturer & Weapon Type ID'] == m_id) & (self.weapon_rarity_df['Stat'] == rarity_en) & (self.weapon_rarity_df['Part Type'] == 'Rarity')]
                    if not info.empty:
                        new_id = info.iloc[0]['Part ID']
                        updated_str = updated_str.replace(self.rarity_part['raw'], f"{{{new_id}}}")
                        self.rarity_part['id'], self.rarity_part['raw'] = new_id, f"{{{new_id}}}"

            if self.serial_decoded_entry.text() != updated_str: self.serial_decoded_entry.setText(updated_str)
        except Exception as e: self.main_app.log(f"Error in update_decoded_from_ui: {e}")

    def randomize_seed(self): self.seed_entry.setText(str(random.randint(100, 9999)))
    def load_weapon_data(self, weapon_data):
        if not weapon_data:
            return
        self.main_app.log(f"Loading weapon: {weapon_data.get('name')}")
        self.selected_weapon_path = weapon_data.get("original_path")
        self._select_current_backpack_item()
        self._update_selected_weapon_summary(weapon_data)
        self.is_handling_change = True
        self.serial_b85_entry.setText(weapon_data.get('serial', ''))
        decoded_str = weapon_data.get('decoded_full', '')
        self.serial_decoded_entry.setText(decoded_str)
        self.is_handling_change = False
        if not decoded_str:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("no_valid_decoded_data")); return
        self.parse_and_display_weapon(decoded_str)
        self.serial_b85_entry.setReadOnly(True); self.update_weapon_btn.setEnabled(True)

    def parse_and_display_weapon(self, decoded_str):
        try:
            header_part, component_part = decoded_str.split('||', 1)
            sections = header_part.strip().split('|')
            m_id, level = int(sections[0].strip().split(',')[0]), int(sections[0].strip().split(',')[3])
            m_info = self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id].iloc[0]
            self.is_handling_change = True
            self.manufacturer_entry.setText(self.get_localized_string(m_info['Manufacturer']))
            self.item_type_entry.setText(self.get_localized_string(m_info['Weapon Type']))
            self.level_entry.setText(str(level))
            self.seed_entry.setText(sections[1].strip().split(',')[1].strip() if len(sections) > 1 and len(sections[1].strip().split(',')) > 1 else "")
            
            temp_parts = self._parse_component_string(component_part)
            display_rarity, weapon_name, self.rarity_part, remaining_parts = self._get_rarity_and_weapon_name(temp_parts, m_id, decoded_str)
            
            rarity_parts = display_rarity.split(' - ')
            base_rarity, localized_base = rarity_parts[0], self.get_localized_string(rarity_parts[0])
            final_display_rarity = f"{localized_base} - {self.get_localized_string(rarity_parts[1], rarity_parts[1])}" if len(rarity_parts) > 1 else localized_base
            
            if base_rarity in {"Legendary", "Pearl"}:
                self.rarity_combo.setEditable(True); self.rarity_combo.lineEdit().setText(final_display_rarity); self.rarity_combo.setEnabled(False)
            else:
                self.rarity_combo.setEditable(False); self.rarity_combo.setEnabled(True)
                if (index := self.rarity_combo.findText(localized_base)) != -1: self.rarity_combo.setCurrentIndex(index)

            self.weapon_name_label.setText(f"{self.weapon_name_label_str} {weapon_name}")
            self._update_weapon_stats(decoded_str)
            self.parts_data = remaining_parts; self.display_parts(m_id)
            self.is_handling_change = False
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("parse_error"), f"{self.get_localized_string('parse_weapon_error')}: {e}")
            self.main_app.log(f"Error parsing weapon: {e}"); self.clear_all_fields()

    def _update_weapon_stats(self, decoded_str):
        if not hasattr(self, 'weapon_stat_value_labels'):
            return
        stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
        for key, label in self.weapon_stat_value_labels.items():
            label.setText(item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—")

    def display_parts(self, manufacturer_id):
        while self.parts_list_layout.count():
            item = self.parts_list_layout.takeAt(0)
            if (widget := item.widget()):
                widget.deleteLater()
            elif (layout := item.layout()):
                while layout.count():
                    sub_item = layout.takeAt(0)
                    if (sub_widget := sub_item.widget()):
                        sub_widget.deleteLater()

        if not self.parts_data:
            self.parts_list_layout.addWidget(QtWidgets.QLabel(self.get_localized_string("parts_not_found"))); return
        for i, part_info in enumerate(self.parts_data):
            if isinstance(part_info, str): continue
            frame = self._create_collapsible_part_frame(part_info, i) if part_info.get('type') == 'group' else self._create_simple_part_frame(part_info, manufacturer_id, i)
            if frame: self.parts_list_layout.addWidget(frame)

    def _create_simple_part_frame(self, part_info, m_id, index):
        frame = QtWidgets.QFrame(); frame.setObjectName('PartFrame')
        layout = QtWidgets.QVBoxLayout(frame); layout.setSpacing(5)
        part_id = part_info.get('id'); info = {'type': "未知", 'str': "", 'stat': "无属性变化"}
        is_skin, is_elemental = (part_info.get('type') == 'skin'), (part_info.get('type') == 'elemental')
        if is_skin:
            if not (d := self.skin_df[self.skin_df['Skin_ID'].str.lower() == str(part_id).lower()]).empty: info.update({'type': self.get_localized_string("Skin"), 'str': d.iloc[0][self.skin_stat_col], 'stat': self._loc('parts', 'cosmetic_part', "Cosmetic part")})
        elif is_elemental:
            if not (d := self.elemental_df[self.elemental_df['Part_ID'] == part_info['sub_id']]).empty:
                row = d.iloc[0]
                description = item_display_resolver.format_weapon_part_description(
                    1, str(part_info['sub_id']), self.serial_decoded_entry.text(), self.current_lang, "Elemental"
                )
                no_change = description in {"无属性变化", "No stat changes"}
                info.update({
                    'type': self.get_localized_string(self._elemental_part_type(row)),
                    'str': row[self.elemental_stat_col],
                    'stat': self._loc('parts', 'element_config', "Element configuration") if no_change else description,
                })
        else:
            d = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == m_id) & (self.all_weapon_parts_df['Part ID'] == part_id)]
            if not d.empty:
                row = d.iloc[0]
                name = item_display_resolver.weapon_part_name(m_id, part_id, self.current_lang, row)
                description = item_display_resolver.format_weapon_part_description(
                    m_id, part_id, self.serial_decoded_entry.text(), self.current_lang, str(row['Part Type'])
                )
                info.update({
                    'type': self.get_localized_string(row['Part Type']),
                    'str': name or (self._loc('parts', 'unnamed_barrel', "Unnamed Barrel") if str(row['Part Type']) == "Barrel" else ""),
                    'stat': description,
                })
        display_text = f"  {part_id}  " if not is_elemental else f"  {part_info['id']}:{part_info['sub_id']}  "
        header = QtWidgets.QHBoxLayout()
        id_label = QtWidgets.QLabel(display_text); id_label.setObjectName("PartIdBadge")
        type_color = self.PART_TYPE_COLORS.get(info['type'], "#e0e0e0")
        type_label = QtWidgets.QLabel(info['type']); type_label.setObjectName("PartTypeBadge"); type_label.setStyleSheet(f"color: {type_color}; border-color: {type_color};")
        header.addWidget(type_label)
        if info['str']:
            name_label = QtWidgets.QLabel(str(info['str'])); name_label.setObjectName("PartName"); name_label.setWordWrap(True)
            header.addWidget(name_label, 1)
        else:
            header.addStretch(1)
        header.addWidget(id_label); header.addWidget(self._add_action_buttons(index, is_skin))
        description_label = QtWidgets.QLabel(str(info['stat']) if pd.notna(info['stat']) else "")
        description_label.setObjectName("PartDescription"); description_label.setWordWrap(True)
        layout.addLayout(header); layout.addWidget(description_label)
        return frame

    def _create_collapsible_part_frame(self, part_info, index):
        container = QtWidgets.QFrame(); container.setObjectName('PartGroupFrame')
        container_layout = QtWidgets.QVBoxLayout(container); container_layout.setSpacing(0); container_layout.setContentsMargins(0,0,0,0)
        header, content = QtWidgets.QFrame(), QtWidgets.QFrame(); content.setVisible(True)
        header_layout, content_layout = QtWidgets.QGridLayout(header), QtWidgets.QVBoxLayout(content)
        group_id = part_info.get('id', 0); mfg_name = "未知厂商"
        if group_id != 1:
            try:
                mfg_name = self.get_localized_string(self.all_weapon_parts_df[self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == group_id].iloc[0]['Manufacturer'])
            except (IndexError, KeyError):
                pass
        toggle_btn = QtWidgets.QPushButton("▾"); toggle_btn.setObjectName("PartActionButton"); toggle_btn.setFixedSize(28, 28)
        toggle_btn.clicked.connect(lambda checked, b=toggle_btn, c=content: self._toggle_group_visibility(b, c))
        if group_id == 1:
            group_title = self._loc('parts', 'element_group', "Element Configuration Group · {n} parts", n=len(part_info.get('sub_ids', [])))
        else:
            group_title = self._loc('parts', 'licensed_group', "Licensed Part Group · {mfg} · {n} parts", mfg=mfg_name, n=len(part_info.get('sub_ids', [])))
        title_label = QtWidgets.QLabel(group_title); title_label.setObjectName("PartName")
        header_layout.addWidget(toggle_btn, 0, 0); header_layout.addWidget(title_label, 0, 1)
        header_layout.setColumnStretch(1, 1)
        action_buttons = self._add_action_buttons(index)
        header_layout.addWidget(action_buttons, 0, 2, QtCore.Qt.AlignmentFlag.AlignRight)
        for sub_id in part_info.get('sub_ids', []):
            sub_frame = QtWidgets.QFrame(); sub_frame.setObjectName("PartSubFrame")
            sub_layout = QtWidgets.QGridLayout(sub_frame); sub_layout.setColumnStretch(1, 1)
            id_label = QtWidgets.QLabel(f"  {sub_id}  "); id_label.setObjectName("PartIdBadge")
            sub_layout.addWidget(id_label, 0, 0)
            p_type, p_str, p_stat = "未知", "", "无属性变化"
            if group_id == 1:
                d = self.elemental_df[
                    (self.elemental_df['Elemental_ID'] == group_id)
                    & (self.elemental_df['Part_ID'] == sub_id)
                ]
                if not d.empty:
                    row = d.iloc[0]
                    description = item_display_resolver.format_weapon_part_description(
                        group_id, str(sub_id), self.serial_decoded_entry.text(), self.current_lang, "Elemental"
                    )
                    p_type = self.get_localized_string(self._elemental_part_type(row))
                    p_str = str(row[self.elemental_stat_col])
                    p_stat = self._loc('parts', 'element_config', "Element configuration") if description in {"无属性变化", "No stat changes"} else description
            else:
                d = self.all_weapon_parts_df[(self.all_weapon_parts_df['Manufacturer & Weapon Type ID'] == group_id) & (self.all_weapon_parts_df['Part ID'] == sub_id)]
                if not d.empty:
                    row = d.iloc[0]
                    name = item_display_resolver.weapon_part_name(group_id, sub_id, self.current_lang, row)
                    description = item_display_resolver.format_weapon_part_description(
                        group_id, sub_id, self.serial_decoded_entry.text(), self.current_lang, str(row['Part Type'])
                    )
                    p_type = self.get_localized_string(row['Part Type'])
                    p_str = name or (self._loc('parts', 'unnamed_barrel', "Unnamed Barrel") if str(row['Part Type']) == "Barrel" else "")
                    p_stat = description
            name_label = QtWidgets.QLabel(" · ".join(value for value in (p_type, p_str) if value)); name_label.setObjectName("PartName"); name_label.setWordWrap(True)
            stat_label = QtWidgets.QLabel(str(p_stat)); stat_label.setObjectName("PartDescription"); stat_label.setWordWrap(True)
            sub_layout.addWidget(name_label, 0, 1); sub_layout.addWidget(stat_label, 1, 1)
            content_layout.addWidget(sub_frame)
        content.setLayout(content_layout); container_layout.addWidget(header); container_layout.addWidget(content)
        return container
        
    def _add_action_buttons(self, index, is_skin=False):
        frame = QtWidgets.QFrame()
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        if is_skin:
            edit_btn = QtWidgets.QPushButton("✎"); edit_btn.setToolTip(self._loc('tooltips', 'change_skin', "Change skin")); edit_btn.clicked.connect(partial(self.open_select_skin_window, index)); layout.addWidget(edit_btn)
        else:
            up_btn = QtWidgets.QPushButton("↑"); up_btn.setToolTip(self._loc('tooltips', 'move_up', "Move up")); up_btn.clicked.connect(partial(self.move_part, index, -1)); layout.addWidget(up_btn)
            down_btn = QtWidgets.QPushButton("↓"); down_btn.setToolTip(self._loc('tooltips', 'move_down', "Move down")); down_btn.clicked.connect(partial(self.move_part, index, 1)); layout.addWidget(down_btn)
        del_btn = QtWidgets.QPushButton("✕"); del_btn.setObjectName("PartDeleteButton"); del_btn.setToolTip(self._loc('tooltips', 'remove_part', "Remove")); del_btn.clicked.connect(partial(self.delete_part, index)); layout.addWidget(del_btn)
        for button in frame.findChildren(QtWidgets.QPushButton):
            if button.objectName() != "PartDeleteButton": button.setObjectName("PartActionButton")
            button.setFixedSize(30, 30)
        return frame

    def move_part(self, index, direction):
        # parts_data interleaves whitespace separators with part dicts, so a raw
        # index±1 step often lands on a separator and moves nothing visible —
        # which is why moving a part took several clicks. Step over separators to
        # the adjacent real part and swap the two, so one click moves one part.
        # parts_data 中部件字典与空白分隔符交替，因此 index±1 的原始步进常落在
        # 分隔符上、视觉上毫无移动——这正是移动部件需点击多次的原因。跳过分隔符
        # 找到相邻的真实部件并交换二者，使一次点击移动一个部件。
        if not (0 <= index < len(self.parts_data)) or not isinstance(self.parts_data[index], dict):
            return
        target = index + direction
        while 0 <= target < len(self.parts_data) and not isinstance(self.parts_data[target], dict):
            target += direction
        if not 0 <= target < len(self.parts_data):
            return
        self.parts_data[index], self.parts_data[target] = self.parts_data[target], self.parts_data[index]
        self.regenerate_ui_and_serial()

    def delete_part(self, index):
        if 0 <= index < len(self.parts_data):
            self.parts_data.pop(index); self.regenerate_ui_and_serial()

    def regenerate_ui_and_serial(self):
        current_decoded = self.serial_decoded_entry.text()
        if '||' not in current_decoded: return
        header_part, _ = current_decoded.split('||', 1)
        try: m_id = int(header_part.strip().split('|')[0].strip().split(',')[0])
        except (ValueError, IndexError): return
        new_component_list = ([self.rarity_part['raw']] if self.rarity_part else []) + [p['raw'] if isinstance(p, dict) else p for p in self.parts_data]
        new_component_str = re.sub(r'\s{2,}', ' ', " ".join(new_component_list).strip())
        self.serial_decoded_entry.setText(f"{header_part.strip()}|| {new_component_str}")
        self.display_parts(m_id)

    def force_refresh_parts(self):
        if not (decoded_str := self.serial_decoded_entry.text()):
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty")); return
        self.main_app.log("Forcing parts list refresh..."); self.parse_and_display_weapon(decoded_str)
        QtWidgets.QMessageBox.information(self, self.get_localized_string("success"), self.get_localized_string("parts_refresh_success"))

    def _weapon_browser_row(self, title, detail, decoded_str, rarity=None, type_en=None):
        # Vertical card for the left-column browser: name, the legendary title
        # (the parenthetical) on its own line to save width, level·slot, then
        # the five stats as a distinct-column strip below. _RarityRow paints
        # the rarity plate, border and punched weapon icon behind it.
        # 左列浏览器的垂直卡片：名称、单独一行的传奇标题（括号内容，以节省宽度）、
        # 等级·槽位，下方为五项属性的独立列条。_RarityRow 在其后绘制稀有度
        # 色板、边框与镂空武器图标。
        row = _RarityRow(rarity, type_en)
        row.setObjectName("WeaponBrowserRow")
        left = 66 if row._icon is not None else 12

        outer = QtWidgets.QVBoxLayout(row)
        outer.setContentsMargins(left, _ROW_PLATE_INSET + 4, 10, _ROW_PLATE_INSET + 4)
        outer.setSpacing(0)

        # Split "Mfg Type (Legendary)" so the parenthetical drops to its own line.
        m = re.match(r'^(.*?)\s*\(([^()]*)\)\s*$', title)
        base_name, legendary = (m.group(1), m.group(2)) if m else (title, None)

        name_label = QtWidgets.QLabel(base_name)
        name_label.setObjectName("WeaponBrowserName")
        name_label.setToolTip(title)
        name_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.NoTextInteraction)
        outer.addWidget(name_label)

        if legendary:
            leg_label = QtWidgets.QLabel(f"({legendary})")
            leg_label.setObjectName("WeaponBrowserLegendary")
            # Tooltip so the (often long, especially RU/UA) legendary name is
            # recoverable when it clips in the narrow card column.
            leg_label.setToolTip(f"({legendary})")
            color = _ROW_RARITY_COLORS.get(rarity, "#cccccc")
            leg_label.setStyleSheet(f"color: {color}; font-style: italic; background: transparent;")
            outer.addWidget(leg_label)

        detail_label = QtWidgets.QLabel(detail)
        detail_label.setObjectName("WeaponBrowserMeta")
        outer.addWidget(detail_label)

        stats = item_display_resolver.resolve_weapon_stats(decoded_str) if decoded_str else {}
        stat_titles = self.ui_localization.get('stats', {})
        stat_strip = QtWidgets.QHBoxLayout()
        stat_strip.setContentsMargins(0, 4, 0, 0)
        stat_strip.setSpacing(6)
        for key in ("damage", "accuracy", "fire_rate", "reload_time", "magazine"):
            stat_layout = QtWidgets.QVBoxLayout()
            stat_layout.setContentsMargins(0, 0, 0, 0)
            stat_layout.setSpacing(0)
            # Short, per-language stat header that fits the narrow card column
            # (full localized names like RU "Скорострельность" overflow it).
            title_text = self._loc('stat_short', key, stat_titles.get(key, key.replace('_', ' ').title()))
            title_label = QtWidgets.QLabel(title_text)
            title_label.setObjectName("WeaponBrowserStatTitle")
            title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            value = item_display_resolver.format_weapon_stat(key, stats.get(key), self.current_lang) or "—"
            value_label = QtWidgets.QLabel(value)
            value_label.setObjectName("WeaponBrowserStatValue")
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            stat_layout.addWidget(title_label)
            stat_layout.addWidget(value_label)
            stat_strip.addLayout(stat_layout, 1)
        outer.addLayout(stat_strip)
        return row

    def refresh_backpack_items(self):
        self.backpack_items_list.clear()
        if self.main_app.controller.yaml_obj is None or not (items := self.main_app.controller.get_all_items()):
            self.backpack_items_list.addItem(self.get_localized_string("decrypt_save_to_show_weapons"))
            self.backpack_items_list.setEnabled(False)
            return
        
        weapon_types = {"Pistol", "Shotgun", "SMG", "Assault Rifle", "Sniper"}
        filtered = [i for i in items if i.get("type_en") in weapon_types and "Backpack" in i.get("container", "")]
        if not filtered:
            self.backpack_items_list.addItem(self.get_localized_string("no_weapons_in_backpack"))
            self.backpack_items_list.setEnabled(False)
            return

        self.backpack_items_list.setEnabled(True)

        for weapon in filtered:
            try:
                header, component = weapon.get('decoded_full', '').split('||', 1)
                m_id = int(header.strip().split('|')[0].strip().split(',')[0])
                parsed_components = self._parse_component_string(component)
                display_rarity, name, _, _ = self._get_rarity_and_weapon_name(parsed_components, m_id, weapon.get('decoded_full', ''))
                base_rarity = str(display_rarity).split(' - ')[0]
                w_name = self.get_localized_string(name, name)
                disp_name = f"{weapon.get('manufacturer', '未知')} {weapon.get('type', '未知物品')} ({w_name})" if w_name not in ["N/A", "Unknown", "未知"] else f"{weapon.get('manufacturer', '未知')} {weapon.get('type', '未知物品')}"
                detail = f"{self.get_localized_string('level_label')} {weapon.get('level', 'N/A')}  ·  {self.get_localized_string('slot_label')} {weapon.get('slot', 'N/A').replace('slot_', '')}"
                item = QtWidgets.QListWidgetItem()
                item.setData(QtCore.Qt.ItemDataRole.UserRole, weapon)
                item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, f"{weapon.get('name', '')} {disp_name} {detail}".lower())
                item.setToolTip(f"{disp_name} · {detail}")
                row_widget = self._weapon_browser_row(
                    disp_name, detail, weapon.get('decoded_full', ''),
                    rarity=base_rarity, type_en=weapon.get('type_en', ''),
                )
                # Size each item to its card — cards with a legendary line are
                # taller than those without. 每张卡片按其内容定高（含传奇行者更高）。
                item.setSizeHint(QtCore.QSize(0, row_widget.sizeHint().height()))
                self.backpack_items_list.addItem(item)
                self.backpack_items_list.setItemWidget(item, row_widget)

            except Exception as e:
                self.main_app.log(f"在处理背包武器时发生严重错误。序列号: {weapon.get('serial', '未知')}，错误: {e}")
        self._filter_backpack_items(self.weapon_search.text())
        self._select_current_backpack_item()

    def _filter_backpack_items(self, query):
        query = query.strip().lower()
        for row in range(self.backpack_items_list.count()):
            item = self.backpack_items_list.item(row)
            search_text = item.data(QtCore.Qt.ItemDataRole.UserRole + 1) or item.text().lower()
            item.setHidden(bool(query and query not in search_text))

    def _select_current_backpack_item(self):
        if not hasattr(self, "backpack_items_list"):
            return
        self.backpack_items_list.clearSelection()
        for row in range(self.backpack_items_list.count()):
            item = self.backpack_items_list.item(row)
            weapon = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if weapon and weapon.get("original_path") == self.selected_weapon_path:
                self.backpack_items_list.setCurrentItem(item)
                self.backpack_items_list.scrollToItem(item, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _update_selected_weapon_summary(self, weapon=None):
        if not hasattr(self, "selected_weapon_summary"):
            return
        if weapon is None and hasattr(self, "backpack_items_list"):
            for row in range(self.backpack_items_list.count()):
                candidate = self.backpack_items_list.item(row).data(QtCore.Qt.ItemDataRole.UserRole)
                if candidate and candidate.get("original_path") == self.selected_weapon_path:
                    weapon = candidate
                    break
        if not weapon:
            self.selected_weapon_summary.setText(self._loc('summary', 'none_selected', "No backpack weapon selected"))
            return
        name = weapon.get("name") or weapon.get("manufacturer") or "Weapon"
        self.selected_weapon_summary.setText(
            self._loc('summary', 'selected', "Selected · {name} · Lv.{level}", name=name, level=weapon.get('level', 'N/A'))
        )

    def update_weapon(self):
        if not self.selected_weapon_path:
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_selection"), self.get_localized_string("select_weapon_first"))
            return

        new_serial, err = b_encoder.encode_to_base85(self.serial_decoded_entry.text().strip())
        if err:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("encoding_fail"), f"{self.get_localized_string('cannot_reencode_serial')}: {err}")
            return

        # 构造符合新 update_item 签名的载荷
        # 我们假设原始数据没有改变，只更新序列号
        # original_item_data 和 new_item_data 可以是部分数据
        payload = {
            'item_path': self.selected_weapon_path,
            'original_item_data': {}, # 留空，让controller自行处理
            'new_item_data': {'serial': new_serial},
            'success_msg': self.get_localized_string('update_success')
        }
        self.update_item_requested.emit(payload)

    def add_new_weapon_to_backpack(self):
        new_decoded = self.serial_decoded_entry.text().strip()
        if not new_decoded:
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_input"), self.get_localized_string("serial_empty"))
            return
        new_serial, err = b_encoder.encode_to_base85(new_decoded)
        if err:
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("encoding_fail"), f"{self.get_localized_string('cannot_encode_serial')}: {err}")
            return
        
        # 使用 flag_combo 的值
        self.add_to_backpack_requested.emit(new_serial, self.flag_combo.currentText().split(" ")[0])

    def open_add_part_window(self):
        if not self.serial_decoded_entry.text():
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_weapon"), self.get_localized_string("load_weapon_first")); return

        win = QtWidgets.QDialog(self)
        win.setObjectName("addPartDialog")
        win.setWindowTitle(self.get_localized_string("add_part_title"))
        win.setMinimumSize(1050, 720)
        win.setModal(True)

        layout = QtWidgets.QVBoxLayout(win)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        header_label = QtWidgets.QLabel(self.get_localized_string("select_parts_to_add"))
        header_label.setObjectName("addPartDialogHeader")
        layout.addWidget(header_label)

        picker = CatalogPicker(
            stackable=True,
            search_placeholder=self._loc('catalog', 'search_part', "Search part name, effect, manufacturer, or type"),
            avail_title=self._loc('catalog', 'available_parts', "Available Parts"),
            selected_title=self._loc('catalog', 'selected_parts', "Selected Parts"),
            clear_text=self._loc('catalog', 'clear', "Clear"),
        )
        source, part_types, manufacturers, weapon_types = self._add_part_catalog_items()
        picker.set_categories(
            [("all", self._loc('catalog', 'all', "All")), *[(value, self.get_localized_string(value)) for value in part_types]],
            columns=5,
        )
        picker.set_subcategories(
            [("all", self._loc('catalog', 'all_manufacturers', "All Manufacturers")), *[(value, self.get_localized_string(value)) for value in manufacturers]],
            columns=6,
        )
        picker.set_third_categories(
            [("all", self._loc('catalog', 'all_weapon_types', "All Weapon Types")), *[(value, self.get_localized_string(value)) for value in weapon_types]],
            columns=6,
        )
        picker.set_source(source)
        layout.addWidget(picker, 1)

        confirm_btn = QtWidgets.QPushButton(self.get_localized_string("confirm_add"))
        confirm_btn.setObjectName("genAddButton")
        confirm_btn.clicked.connect(lambda: self.add_selected_parts(win, picker))
        layout.addWidget(confirm_btn)
        win.exec()

    def _add_part_catalog_items(self):
        source = []
        part_types = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df['Part Type'].dropna()))
        elemental_type = "Elemental"
        elemental_types = ("Element", "Element Switch", "Underbarrel Element Switch", "Pearl Elements", "Pearl Stat")
        part_types.extend(value for value in elemental_types if value not in part_types)
        manufacturers = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df['Manufacturer'].dropna()))
        manufacturers.append(elemental_type)
        weapon_types = list(dict.fromkeys(str(value) for value in self.all_weapon_parts_df['Weapon Type'].dropna()))
        weapon_types.append(elemental_type)

        try:
            level = int(self.level_entry.text())
        except ValueError:
            level = 60
        for _, row in self.all_weapon_parts_df.iterrows():
            item_id, part_id = int(row['Manufacturer & Weapon Type ID']), str(row['Part ID'])
            part_type, manufacturer = str(row['Part Type']), str(row['Manufacturer'])
            weapon_type = str(row['Weapon Type'])
            name = item_display_resolver.weapon_part_name(item_id, part_id, self.current_lang, row)
            preview_serial = f"{item_id}, 0, 1, {level}| 2, 0|| |"
            description = item_display_resolver.format_weapon_part_description(
                item_id, part_id, preview_serial, self.current_lang, part_type
            )
            name = name or (self._loc('parts', 'unnamed_barrel', "Unnamed Barrel") if part_type == "Barrel" else "")
            detail = " · ".join(value for value in (name, description) if value)
            metadata = " / ".join(self.get_localized_string(value) for value in (manufacturer, weapon_type, part_type))
            label = f"{detail}  [{metadata}]"
            source.append({
                "key": f"normal:{item_id}:{part_id}", "label": label, "category": part_type,
                "subcategory": manufacturer, "tertiary": weapon_type,
                "data": {"id": part_id, "mfg_id": item_id, "type": "normal"},
            })

        for _, row in self.elemental_df.iterrows():
            element_id, part_id = int(row['Elemental_ID']), int(row['Part_ID'])
            name = str(row[self.elemental_stat_col])
            part_type = self._elemental_part_type(row)
            source.append({
                "key": f"elemental:{element_id}:{part_id}", "label": name, "category": part_type,
                "subcategory": elemental_type, "tertiary": elemental_type,
                "data": {"id": part_id, "mfg_id": element_id, "type": "elemental"},
            })
        return source, part_types, manufacturers, weapon_types

    @staticmethod
    def _elemental_part_type(row):
        stat = str(row['Stat'])
        if stat.startswith("Pearl Stat"):
            return "Pearl Stat"
        if stat.startswith("Pearl Elements"):
            return "Pearl Elements"
        if stat.startswith("Maliwan Underbarrel-switch"):
            return "Underbarrel Element Switch"
        if stat.startswith("switch between"):
            return "Element Switch"
        return "Element"

    def _build_part_strings(self, parts_by_mfg, current_weapon_mfg_id):
        new_parts_list = []
        for mfg_id, parts in parts_by_mfg.items():
            elemental_parts = [f"{{1:{p['id']}}}" for p in parts if p['type'] == 'elemental']
            normal_parts = [p['id'] for p in parts if p['type'] == 'normal']

            if mfg_id == 1:  # Elemental parts mfg_id is 1
                new_parts_list.extend(elemental_parts)
            elif mfg_id == current_weapon_mfg_id:
                new_parts_list.extend([f"{{{pid}}}" for pid in normal_parts])
            elif normal_parts:
                new_parts_list.append(f"{{{mfg_id}:[{' '.join(map(str, sorted(normal_parts)))}]}}")
        return new_parts_list

    def add_selected_parts(self, window, picker):
        parts_by_mfg = {}
        try:
            current_weapon_mfg_id = int(self.serial_decoded_entry.text().split(',')[0])
        except (ValueError, IndexError):
            QtWidgets.QMessageBox.critical(self, self.get_localized_string("error"), self.get_localized_string("cannot_determine_mfg"))
            return window.close()

        for entry in picker.entries():
            item = entry['data']
            mfg_id = int(item['mfg_id'])
            parts_by_mfg.setdefault(mfg_id, [])
            count = 1 if item['type'] == 'elemental' else entry['count']
            parts_by_mfg[mfg_id].extend([{'id': item['id'], 'type': item['type']}] * count)

        if not parts_by_mfg:
            return window.close()

        new_parts_list = self._build_part_strings(parts_by_mfg, current_weapon_mfg_id)
        if not new_parts_list:
            return window.close()

        new_part_data = self._parse_component_string(" ".join(new_parts_list))

        # Find the last non-skin part index to insert after
        insertion_index = len(self.parts_data)
        for i in range(len(self.parts_data) - 1, -1, -1):
            part = self.parts_data[i]
            if isinstance(part, dict) and part.get('type') != 'skin':
                insertion_index = i + 1
                break
        
        # Insert a space if needed before adding new parts
        if insertion_index > 0:
            prev_item = self.parts_data[insertion_index - 1]
            if (isinstance(prev_item, dict)) or (isinstance(prev_item, str) and prev_item.strip()):
                self.parts_data.insert(insertion_index, ' ')
                insertion_index += 1
        
        self.parts_data[insertion_index:insertion_index] = new_part_data
        
        self.regenerate_ui_and_serial()
        self.main_app.log(f"Added {len(new_part_data)} new part(s).")
        window.close()

    def open_select_skin_window(self, part_index):
        if not self.serial_decoded_entry.text():
            QtWidgets.QMessageBox.warning(self, self.get_localized_string("no_weapon"), self.get_localized_string("load_weapon_first"))
            return
        win = QtWidgets.QDialog(self); win.setWindowTitle(self.get_localized_string("Select Skin"))
        win.setMinimumSize(400, 500); win.setModal(True)
        layout = QtWidgets.QVBoxLayout(win); layout.addWidget(QtWidgets.QLabel(self.get_localized_string("Select a skin to apply")))
        scroll_area = ContainedWheelScrollArea(); scroll_area.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget(); scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        for _, row in self.skin_df.iterrows():
            skin_name = row[self.skin_stat_col] if pd.notna(row.get(self.skin_stat_col)) else row['Stat']
            btn = QtWidgets.QPushButton(f"{row['Skin_ID']}: {self.get_localized_string(skin_name, skin_name)}")
            btn.clicked.connect(partial(self.update_skin, part_index, row['Skin_ID'], win)); scroll_layout.addWidget(btn)
        scroll_area.setWidget(scroll_content); layout.addWidget(scroll_area); win.exec()
    
    def _toggle_group_visibility(self, button, content_frame):
        is_visible = not content_frame.isVisible()
        content_frame.setVisible(is_visible)
        button.setText("▾" if is_visible else "▸")

    def update_skin(self, part_index, new_skin_id, window):
        is_text_id = isinstance(new_skin_id, str) and not new_skin_id.isdigit()
        skin = {
            'type': 'skin',
            'id': new_skin_id if is_text_id else int(new_skin_id),
            'raw': f' "c", "{new_skin_id}"' if is_text_id else f' "c", {int(new_skin_id)}',
        }
        target_index = part_index
        if target_index is None:
            target_index = next(
                (i for i, part in enumerate(self.parts_data) if isinstance(part, dict) and part.get('type') == 'skin'),
                None,
            )
        if target_index is not None and 0 <= target_index < len(self.parts_data):
            if not isinstance(self.parts_data[target_index], dict) or self.parts_data[target_index].get('type') != 'skin':
                QtWidgets.QMessageBox.critical(self, "Error", "The selected part is not a skin part.")
                window.close()
                return
            self.parts_data[target_index] = skin
        else:
            self.parts_data.append(skin)
            self.parts_data.append('|')
        self.regenerate_ui_and_serial()
        self.main_app.log(f"Weapon skin updated to ID: {new_skin_id}")
        window.close()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    class MockApp:
        def log(self, m): print(f"[LOG] {m}")
        def handle_add_to_backpack(self, serial, flag): print(f"Adding to backpack: {serial}")
        @property
        def controller(self):
            class MockController:
                yaml_obj = True
                def get_all_items(self): return []
            return MockController()

    mock_app = MockApp()
    main_win = QtWidgets.QWidget()
    main_win.setWindowTitle("QT Weapon Editor Test")
    main_win.setGeometry(100, 100, 1024, 768)
    layout = QtWidgets.QVBoxLayout(main_win)
    editor = WeaponEditorTab(mock_app)
    layout.addWidget(editor)
    main_win.show()
    sys.exit(app.exec())
