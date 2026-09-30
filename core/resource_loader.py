#!/usr/bin/env python3
"""
资源加载工具模块
用于解决PyInstaller打包后的资源路径问题
"""

import sys
import json
import ast
import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

def get_ui_localization_file(lang: str) -> str:
    """
    Get the UI localization file name for the given language code.
    
    Args:
        lang: Language code (e.g., 'zh-CN', 'en-US', 'ru', 'ua', 'de')
        
    Returns:
        Filename of the localization JSON.
    """
    mapping = {
        'zh-CN': 'data/i18n/ui_localization.json',
        'en-US': 'data/i18n/ui_localization_EN.json',
        'ru': 'data/i18n/ui_localization_RU.json',
        'ua': 'data/i18n/ui_localization_UA.json',
        'de': 'data/i18n/ui_localization_DE.json',
    }
    return mapping.get(lang, 'data/i18n/ui_localization_EN.json')


# Item flag labels are identical across every editor tab; keep one localized
# source instead of a copy-pasted bilingual map per tab. The English values are
# the fallback used only if the localization JSON fails to load.
# 物品标记标签在每个编辑器标签页中都相同；集中维护单一本地化来源，而非在每个
# 标签页复制双语映射。英文值仅在本地化 JSON 加载失败时作为回退。
_FLAG_KEYS = ("1", "3", "5", "17", "33", "65", "129")
_FLAG_FALLBACK_EN = {
    "1": "1 (Normal)", "3": "3 (Favorite)", "5": "5 (Junk)",
    "17": "17 (Group 1)", "33": "33 (Group 2)", "65": "65 (Group 3)",
    "129": "129 (Group 4)",
}


def get_flag_labels(lang: str) -> dict:
    """Localized {code: label} flag map shared by all editor tabs.

    Reads weapon_editor_tab.flags from the language's UI localization (every
    language ships these) and falls back to English per-key on any miss.
    所有编辑器标签页共用的本地化标记映射；读取该语言 UI 本地化中的
    weapon_editor_tab.flags（每种语言均已提供），缺失项按键回退到英文。
    """
    full = load_json_resource(get_ui_localization_file(lang)) or {}
    flags = full.get("weapon_editor_tab", {}).get("flags", {}) or {}
    return {k: flags.get(k, _FLAG_FALLBACK_EN[k]) for k in _FLAG_KEYS}

