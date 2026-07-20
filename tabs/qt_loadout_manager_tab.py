# qt_loadout_manager_tab.py
# 配置管理器标签页 — 查看已装备物品、技能配点，保存/加载配置方案
# i18n support: uses ui_localization[_XX].json -> "loadout_tab" section

import re
import json
import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QScrollArea, QMessageBox, QFrame, QInputDialog
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon

from core import resource_loader
from core import decoder_logic
from core import item_display_resolver
from core import lookup
from core import bl4_functions as bl4f
from core.unlock_data import CHARACTER_CLASSES


# ── 武器槽位 (0-3) — 需要解析真实名称 ────────────────────────────────
WEAPON_SLOT_KEYS = {'slot_0', 'slot_1', 'slot_2', 'slot_3'}

# SDU graph 名称，用于划定边界
SDU_GRAPH_NAME = 'sdu_upgrades'

# Fallback slot names (used if localization loading fails)
_SLOT_FALLBACK = {
    'slot_0': '武器1', 'slot_1': '武器2', 'slot_2': '武器3', 'slot_3': '武器4',
    'slot_4': '护盾', 'slot_5': '重武器/手雷', 'slot_6': '修复套件',
    'slot_7': '强化模组', 'slot_8': '职业模组',
}


def _get_editor_root() -> Path:
    """获取编辑器根目录"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_skill_graphs(graphs: list) -> list:
    """从 progression.graphs 中提取 actionskills 到 sdu_upgrades 之前的所有 graph。"""
    result = []
    for g in graphs:
        if g.get('name', '') == SDU_GRAPH_NAME:
            break
        result.append(g)
    return result


def _replace_skill_graphs(graphs: list, new_skill_graphs: list) -> list:
    """安全替换 progression.graphs 中的技能部分。"""
    sdu_index = None
    for i, g in enumerate(graphs):
        if g.get('name', '') == SDU_GRAPH_NAME:
            sdu_index = i
            break
    if sdu_index is not None:
        tail = graphs[sdu_index:]
        return new_skill_graphs + tail
    else:
        return list(new_skill_graphs)


class QtLoadoutManagerTab(QWidget):
    """配置管理器标签页 (with full i18n support)"""

    # CLASS_IDS mirrors QtClassModEditorTab for icon lookup
    CLASS_IDS = {'Amon': 255, 'Harlowe': 259, 'Rafa': 256, 'Vex': 254, 'C4sh': 404, 'C4SH': 404}
    CLASS_NAME_ALIASES = {'C4SH': 'C4sh'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.yaml_data = None
        self.current_loadout_index = 1
        self.save_file_path = None       # 当前存档文件路径
        self.save_name = None            # 存档文件名（不含后缀）
        self.current_lang = 'zh-CN'
        self.image_cache = {}            # 技能图标缓存
        self._manual_read_active = False # 是否处于手动读取状态

        # 每个槽位已保存配置内容缓存 {slot_index: loadout_dict or None}
        self._saved_loadouts = {i: None for i in range(1, 7)}

        # Load i18n data
        self.loc = {}
        self._load_localization()

        # 加载武器 CSV 数据
        self._load_weapon_csv_data()
        # 加载技能 CSV 数据
        self._load_skills_csv_data()
        # 加载武器本地化
        self._load_weapon_localization()

        self._build_ui()

    # ══════════════════════════════════════════════════════════════════
    # i18n 本地化
    # ══════════════════════════════════════════════════════════════════
    def _load_localization(self):
        """根据当前语言加载 loadout_tab 本地化数据"""
        lang_map = {
            'zh-CN': "i18n/ui_localization.json",
            'en-US': "i18n/ui_localization_EN.json",
            'ru': "i18n/ui_localization_RU.json",
            'ua': "i18n/ui_localization_UA.json",
        }
        filename = lang_map.get(self.current_lang, "i18n/ui_localization_EN.json")
        data = resource_loader.load_json_resource(filename)
        if data and "loadout_tab" in data:
            self.loc = data["loadout_tab"]
        else:
            # Fallback (Chinese)
            self.loc = {
                "groups": {"equipped": "已装备物品", "loadout": "配置方案", "skills": "技能配置"},
                "slots": _SLOT_FALLBACK,
                "buttons": {"read_save": "读取当前存档配置", "save_loadout": "保存配置",
                            "load_loadout": "加载配置到存档"},
                "labels": {"activated_skills": "已激活技能", "points_suffix": " 点",
                           "activated": "已激活", "config_name": "配置名称:",
                           "default_config_name": "槽位 {slot}"},
                "placeholders": {
                    "empty_slot": "该槽位无已保存配置\n点击「读取当前存档配置」查看当前装备",
                    "empty_slot_skills": "该槽位无已保存配置",
                    "open_save_first": "请先打开存档并点击「读取当前存档配置」",
                    "no_equipped": "配置中无装备数据", "no_skills": "配置中无技能数据",
                    "no_data": "暂无技能数据", "no_activated": "暂无已激活技能",
                    "no_items": "当前没有装备任何物品", "open_first": "请先打开存档",
                    "no_equipped_data": "未找到已装备物品数据",
                },
                "decode": {
                    "unknown": "未知",
                    "decode_failed": "解码失败",
                    "unknown_item": "未知物品",
                    "decode_error": "解码错误",
                },
                "notice": "",
                "dialogs": {},
            }

    def _t(self, section: str, key: str, **kwargs) -> str:
        """Convenience helper: loc[section][key].format(**kwargs) with fallback."""
        val = self.loc.get(section, {}).get(key, key)
        if kwargs:
            try:
                return val.format(**kwargs)
            except (KeyError, IndexError):
                return val
        return val

    def _t_slot(self, slot_key: str) -> str:
        """Get localized slot name."""
        return self.loc.get('slots', {}).get(slot_key, _SLOT_FALLBACK.get(slot_key, slot_key))

    def update_language(self, lang_code: str):
        """Called by MainWindow when language changes. Reload i18n and refresh UI."""
        self.current_lang = lang_code
        self._load_localization()
        self._load_weapon_localization()
        self._refresh_ui_text()

    def _refresh_ui_text(self):
        """Refresh all static text in the UI after language change."""
        # Group titles
        self.equipped_group.setTitle(self._t('groups', 'equipped'))
        self.loadout_group.setTitle(self._t('groups', 'loadout'))
        self.skill_group.setTitle(self._t('groups', 'skills'))

        # Buttons
        self.read_save_button.setText(self._t('buttons', 'read_save'))
        self.save_loadout_btn.setText(self._t('buttons', 'save_loadout'))
        self.load_loadout_btn.setText(self._t('buttons', 'load_loadout'))

        # Notification bar
        notice = self.loc.get('notice', '')
        if notice:
            self.notice_label.setText(notice)
            self.notice_label.setVisible(True)
        else:
            self.notice_label.setVisible(False)

        # Update slot button labels with config names
        self._update_slot_button_labels()

        # Re-display current content
        if self._manual_read_active:
            self._refresh_equipped_display_from_yaml()
            self._refresh_skills_display_from_yaml()
        else:
            self._display_slot_content(self.current_loadout_index)

    # ══════════════════════════════════════════════════════════════════
    # 数据加载
    # ══════════════════════════════════════════════════════════════════
    def _load_weapon_csv_data(self):
        """加载 weapon_rarity.csv, all_weapon_part.csv"""
        try:
            suffix = ""
            def get_path(base_name):
                name_with_suffix = base_name.replace('.csv', f'{suffix}.csv')
                path = resource_loader.get_weapon_data_path(name_with_suffix)
                if path and path.exists():
                    return path
                return resource_loader.get_weapon_data_path(base_name)

            self.all_weapon_parts_df = pd.read_csv(get_path('all_weapon_part.csv'))
            self.weapon_rarity_df = pd.read_csv(get_path('weapon_rarity.csv'))
        except Exception as e:
            print(f"Loadout: 加载武器CSV数据失败: {e}")
            self.all_weapon_parts_df = pd.DataFrame()
            self.weapon_rarity_df = pd.DataFrame()

    def _load_weapon_localization(self):
        """加载武器本地化 JSON — 仅中文时使用映射，其他语言直接显示英文原名"""
        if self.current_lang == 'zh-CN':
            try:
                self.weapon_localization = resource_loader.load_weapon_json('weapon_localization_zh-CN.json') or {}
            except Exception:
                self.weapon_localization = {}
        else:
            # Non-Chinese: skip the mapping so English names from CSV pass through
            self.weapon_localization = {}

    def _load_skills_csv_data(self):
        """加载 class_mods/Skills.csv 并按 class_ID 索引"""
        self.skills_data = resource_loader.load_class_mods_csv("Skills.csv")
        self.class_ids = dict(self.CLASS_IDS)
        self.class_names_by_identifier = {}
        self.skills_by_class = {}
        for skill in self.skills_data:
            class_id = skill.get('class_ID', '')
            class_name = skill.get('class_name', '').strip()
            class_identifier = skill.get('class_identifier', '').strip().casefold()
            if class_id.isdigit() and class_name:
                self.class_ids[class_name] = int(class_id)
                if class_identifier:
                    self.class_names_by_identifier[class_identifier] = class_name
            if class_id not in self.skills_by_class:
                self.skills_by_class[class_id] = []
            self.skills_by_class[class_id].append(skill)

        self.skill_lookup = {}
        self.skills_by_graph = {}
        for skill in self.skills_data:
            key = (skill.get('class_ID', ''), skill.get('skill_name_EN', ''))
            self.skill_lookup[key] = skill
            graph_key = self._skill_mapping_key(
                skill.get('class_ID', ''), skill.get('graph_name', ''), skill.get('node_name', '')
            )
            self.skills_by_graph[graph_key] = skill

        # 加载技能名称映射表
        self._load_skill_name_mapping()

    @staticmethod
    def _normalize_mapping_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    def _skill_mapping_key(self, class_id: str, graph_name: str, node_name: str) -> tuple:
        return (
            str(class_id or "").strip(),
            self._normalize_mapping_text(graph_name),
            self._normalize_mapping_text(node_name),
        )

    def _skill_mapping_class_key(self, class_id: str, node_name: str) -> tuple:
        return (
            str(class_id or "").strip(),
            self._normalize_mapping_text(node_name),
        )

    def _load_skill_name_mapping(self):
        """加载 loadout/skill_name_mapping.csv 映射表。"""
        self.skill_name_mapping = {}
        self.skill_name_mapping_by_graph = {}
        self.skill_name_mapping_by_class = {}
        try:
            mapping_path = resource_loader.get_loadout_data_path("skill_name_mapping.csv")
            if mapping_path and mapping_path.exists():
                with open(mapping_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    fieldnames = set(reader.fieldnames or [])
                    for row in reader:
                        if {'class_id', 'graph_name', 'node_name', 'middle_name', 'skill_name_EN'}.issubset(fieldnames):
                            class_id = row.get('class_id', '').strip()
                            graph_name = row.get('graph_name', '').strip()
                            node_name = row.get('node_name', '').strip()
                            middle_name = row.get('middle_name', '').strip()
                            mapped_name = row.get('skill_name_EN', '').strip()

                            if not (class_id and mapped_name):
                                continue
                            for lookup_name in {node_name, middle_name}:
                                if graph_name and lookup_name:
                                    self.skill_name_mapping_by_graph[
                                        self._skill_mapping_key(class_id, graph_name, lookup_name)
                                    ] = row
                                if lookup_name:
                                    self.skill_name_mapping_by_class[
                                        self._skill_mapping_class_key(class_id, lookup_name)
                                    ] = row
                                    self.skill_name_mapping.setdefault(lookup_name, mapped_name)
                        else:
                            raw_name = row.get('raw_display_name', '').strip()
                            mapped_name = row.get('skill_name_EN', '').strip()
                            if raw_name and mapped_name:
                                self.skill_name_mapping[raw_name] = mapped_name
                total = len(self.skill_name_mapping_by_graph) or len(self.skill_name_mapping)
                print(f"Loadout: 已加载 {total} 条技能名称映射")
            else:
                print(f"Loadout: 映射表不存在 {mapping_path}")
        except Exception as e:
            print(f"Loadout: 加载技能名称映射表失败: {e}")
            self.skill_name_mapping = {}
            self.skill_name_mapping_by_graph = {}
            self.skill_name_mapping_by_class = {}

    # ══════════════════════════════════════════════════════════════════
    # 角色/技能辅助
    # ══════════════════════════════════════════════════════════════════
    def _get_character_class_name(self) -> str:
        """从 YAML 获取角色职业英文名 (e.g. 'Harlowe')"""
        if not self.yaml_data:
            return ''
        try:
            state = self.yaml_data.get('state', self.yaml_data)
            class_raw = state.get('class', '')
            discovered_name = self.class_names_by_identifier.get(str(class_raw).casefold())
            if discovered_name:
                return self.CLASS_NAME_ALIASES.get(discovered_name, discovered_name)
            class_key = class_raw.replace('Char_', '') if class_raw.startswith('Char_') else class_raw
            char_info = CHARACTER_CLASSES.get(class_key, {})
            class_name = char_info.get('name', class_key)
            return self.CLASS_NAME_ALIASES.get(class_name, class_name)
        except (AttributeError, TypeError):
            return ''

    def get_skill_icon(self, icon_file: str, class_name: str) -> QIcon:
        """获取技能图标"""
        if not icon_file:
            return QIcon()
        class_name = self.CLASS_NAME_ALIASES.get(class_name, class_name)
        cache_key = f"{class_name}/{icon_file}"
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        try:
            path = resource_loader.get_class_mods_image_path(class_name, icon_file)
            if path and Path(path).exists():
                icon = QIcon(str(path))
                self.image_cache[cache_key] = icon
                return icon
        except Exception as e:
            print(f"Could not load icon {icon_file}: {e}")
        return QIcon()

    def _find_skill_csv_row(self, class_id: str, graph_name: str = '', node_name: str = '', skill_name: str = '') -> dict:
        if graph_name and node_name:
            row = self.skills_by_graph.get(self._skill_mapping_key(class_id, graph_name, node_name))
            if row:
                return row
        normalized_name = re.sub(r" [BGR]$", "", skill_name).casefold()
        for row in self.skills_by_class.get(class_id, []):
            if graph_name and self._normalize_mapping_text(row.get('graph_name', '')) != self._normalize_mapping_text(graph_name):
                continue
            row_name = re.sub(r" [BGR]$", "", row.get('skill_name_EN', '')).casefold()
            if row_name == normalized_name:
                return row
        return {}

    def _find_loadout_skill_mapping(self, class_id: str, graph_name: str, skill_name: str) -> dict:
        if graph_name and skill_name:
            row = self.skill_name_mapping_by_graph.get(
                self._skill_mapping_key(class_id, graph_name, skill_name)
            )
            if row:
                return row
        if skill_name:
            row = self.skill_name_mapping_by_class.get(
                self._skill_mapping_class_key(class_id, skill_name)
            )
            if row:
                return row
        return {}

    def _get_skill_display_info(self, skill_name_en: str, class_name: str,
                                class_id: str, graph_name: str = '') -> tuple:
        """查找技能的本地化名和图标。返回 (display_name, icon)。

        优先使用从 progress_graph + uitooltipdata 生成的新映射表；
        找不到时再回退到旧的 Skills.csv 名称匹配。
        """
        original_name = skill_name_en
        class_name = self.CLASS_NAME_ALIASES.get(class_name, class_name)
        mapping_row = self._find_loadout_skill_mapping(class_id, graph_name, skill_name_en)
        if mapping_row:
            mapped_name = mapping_row.get('skill_name_EN', '').strip() or skill_name_en
            skill_row = self._find_skill_csv_row(
                class_id,
                mapping_row.get('graph_name', ''),
                mapping_row.get('graph_coord', '') or mapping_row.get('node_name', ''),
                mapped_name,
            )
            display_name = skill_row.get('skill_name_EN', '').strip() or mapped_name
            zh_name = (skill_row.get('skill_name_ZH', '') or mapping_row.get('skill_name_ZH', '')).strip()
            if self.current_lang == 'zh-CN' and zh_name:
                display_name = zh_name
            icon = self.get_skill_icon(skill_row.get('icon_file', ''), class_name)
            return display_name, icon

        mapped_name = self.skill_name_mapping.get(skill_name_en, skill_name_en)
        if mapped_name != original_name:
            print(f"Loadout: 技能名称映射 '{original_name}' -> '{mapped_name}'")
        
        lookup_name = mapped_name
        display_name = lookup_name
        icon = QIcon()
        
        # Step 2: 在 Skills.csv 中查找
        skill_row = self.skill_lookup.get((class_id, lookup_name))
        if not skill_row:
            candidates = self.skills_by_class.get(class_id, [])
            # 精确匹配（不区分大小写）
            for row in candidates:
                en_name = row.get('skill_name_EN', '')
                if en_name.lower() == lookup_name.lower():
                    skill_row = row
                    break
            # 模糊匹配
            if not skill_row:
                for row in candidates:
                    en_name = row.get('skill_name_EN', '')
                    if (lookup_name.lower() in en_name.lower()
                            or en_name.lower() in lookup_name.lower()):
                        skill_row = row
                        break
        
        # Step 3: 获取显示名称和图标
        if skill_row:
            skill_name_en_canonical = skill_row.get('skill_name_EN', lookup_name)
            zh_name = skill_row.get('skill_name_ZH', '')
            if self.current_lang == 'zh-CN' and zh_name:
                display_name = zh_name
            else:
                display_name = skill_name_en_canonical
            icon = self.get_skill_icon(skill_row.get('icon_file', ''), class_name)
        else:
            # 未找到匹配，显示原始名称（或映射后的名称）
            display_name = lookup_name
            
        return display_name, icon

    # ══════════════════════════════════════════════════════════════════
    # 武器名称解析
    # ══════════════════════════════════════════════════════════════════
    def _parse_component_string(self, component_str):
        """解析武器部件字符串"""
        components, last_index = [], 0
        for match in re.finditer(r'\{(\d+)(?::(\d+|\[[\d\s]+\]))?\}|\"c\",\s*(?:(\d+)|\"([^\"]+)\")', component_str):
            components.append(component_str[last_index:match.start()])
            part_data = {'raw': match.group(0)}
            if match.group(3):
                part_data.update({'type': 'skin', 'id': int(match.group(3))})
            elif match.group(4):
                part_data.update({'type': 'skin', 'id': match.group(4)})
            else:
                outer_id, inner = int(match.group(1)), match.group(2)
                if inner:
                    if '[' in inner:
                        part_data.update({'type': 'group', 'id': outer_id,
                                          'sub_ids': [int(sid) for sid in inner.strip('[]').split()]})
                    else:
                        part_data.update({'type': 'elemental', 'id': outer_id, 'sub_id': int(inner)})
                else:
                    part_data.update({'type': 'simple', 'id': outer_id})
            components.append(part_data)
            last_index = match.end()
        components.append(component_str[last_index:])
        return [c for c in components if c]

    def _get_weapon_real_name(self, serial: str) -> str:
        """解码 serial 获取武器真实名称"""
        try:
            formatted_str, _, err = decoder_logic.decode_serial_to_string(serial)
            if err or '||' not in formatted_str:
                return ''
            header_part, component_part = formatted_str.split('||', 1)
            sections = header_part.strip().split('|')
            m_id = int(sections[0].strip().split(',')[0])

            manufacturer, item_type, found = lookup.get_kind_enums(m_id)
            if not found:
                return ''
            display = item_display_resolver.resolve_item_display(
                m_id,
                manufacturer,
                item_type,
                formatted_str,
                self.current_lang,
            )
            weapon_name = "" if display.get("display_source") == "fallback" else display.get("display_name", "")
            loc_rarity = display.get("rarity", "")

            display_parts = []
            if loc_rarity:
                display_parts.append(f"[{loc_rarity}]")
            if weapon_name:
                display_parts.append(weapon_name)
            return ' '.join(display_parts) if display_parts else ''
        except Exception as e:
            print(f"Loadout: 武器名称解析失败: {e}")
            return ''

    # ══════════════════════════════════════════════════════════════════
    # Loadout 文件 I/O
    # ══════════════════════════════════════════════════════════════════
    def _get_loadout_dir(self) -> Path:
        """获取 loadouts 保存目录（编辑器根目录/loadouts）"""
        return _get_editor_root() / "loadouts"

    def _get_loadout_filepath(self, slot: int) -> Path:
        """获取指定槽位的配置文件路径"""
        return self._get_loadout_dir() / f"loadout_{self.save_name}_{slot}.json"

    def _scan_saved_loadouts(self):
        """扫描当前存档对应的已保存配置"""
        self._saved_loadouts = {i: None for i in range(1, 7)}
        if not self.save_name:
            return
        loadout_dir = self._get_loadout_dir()
        if not loadout_dir.exists():
            return
        for slot in range(1, 7):
            fp = loadout_dir / f"loadout_{self.save_name}_{slot}.json"
            if fp.exists():
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        self._saved_loadouts[slot] = json.load(f)
                except Exception as e:
                    print(f"Loadout: 读取槽位 {slot} 配置失败: {e}")

    # ══════════════════════════════════════════════════════════════════
    # UI 构建
    # ══════════════════════════════════════════════════════════════════
    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        left_panel = self._build_equipped_panel()
        main_layout.addWidget(left_panel, stretch=1)

        right_panel = self._build_right_panel()
        main_layout.addWidget(right_panel, stretch=1)

    def _build_equipped_panel(self) -> QWidget:
        self.equipped_group = QGroupBox(self._t('groups', 'equipped'))
        layout = QVBoxLayout(self.equipped_group)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 15, 10, 10)

        self.read_save_button = QPushButton(self._t('buttons', 'read_save'))
        self.read_save_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(76, 175, 80, 0.3);
                border: 1px solid rgba(76, 175, 80, 0.5); border-radius: 6px;
                padding: 8px 16px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(76, 175, 80, 0.5); color: white; }
        """)
        self.read_save_button.clicked.connect(self._on_read_save_clicked)
        layout.addWidget(self.read_save_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.equipped_container = QWidget()
        self.equipped_container.setStyleSheet("background: transparent;")
        self.equipped_layout = QVBoxLayout(self.equipped_container)
        self.equipped_layout.setSpacing(6)
        self.equipped_layout.setContentsMargins(0, 0, 0, 0)
        self.equipped_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.equipped_placeholder = QLabel(self._t('placeholders', 'open_save_first'))
        self.equipped_placeholder.setStyleSheet("color: #888; font-size: 13px; padding: 20px;")
        self.equipped_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.equipped_layout.addWidget(self.equipped_placeholder)
        scroll.setWidget(self.equipped_container)
        layout.addWidget(scroll)
        return self.equipped_group

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.loadout_group = QGroupBox(self._t('groups', 'loadout'))
        loadout_layout = QVBoxLayout(self.loadout_group)
        loadout_layout.setSpacing(8)

        # Slot buttons row + config name label
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.loadout_buttons = []
        for i in range(1, 7):
            btn = QPushButton(str(i))
            btn.setFixedSize(42, 36)
            btn.setCheckable(True)
            btn.setStyleSheet(self._loadout_btn_style(False, False))
            btn.clicked.connect(lambda checked, idx=i: self._on_loadout_selected(idx))
            self.loadout_buttons.append(btn)
            btn_row.addWidget(btn)

        # Config name label (shows name of the saved config next to slots)
        self.config_name_label = QLabel("")
        self.config_name_label.setStyleSheet(
            "font-size: 12px; font-style: italic; padding-left: 8px;")
        btn_row.addWidget(self.config_name_label)

        self.loadout_buttons[0].setChecked(True)
        self.loadout_buttons[0].setStyleSheet(self._loadout_btn_style(True, False))
        btn_row.addStretch()
        loadout_layout.addLayout(btn_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.save_loadout_btn = QPushButton(self._t('buttons', 'save_loadout'))
        self.save_loadout_btn.setStyleSheet(self._action_btn_style("#2196F3"))
        self.save_loadout_btn.clicked.connect(self._on_save_loadout)
        action_row.addWidget(self.save_loadout_btn)

        self.load_loadout_btn = QPushButton(self._t('buttons', 'load_loadout'))
        self.load_loadout_btn.setStyleSheet(self._action_btn_style("#FF9800"))
        self.load_loadout_btn.clicked.connect(self._on_load_loadout)
        action_row.addWidget(self.load_loadout_btn)
        action_row.addStretch()
        loadout_layout.addLayout(action_row)
        layout.addWidget(self.loadout_group)

        # 技能区
        self.skill_group = QGroupBox(self._t('groups', 'skills'))
        skill_outer = QVBoxLayout(self.skill_group)

        # Notification bar
        self.notice_label = QLabel(self.loc.get('notice', ''))
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 152, 0, 0.12);
                border: 1px solid rgba(255, 152, 0, 0.35);
                border-radius: 6px;
                color: #e65100;
                font-size: 11px;
                padding: 8px 10px;
                margin-bottom: 4px;
            }
        """)
        if not self.loc.get('notice', ''):
            self.notice_label.setVisible(False)
        skill_outer.addWidget(self.notice_label)

        skill_scroll = QScrollArea()
        skill_scroll.setWidgetResizable(True)
        skill_scroll.setFrameShape(QFrame.Shape.NoFrame)
        skill_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.skills_container = QWidget()
        self.skills_container.setStyleSheet("background: transparent;")
        self.skills_layout = QVBoxLayout(self.skills_container)
        self.skills_layout.setSpacing(4)
        self.skills_layout.setContentsMargins(0, 0, 0, 0)
        self.skills_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.skills_placeholder = QLabel(self._t('placeholders', 'no_data'))
        self.skills_placeholder.setStyleSheet("color: #888; font-size: 13px; padding: 20px;")
        self.skills_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.skills_layout.addWidget(self.skills_placeholder)
        skill_scroll.setWidget(self.skills_container)
        skill_outer.addWidget(skill_scroll)
        layout.addWidget(self.skill_group, stretch=1)
        return panel

    # ══════════════════════════════════════════════════════════════════
    # 样式
    # ══════════════════════════════════════════════════════════════════
    @staticmethod
    def _loadout_btn_style(active: bool, has_saved: bool) -> str:
        if active:
            return """
                QPushButton {
                    background-color: rgba(33, 150, 243, 0.6); color: white;
                    border: 2px solid #2196F3; border-radius: 6px;
                    font-size: 14px; font-weight: bold;
                }
            """
        if has_saved:
            return """
                QPushButton {
                    background-color: rgba(76, 175, 80, 0.15);
                    border: 1px solid rgba(76, 175, 80, 0.5); border-radius: 6px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: rgba(76, 175, 80, 0.3);
                }
            """
        return """
            QPushButton {
                background-color: rgba(128,128,128,0.06);
                border: 1px solid rgba(128,128,128,0.12); border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(128,128,128,0.12);
            }
        """

    @staticmethod
    def _action_btn_style(color: str) -> str:
        return f"""
            QPushButton {{
                background-color: rgba({_hex_to_rgb(color)}, 0.25);
                border: 1px solid rgba({_hex_to_rgb(color)}, 0.5); border-radius: 6px;
                padding: 7px 18px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba({_hex_to_rgb(color)}, 0.45); color: white;
            }}
        """

    # ══════════════════════════════════════════════════════════════════
    # 回调
    # ══════════════════════════════════════════════════════════════════
    def _on_loadout_selected(self, index: int):
        """切换槽位：清空手动读取状态，显示已保存配置（如有）"""
        self.current_loadout_index = index
        self._manual_read_active = False
        self._update_loadout_button_styles()
        self._update_config_name_display()
        self._display_slot_content(index)

    def _update_loadout_button_styles(self):
        """刷新所有槽位按钮样式"""
        for i, btn in enumerate(self.loadout_buttons):
            slot = i + 1
            is_active = (slot == self.current_loadout_index)
            has_saved = self._saved_loadouts.get(slot) is not None
            btn.setChecked(is_active)
            btn.setStyleSheet(self._loadout_btn_style(is_active, has_saved))

    def _update_slot_button_labels(self):
        """Update slot button text with config names (if saved) or slot number."""
        for i, btn in enumerate(self.loadout_buttons):
            slot = i + 1
            saved = self._saved_loadouts.get(slot)
            if saved and saved.get('config_name'):
                btn.setText(str(slot))
                btn.setToolTip(saved['config_name'])
            else:
                btn.setText(str(slot))
                btn.setToolTip("")
        self._update_config_name_display()

    def _update_config_name_display(self):
        """Update the config name label next to the slot buttons."""
        slot = self.current_loadout_index
        saved = self._saved_loadouts.get(slot)
        if saved and saved.get('config_name'):
            self.config_name_label.setText(f"[ {saved['config_name']} ]")
        else:
            default_name = self._t('labels', 'default_config_name', slot=slot)
            self.config_name_label.setText(f"[ {default_name} ]")

    def _on_read_save_clicked(self):
        """读取当前存档实时配置并临时显示"""
        if not self.yaml_data:
            QMessageBox.warning(self,
                                self._t('dialogs', 'hint'),
                                self._t('dialogs', 'open_save_first'))
            return
        self._manual_read_active = True
        self._refresh_equipped_display_from_yaml()
        self._refresh_skills_display_from_yaml()

    # ══════════════════════════════════════════════════════════════════
    # set_data — 由 MainWindow 调用
    # ══════════════════════════════════════════════════════════════════
    def set_data(self, yaml_data, save_file_path=None):
        """由 MainWindow 调用，传入 YAML 数据和存档路径。
        切换存档时重置全部状态。
        """
        self.yaml_data = yaml_data
        self._manual_read_active = False

        if save_file_path:
            self.save_file_path = save_file_path
            self.save_name = Path(save_file_path).stem  # e.g. "1"
        else:
            self.save_name = None

        # 扫描已保存配置
        self._scan_saved_loadouts()
        self._update_loadout_button_styles()
        self._update_slot_button_labels()

        # 显示当前槽位的内容（已保存 or 空）
        self._display_slot_content(self.current_loadout_index)

    # ══════════════════════════════════════════════════════════════════
    # 显示控制
    # ══════════════════════════════════════════════════════════════════
    def _display_slot_content(self, slot: int):
        """显示指定槽位的配置内容。
        优先显示已保存配置；若无，显示空。
        """
        saved = self._saved_loadouts.get(slot)
        if saved:
            self._display_loadout_data(saved)
        else:
            # 空槽位
            self._clear_layout(self.equipped_layout)
            self._add_placeholder(self.equipped_layout, self._t('placeholders', 'empty_slot'))
            self._clear_layout(self.skills_layout)
            self._add_placeholder(self.skills_layout, self._t('placeholders', 'empty_slot_skills'))
        self._update_config_name_display()

    def _display_loadout_data(self, loadout: dict):
        """展示一个已保存的 loadout（来自 JSON）"""
        # 装备
        self._clear_layout(self.equipped_layout)
        equipped_items = loadout.get('equipped_items', [])
        if equipped_items:
            for item_data in equipped_items:
                slot_key = item_data.get('slot', '')
                serial = item_data.get('serial', '')
                if not serial:
                    continue
                slot_name = self._t_slot(slot_key)
                if slot_key in WEAPON_SLOT_KEYS:
                    item_name = self._get_weapon_real_name(serial)
                    if not item_name:
                        item_name = self._decode_item_name(serial)
                else:
                    item_name = self._decode_item_name(serial)
                row = self._create_equipped_row(slot_name, item_name, serial)
                self.equipped_layout.addWidget(row)
            self.equipped_layout.addStretch()
        else:
            self._add_placeholder(self.equipped_layout, self._t('placeholders', 'no_equipped'))

        # 技能
        self._clear_layout(self.skills_layout)
        skill_graphs = loadout.get('skill_graphs', [])
        if skill_graphs:
            self._display_skill_graphs(skill_graphs)
        else:
            self._add_placeholder(self.skills_layout, self._t('placeholders', 'no_skills'))

    # ══════════════════════════════════════════════════════════════════
    # 从 YAML 实时读取显示（手动读取）
    # ══════════════════════════════════════════════════════════════════
    def _refresh_equipped_display_from_yaml(self):
        """从当前存档 YAML 读取装备并显示"""
        self._clear_layout(self.equipped_layout)
        if not self.yaml_data:
            self._add_placeholder(self.equipped_layout, self._t('placeholders', 'open_first'))
            return
        equipped_data = self._get_equipped_data()
        if not equipped_data:
            self._add_placeholder(self.equipped_layout, self._t('placeholders', 'no_equipped_data'))
            return

        found_any = False
        for slot_key in ['slot_0', 'slot_1', 'slot_2', 'slot_3', 'slot_4',
                         'slot_5', 'slot_6', 'slot_7', 'slot_8']:
            if slot_key not in equipped_data:
                continue
            slot_name = self._t_slot(slot_key)
            item_list = equipped_data[slot_key]
            if isinstance(item_list, list) and len(item_list) > 0:
                item = item_list[0]
            elif isinstance(item_list, dict):
                item = item_list
            else:
                continue
            serial = item.get('serial', '')
            if not serial:
                continue
            found_any = True
            if slot_key in WEAPON_SLOT_KEYS:
                item_name = self._get_weapon_real_name(serial)
                if not item_name:
                    item_name = self._decode_item_name(serial)
            else:
                item_name = self._decode_item_name(serial)
            row = self._create_equipped_row(slot_name, item_name, serial)
            self.equipped_layout.addWidget(row)

        if not found_any:
            self._add_placeholder(self.equipped_layout, self._t('placeholders', 'no_items'))
        self.equipped_layout.addStretch()

    def _refresh_skills_display_from_yaml(self):
        """从当前存档 YAML 读取技能并显示"""
        self._clear_layout(self.skills_layout)
        if not self.yaml_data:
            self._add_placeholder(self.skills_layout, self._t('placeholders', 'no_data'))
            return
        progression = self.yaml_data.get('progression', {})
        graphs = progression.get('graphs', [])
        skill_graphs = _get_skill_graphs(graphs)
        if not skill_graphs:
            self._add_placeholder(self.skills_layout, self._t('placeholders', 'no_data'))
            return
        self._display_skill_graphs(skill_graphs)

    def _display_skill_graphs(self, skill_graphs: list):
        """通用：将 skill_graphs 列表显示到技能面板（仅显示已激活技能）"""
        class_name = self._get_character_class_name()
        class_id = str(self.class_ids.get(class_name, 0))

        found_any = False
        cat_label = QLabel(self._t('labels', 'activated_skills'))
        cat_label.setStyleSheet("""
            font-size: 13px; font-weight: bold;
            padding: 6px 0 2px 0;
        """)
        self.skills_layout.addWidget(cat_label)

        pts_suffix = self._t('labels', 'points_suffix')
        activated_text = self._t('labels', 'activated')

        for graph in skill_graphs:
            graph_name = graph.get('name', '')
            for node in graph.get('nodes', []):
                name = node.get('name') or self._t('decode', 'unknown')
                pts = node.get('points_spent', 0)
                is_activated = node.get('is_activated', False)

                if pts and pts > 0:
                    found_any = True
                    display_name, icon = self._get_skill_display_info(name, class_name, class_id, graph_name)
                    row = self._create_skill_row(display_name, f"{pts}{pts_suffix}", "#64b5f6", icon)
                    self.skills_layout.addWidget(row)
                elif is_activated:
                    found_any = True
                    display_name, icon = self._get_skill_display_info(name, class_name, class_id, graph_name)
                    row = self._create_skill_row(display_name, activated_text, "#4caf50", icon)
                    self.skills_layout.addWidget(row)

        if not found_any:
            self._add_placeholder(self.skills_layout, self._t('placeholders', 'no_activated'))

        self.skills_layout.addStretch()

    # ══════════════════════════════════════════════════════════════════
    # 装备/技能行 UI 创建
    # ══════════════════════════════════════════════════════════════════
    def _get_equipped_data(self):
        try:
            state = self.yaml_data.get('state', self.yaml_data)
            inventory = state.get('inventory', {})
            equipped_inv = inventory.get('equipped_inventory', {})
            return equipped_inv.get('equipped', {})
        except (AttributeError, TypeError):
            return None

    def _decode_item_name(self, serial: str) -> str:
        try:
            formatted_str, _, err = decoder_logic.decode_serial_to_string(serial)
            if err:
                return f"[{self._t('decode', 'decode_failed')}: {err}]"
            if '||' not in formatted_str:
                return f"[{self._t('decode', 'unknown_item')}]"
            header_part, _ = formatted_str.split('||', 1)
            id_section = header_part.strip().split('|')[0]
            id_part = id_section.strip().split(',')
            if len(id_part) < 4:
                return f"[{self._t('decode', 'unknown_item')}]"
            item_id = int(id_part[0].strip())
            manufacturer, item_type, found = lookup.get_kind_enums(item_id)
            if not found:
                return f"[ID: {item_id}]"
            loc_mfr = bl4f.get_localized_string(manufacturer)
            loc_type = bl4f.get_localized_string(item_type)
            return f"{loc_mfr} {loc_type}"
        except Exception:
            return f"[{self._t('decode', 'decode_error')}]"

    def _create_equipped_row(self, slot_name: str, item_name: str, serial: str) -> QWidget:
        row = QFrame()
        row.setStyleSheet("""
            QFrame {
                background-color: rgba(128,128,128,0.05);
                border: 1px solid rgba(128,128,128,0.1);
                border-radius: 6px; padding: 4px;
            }
        """)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(3)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        slot_label = QLabel(slot_name)
        slot_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        slot_label.setFixedWidth(90)
        slot_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(slot_label)
        name_label = QLabel(item_name)
        name_label.setStyleSheet("font-size: 12px;")
        header_layout.addWidget(name_label)
        header_layout.addStretch()
        row_layout.addLayout(header_layout)

        serial_edit = QLineEdit(serial)
        serial_edit.setReadOnly(True)
        serial_edit.setStyleSheet("""
            QLineEdit {
                border-radius: 4px;
                padding: 3px 6px; font-size: 11px; font-family: Consolas, monospace;
            }
        """)
        serial_edit.setFixedHeight(26)
        serial_edit.mousePressEvent = lambda e, se=serial_edit: se.selectAll() \
            if e.button() == Qt.MouseButton.LeftButton and e.type().value == 4 else None
        row_layout.addWidget(serial_edit)
        return row

    def _create_skill_row(self, name: str, status_text: str, color: str,
                          icon: QIcon = None) -> QFrame:
        row = QFrame()
        row.setFixedHeight(36)
        row.setStyleSheet("""
            QFrame {
                background-color: rgba(128,128,128,0.05);
                border: 1px solid rgba(128,128,128,0.1); border-radius: 5px;
            }
        """)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 2, 10, 2)
        row_layout.setSpacing(6)

        if icon and not icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(QSize(24, 24)))
            icon_label.setFixedSize(28, 28)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(icon_label)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-size: 12px;")
        row_layout.addWidget(name_label)
        row_layout.addStretch()

        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
        row_layout.addWidget(status_label)
        return row

    # ══════════════════════════════════════════════════════════════════
    # 保存配置
    # ══════════════════════════════════════════════════════════════════
    def _on_save_loadout(self):
        if not self.yaml_data:
            QMessageBox.warning(self,
                                self._t('dialogs', 'hint'),
                                self._t('dialogs', 'open_save_first'))
            return
        if not self.save_name:
            QMessageBox.warning(self,
                                self._t('dialogs', 'hint'),
                                self._t('dialogs', 'no_save_name'))
            return

        idx = self.current_loadout_index

        # Prompt for config name
        config_name, ok = QInputDialog.getText(
            self,
            self._t('dialogs', 'name_prompt_title'),
            self._t('dialogs', 'name_prompt_msg'),
        )
        if not ok or not config_name.strip():
            config_name = ""  # Will use default name on display

        loadout_dir = self._get_loadout_dir()
        loadout_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._get_loadout_filepath(idx)

        # 收集装备
        equipped_data = self._get_equipped_data() or {}
        equipped_items = []
        for slot_key in ['slot_0', 'slot_1', 'slot_2', 'slot_3', 'slot_4',
                         'slot_5', 'slot_6', 'slot_7', 'slot_8']:
            if slot_key not in equipped_data:
                continue
            item_list = equipped_data[slot_key]
            if isinstance(item_list, list) and len(item_list) > 0:
                item = item_list[0]
            elif isinstance(item_list, dict):
                item = item_list
            else:
                continue
            equipped_items.append({
                'slot': slot_key,
                'serial': item.get('serial', ''),
                'flags': item.get('flags', None),
                'state_flags': item.get('state_flags', 1),
            })

        # 收集技能 graphs（actionskills ~ sdu 之前的全部）
        progression = self.yaml_data.get('progression', {})
        graphs = progression.get('graphs', [])
        skill_graphs = _get_skill_graphs(graphs)

        loadout = {
            'save_name': self.save_name,
            'slot': idx,
            'config_name': config_name.strip(),
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'equipped_items': equipped_items,
            'skill_graphs': skill_graphs,
        }

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(loadout, f, ensure_ascii=False, indent=2)
            # 更新内存缓存
            self._saved_loadouts[idx] = loadout
            self._manual_read_active = False
            self._update_loadout_button_styles()
            self._update_slot_button_labels()
            self._display_slot_content(idx)
            QMessageBox.information(
                self,
                self._t('dialogs', 'success'),
                self._t('dialogs', 'save_success', slot=idx, path=str(filepath)))
        except Exception as e:
            QMessageBox.critical(
                self,
                self._t('dialogs', 'save_fail_title'),
                self._t('dialogs', 'save_fail', error=str(e)))

    # ══════════════════════════════════════════════════════════════════
    # 加载配置到存档
    # ══════════════════════════════════════════════════════════════════
    def _on_load_loadout(self):
        """将已保存的配置覆写到当前 YAML 存档"""
        if not self.yaml_data:
            QMessageBox.warning(self,
                                self._t('dialogs', 'hint'),
                                self._t('dialogs', 'open_save_first'))
            return

        idx = self.current_loadout_index
        saved = self._saved_loadouts.get(idx)
        if not saved:
            QMessageBox.warning(self,
                                self._t('dialogs', 'hint'),
                                self._t('dialogs', 'no_saved_config', slot=idx))
            return

        # 确认对话框
        reply = QMessageBox.question(
            self,
            self._t('dialogs', 'confirm_overwrite_title'),
            self._t('dialogs', 'confirm_overwrite_msg', slot=idx),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors = []

        # 覆写装备 — 整体替换 equipped 字典（处理槽位增减）
        try:
            state = self.yaml_data.get('state', self.yaml_data)
            inventory = state.get('inventory', {})
            equipped_inv = inventory.setdefault('equipped_inventory', {})
            new_equipped = {}
            for item_data in saved.get('equipped_items', []):
                slot = item_data['slot']
                entry = {'serial': item_data['serial']}
                if item_data.get('flags') is not None:
                    entry['flags'] = item_data['flags']
                entry['state_flags'] = item_data.get('state_flags', 1)
                new_equipped[slot] = [entry]
            equipped_inv['equipped'] = new_equipped
        except Exception as e:
            errors.append(self._t('dialogs', 'equip_fail', error=str(e)))

        # 覆写技能 graphs
        skill_graphs = saved.get('skill_graphs', [])
        if skill_graphs:
            try:
                progression = self.yaml_data.setdefault('progression', {})
                current_graphs = progression.get('graphs', [])
                new_graphs = _replace_skill_graphs(current_graphs, skill_graphs)
                progression['graphs'] = new_graphs
            except Exception as e:
                errors.append(self._t('dialogs', 'skill_fail', error=str(e)))

        if errors:
            QMessageBox.warning(self,
                                self._t('dialogs', 'partial_fail'),
                                "\n".join(errors))
        else:
            QMessageBox.information(
                self,
                self._t('dialogs', 'success'),
                self._t('dialogs', 'load_success', slot=idx))

        # 刷新显示
        self._display_slot_content(idx)

    # ══════════════════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════════════════
    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    @staticmethod
    def _add_placeholder(layout, text: str):
        label = QLabel(text)
        label.setStyleSheet("color: #888; font-size: 13px; padding: 20px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


def _hex_to_rgb(hex_color: str) -> str:
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"{r}, {g}, {b}"
