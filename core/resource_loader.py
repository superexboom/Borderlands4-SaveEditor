#!/usr/bin/env python3
"""
资源加载工具模块
用于解决PyInstaller打包后的资源路径问题
"""

import sys
import json
import ast
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

def get_ui_localization_file(lang: str) -> str:
    """
    Get the UI localization file name for the given language code.
    
    Args:
        lang: Language code (e.g., 'zh-CN', 'en-US', 'ru', 'ua')
        
    Returns:
        Filename of the localization JSON.
    """
    mapping = {
        'zh-CN': 'i18n/ui_localization.json',
        'en-US': 'i18n/ui_localization_EN.json',
        'ru': 'i18n/ui_localization_RU.json',
        'ua': 'i18n/ui_localization_UA.json'
    }
    return mapping.get(lang, 'i18n/ui_localization_EN.json')


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

    Reads weapon_editor_tab.flags from the language's UI localization (all four
    languages ship these) and falls back to English per-key on any miss.
    所有编辑器标签页共用的本地化标记映射；读取该语言 UI 本地化中的
    weapon_editor_tab.flags（四种语言均已提供），缺失项按键回退到英文。
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
    Load a merged EN/ZH CSV and expose old-compatible Stat/Description columns.

    Merged data keeps localized text in Stat_ZH/Stat_EN and
    Description_ZH/Description_EN. Existing tabs still read Stat/Description.
    """
    import pandas as pd

    resource_path = get_resource_path(relative_path)
    df = pd.read_csv(resource_path)
    suffix = "EN" if lang in ["en-US", "ru", "ua"] else "ZH"

    for base_col in ("Stat", "Description"):
        localized_col = f"{base_col}_{suffix}"
        if localized_col in df.columns:
            df[base_col] = df[localized_col]

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
    return get_resource_path(f"class_mods/{filename}")

def load_class_mods_json(filename: str, use_literal_eval: bool = False) -> Optional[Dict[str, Any]]:
    """
    加载类模组JSON文件
    
    Args:
        filename: 文件名
        use_literal_eval: 是否使用ast.literal_eval解析
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"class_mods/{filename}", use_literal_eval)

def load_class_mods_csv(filename: str) -> List[Dict[str, str]]:
    """
    加载类模组CSV文件
    
    Args:
        filename: CSV文件名
        
    Returns:
        解析后的数据列表，每行作为一个字典，失败时返回空列表
    """
    try:
        resource_path = get_resource_path(f"class_mods/{filename}")
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
    return get_image_resource_path(f"class_mods/{class_name}/{image_name}")

def get_enhancement_data_path(filename: str) -> Optional[Path]:
    """
    获取enhancement目录下数据文件的路径
    """
    return get_resource_path(f"enhancement/{filename}")


def load_enhancement_csv(filename: str) -> List[Dict[str, str]]:
    """
    加载enhancement目录下的CSV文件
    
    Args:
        filename: CSV文件名
        
    Returns:
        解析后的数据列表，每行作为一个字典，失败时返回空列表
    """
    try:
        resource_path = get_resource_path(f"enhancement/{filename}")
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
        与原enhancement_data.txt格式兼容的数据字典，包含中文翻译
    """
    try:
        # 加载CSV数据
        manufacturers_csv = load_enhancement_csv("Enhancement_manufacturers.csv")
        perks_csv = load_enhancement_csv("Enhancement_perk.csv")
        rarity_csv = load_enhancement_csv("Enhancement_rarity.csv")
        
        if not manufacturers_csv or not perks_csv or not rarity_csv:
            print("Enhancement CSV文件加载失败")
            return None
        
        # 构建英文名到中文名的映射表
        localization_map = {}
        
        # 构建manufacturers数据
        manufacturers = {}
        for row in manufacturers_csv:
            mfg_name = row['manufacturers_name']
            mfg_id = int(row['manufacturers_ID'])
            perk_id = int(row['perk_ID'])
            perk_name_en = row['perk_name_EN']
            perk_name_zh = row.get('perk_name_ZH', perk_name_en)
            
            # 添加到本地化映射
            localization_map[perk_name_en] = perk_name_zh
            
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
                'name_zh': perk_name_zh
            })
        
        # 构建rarities数据
        rarity_map_247 = {}
        rarity_localization = {
            'Common': '普通',
            'Uncommon': '罕见',
            'Rare': '稀有',
            'Epic': '史诗',
            'Legendary': '传奇'
        }
        for rarity_en, rarity_zh in rarity_localization.items():
            localization_map[rarity_en] = rarity_zh
        
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
            perk_id = int(row['perk_ID'])
            perk_name_en = row['perk_name_EN']
            perk_name_zh = row.get('perk_name_ZH', perk_name_en)
            
            # 添加到本地化映射
            localization_map[perk_name_en] = perk_name_zh
            
            secondary_247.append({
                'code': perk_id,
                'name': perk_name_en,
                'name_zh': perk_name_zh
            })
        
        # 添加制造商名称的本地化
        mfg_name_localization = {
            'Atlas': '阿特拉斯',
            'COV': '秘藏之子',
            'Daedalus': '代达洛斯',
            'Hyperion': '亥伯龙',
            'Jakobs': '雅各布斯',
            'Maliwan': '马里旺',
            'Ripper': '开颅者',
            'Tediore': '泰迪尔',
            'The Order': '教团',
            'Torgue': '托格',
            'Vladof': '弗拉多夫'
        }
        for mfg_en, mfg_zh in mfg_name_localization.items():
            localization_map[mfg_en] = mfg_zh
        
        return {
            'manufacturers': manufacturers,
            'rarity_map_247': rarity_map_247,
            'secondary_247': secondary_247,
            'localization': localization_map
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
    return get_resource_path(f"weapon_edit/{filename}")

def load_weapon_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载武器编辑器JSON文件
    
    Args:
        filename: 文件名
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"weapon_edit/{filename}")

def get_grenade_data_path(filename: str) -> Optional[Path]:
    """
    获取手雷数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"grenade/{filename}")


def get_shield_data_path(filename: str) -> Optional[Path]:
    """
    获取护盾数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"shield/{filename}")


def get_repkit_data_path(filename: str) -> Optional[Path]:
    """
    获取修复套件数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"repkit/{filename}")


def get_heavy_data_path(filename: str) -> Optional[Path]:
    """
    获取重武器数据文件的路径

    Args:
        filename: 文件名

    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"heavy/{filename}")


def get_firmware_data_path(filename: str) -> Optional[Path]:
    """
    获取共享固件数据文件的路径（四族装备共用一份固件目录）。

    Args:
        filename: 文件名

    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"Firmware/{filename}")


def load_item_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载物品浏览器JSON索引文件。
    """
    return load_json_resource(f"item/{filename}")


def get_loadout_data_path(filename: str) -> Optional[Path]:
    """
    获取配置管理器静态数据文件的路径。

    注意：这里只用于打包进程序的只读资源，例如
    loadout/skill_name_mapping.csv。用户保存的配置方案仍应写入
    exe 同目录下的 loadouts/，不要走 PyInstaller 临时目录。
    """
    return get_resource_path(f"loadout/{filename}")