def get_resource_path(relative_path: Union[str, Path]) -> Path:
    """
    获取资源的绝对路径，支持PyInstaller打包环境
    
    Args:
        relative_path: 相对路径
        
    Returns:
        资源的绝对路径
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller打包环境
        base_path = Path(sys._MEIPASS)
    else:
        # 开发环境 - 使用父目录（core的父目录是项目根目录）
        base_path = Path(__file__).parent.parent
    
    return base_path / relative_path

def load_json_resource(relative_path: Union[str, Path], 
                      use_literal_eval: bool = False) -> Optional[Dict[str, Any]]:
    """
    加载JSON资源文件，支持PyInstaller打包环境
    
    Args:
        relative_path: 相对路径
        use_literal_eval: 是否使用ast.literal_eval解析（用于非标准JSON）
        
    Returns:
        解析后的数据，失败时返回None
    """
    try:
        resource_path = get_resource_path(relative_path)
        if not resource_path.exists():
            # print(f"资源文件不存在: {resource_path}")
            return None
        with open(resource_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if use_literal_eval:
            return ast.literal_eval(content)
        else:
            return json.loads(content)
    except FileNotFoundError:
        # print(f"资源文件不存在: {relative_path}")
        return None
    except json.JSONDecodeError as e:
        # print(f"JSON解析错误 {relative_path}: {e}")
        return None
    except UnicodeDecodeError as e:
        # print(f"文件编码错误 {relative_path}: {e}")
        return None
    except Exception as e:
        # print(f"加载资源文件时发生未知错误 {relative_path}: {e}")
        return None

def load_text_resource(relative_path: Union[str, Path]) -> Optional[str]:
    """
    加载文本资源文件，支持PyInstaller打包环境
    
    Args:
        relative_path: 相对路径
        
    Returns:
        文本内容，失败时返回None
    """
    try:
        resource_path = get_resource_path(relative_path)
        if not resource_path.exists():
            # print(f"文本资源文件不存在: {resource_path}")
            return None
        with open(resource_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        # print(f"文本资源文件不存在: {relative_path}")
        return None
    except UnicodeDecodeError as e:
        # print(f"文件编码错误 {relative_path}: {e}")
        return None
    except Exception as e:
        # print(f"加载文本资源时发生未知错误 {relative_path}: {e}")
        return None


def load_localized_csv_resource(relative_path: Union[str, Path], lang: str):
    """
    Load a localized CSV and expose old-compatible Stat/Description columns.

    The data keeps game text in Stat_EN/_ZH/_RU/_DE and Description_EN/_ZH/_RU/_DE
    (Russian/German filled by the update pipeline); tabs read Stat/Description.
    Cells missing in the UI language fall back to English, as the game does.
    """
    import pandas as pd
    from .game_text import text_lang

    resource_path = get_resource_path(relative_path)
    df = pd.read_csv(resource_path)
    suffix = text_lang(lang).upper()

    for base_col in ("Stat", "Description"):
        localized_col, english_col = f"{base_col}_{suffix}", f"{base_col}_EN"
        if localized_col in df.columns:
            column = df[localized_col]
            if english_col in df.columns and localized_col != english_col:
                column = column.where(column.notna() & (column.astype(str).str.strip() != ""), df[english_col])
            df[base_col] = column
        elif english_col in df.columns:
            df[base_col] = df[english_col]

    return df


def get_image_resource_path(relative_path: Union[str, Path]) -> Optional[Path]:
    """
    获取图片资源的绝对路径，支持PyInstaller打包环境
    
    Args:
        relative_path: 相对路径
        
    Returns:
        图片资源的绝对路径，失败时返回None
    """
    try:
        resource_path = get_resource_path(relative_path)
        
        if not resource_path.exists():
            print(f"图片资源不存在: {resource_path}")
            return None
            
        return resource_path
        
    except Exception as e:
        print(f"获取图片资源路径失败 {relative_path}: {e}")
        return None

def get_class_mods_data_path(filename: str) -> Optional[Path]:
    """
    获取类模组数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/class_mods/{filename}")

def load_class_mods_csv(filename: str) -> List[Dict[str, str]]:
    """
    加载类模组CSV文件
    
    Args:
        filename: CSV文件名
        
    Returns:
        解析后的数据列表，每行作为一个字典，失败时返回空列表
    """
    try:
        resource_path = get_resource_path(f"data/class_mods/{filename}")
        if not resource_path.exists():
            print(f"CSV文件不存在: {resource_path}")
            return []
        with open(resource_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        print(f"加载CSV文件时发生错误 {filename}: {e}")
        return []

def get_class_mods_image_path(class_name: str, image_name: str) -> Optional[Path]:
    """
    获取类模组图片文件的路径
    
    Args:
        class_name: 职业名称
        image_name: 图片文件名
        
    Returns:
        图片路径，失败时返回None
    """
    return get_image_resource_path(f"data/class_mods/{class_name}/{image_name}")

def get_enhancement_data_path(filename: str) -> Optional[Path]:
    """
    获取enhancement目录下数据文件的路径
    """
    return get_resource_path(f"data/enhancement/{filename}")


def load_enhancement_csv(filename: str) -> List[Dict[str, str]]:
    """
    加载enhancement目录下的CSV文件
    
    Args:
        filename: CSV文件名
        
    Returns:
        解析后的数据列表，每行作为一个字典，失败时返回空列表
    """
    try:
        resource_path = get_resource_path(f"data/enhancement/{filename}")
        if not resource_path.exists():
            print(f"Enhancement CSV文件不存在: {resource_path}")
            return []
        with open(resource_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        print(f"加载Enhancement CSV文件时发生错误 {filename}: {e}")
        return []


def get_enhancement_data() -> Optional[Dict[str, Any]]:
    """
    从CSV文件加载enhancement数据并构建与原格式兼容的数据结构
    
    Returns:
        与原enhancement_data.txt格式兼容的数据字典；词条名按语言放在 names 中
    """
    try:
        # 加载CSV数据
        manufacturers_csv = load_enhancement_csv("Enhancement_manufacturers.csv")
        perks_csv = load_enhancement_csv("Enhancement_perk.csv")
        rarity_csv = load_enhancement_csv("Enhancement_rarity.csv")
        
        if not manufacturers_csv or not perks_csv or not rarity_csv:
            print("Enhancement CSV文件加载失败")
            return None
        
        def names(row: Dict[str, str]) -> Dict[str, str]:
            """Perk name per game text language (Russian/German from the pipeline)."""
            out = {code: (row.get(f'perk_name_{code.upper()}') or '').strip() for code in ('en', 'zh', 'ru', 'de')}
            return {code: text for code, text in out.items() if text}

        # 构建manufacturers数据
        manufacturers = {}
        for row in manufacturers_csv:
            mfg_name = row['manufacturers_name']
            mfg_id = int(row['manufacturers_ID'])
            perk_id = int(row['perk_ID'])
            perk_name_en = row['perk_name_EN']

            if mfg_name not in manufacturers:
                manufacturers[mfg_name] = {
                    'code': mfg_id,
                    'name': mfg_name,
                    'perks': [],
                    'rarities': {}
                }

            manufacturers[mfg_name]['perks'].append({
                'index': perk_id,
                'name': perk_name_en,
                'names': names(row),
            })

        # 构建rarities数据
        rarity_map_247 = {}
        for row in rarity_csv:
            mfg_id = int(row['manufacturers_ID'])
            mfg_name = row['manufacturers_name']
            rarity_id = int(row['rarity_ID'])
            rarity_name = row['rarity']

            if mfg_id == 247:
                # 247的稀有度映射
                rarity_map_247[rarity_name] = rarity_id
            else:
                # 普通制造商的稀有度
                if mfg_name in manufacturers:
                    manufacturers[mfg_name]['rarities'][rarity_name] = rarity_id

        # 构建secondary_247数据
        secondary_247 = []
        for row in perks_csv:
            secondary_247.append({
                'code': int(row['perk_ID']),
                'name': row['perk_name_EN'],
                'names': names(row),
            })

        return {
            'manufacturers': manufacturers,
            'rarity_map_247': rarity_map_247,
            'secondary_247': secondary_247,
        }
        
    except Exception as e:
        print(f"构建Enhancement数据时发生错误: {e}")
        return None

def get_weapon_data_path(filename: str) -> Optional[Path]:
    """
    获取武器数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/weapon/{filename}")

def get_grenade_data_path(filename: str) -> Optional[Path]:
    """
    获取手雷数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/grenade/{filename}")


def get_shield_data_path(filename: str) -> Optional[Path]:
    """
    获取护盾数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/shield/{filename}")


def get_repkit_data_path(filename: str) -> Optional[Path]:
    """
    获取修复套件数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/repkit/{filename}")


def get_heavy_data_path(filename: str) -> Optional[Path]:
    """
    获取重武器数据文件的路径

    Args:
        filename: 文件名

    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/heavy/{filename}")


def get_firmware_data_path(filename: str) -> Optional[Path]:
    """
    获取共享固件数据文件的路径（四族装备共用一份固件目录）。

    Args:
        filename: 文件名

    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"data/firmware/{filename}")


@lru_cache(maxsize=4)
def load_item_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载物品浏览器JSON索引文件。
    """
    return load_json_resource(f"data/item/{filename}")


def get_loadout_data_path(filename: str) -> Optional[Path]:
    """
    获取配置管理器静态数据文件的路径。

    注意：这里只用于打包进程序的只读资源，例如
    loadout/skill_name_mapping.csv。用户保存的配置方案仍应写入
    exe 同目录下的 loadouts/，不要走 PyInstaller 临时目录。
    """
    return get_resource_path(f"data/loadout/{filename}")
