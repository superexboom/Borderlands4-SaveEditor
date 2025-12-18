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
import importlib.resources
import pkg_resources

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

def load_all_skill_descriptions() -> Dict[str, Dict[str, str]]:
    """
    加载所有职业的技能描述文件，并整合成一个字典
    使用Skills.csv获取英文名到中文名的映射

    Returns:
        一个以技能英文名为键，包含中英文描述的字典
    """
    all_skills = {}
    characters = ['Amon', 'Vex', 'Harlowe', 'Rafa']
    
    # 从Skills.csv加载英文名→中文名的映射
    skills_csv = load_class_mods_csv("Skills.csv")
    skill_name_map = {}  # skill_name_EN -> skill_name_ZH
    for row in skills_csv:
        en_name = row.get('skill_name_EN', '').strip()
        zh_name = row.get('skill_name_ZH', '').strip()
        if en_name and zh_name:
            skill_name_map[en_name] = zh_name

    for char in characters:
        en_skills_list = load_class_mods_json(f"{char}_en.json")
        zh_skills_list = load_class_mods_json(f"{char}_zh.json")

        if not en_skills_list:
            continue
        
        # Build ZH lookup map keyed by Chinese Name for robust matching
        zh_lookup = {}
        if zh_skills_list:
            for item in zh_skills_list:
                if 'name' in item:
                    zh_lookup[item['name']] = item

        for en_skill_data in en_skills_list:
            skill_en_name = en_skill_data.get('name')
            if not skill_en_name:
                continue
            
            desc_en = en_skill_data.get('description', 'No English description.')
            desc_zh = desc_en
            
            # 使用Skills.csv中的映射查找中文名称
            zh_name_candidate = skill_name_map.get(skill_en_name)
            if zh_name_candidate and zh_name_candidate in zh_lookup:
                desc_zh = zh_lookup[zh_name_candidate].get('description', desc_en)
            # Fallback: Try direct name match (if keys are identical)
            elif skill_en_name in zh_lookup:
                desc_zh = zh_lookup[skill_en_name].get('description', desc_en)

            all_skills[skill_en_name] = {
                'en': desc_en,
                'zh': desc_zh,
                'type': en_skill_data.get('type', 'N/A')
            }
            
            # Also add lower-case key to handle inconsistencies
            if skill_en_name and skill_en_name.lower() != skill_en_name:
                all_skills[skill_en_name.lower()] = all_skills[skill_en_name]

    return all_skills

def load_enhancement_json(filename: str, use_literal_eval: bool = False) -> Optional[Dict[str, Any]]:
    """
    加载增强功能JSON/文本文件
    
    Args:
        filename: 文件名
        use_literal_eval: 是否使用ast.literal_eval解析
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"enhancement/{filename}", use_literal_eval)


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
            'Uncommon': '稀有',
            'Rare': '特殊',
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


def load_grenade_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载手雷编辑器JSON文件
    
    Args:
        filename: 文件名
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"grenade/{filename}")


def get_shield_data_path(filename: str) -> Optional[Path]:
    """
    获取护盾数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"shield/{filename}")


def load_shield_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载护盾编辑器JSON文件
    
    Args:
        filename: 文件名
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"shield/{filename}")


def get_repkit_data_path(filename: str) -> Optional[Path]:
    """
    获取修复套件数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"repkit/{filename}")


def load_repkit_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载修复套件编辑器JSON文件
    
    Args:
        filename: 文件名
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"repkit/{filename}")


def get_heavy_data_path(filename: str) -> Optional[Path]:
    """
    获取重武器数据文件的路径
    
    Args:
        filename: 文件名
        
    Returns:
        文件路径，失败时返回None
    """
    return get_resource_path(f"heavy/{filename}")


def load_heavy_json(filename: str) -> Optional[Dict[str, Any]]:
    """
    加载重武器编辑器JSON文件
    
    Args:
        filename: 文件名
        
    Returns:
        解析后的数据，失败时返回None
    """
    return load_json_resource(f"heavy/{filename}")


# 向后兼容的函数
def get_builtin_localization() -> Dict[str, str]:
    """
    获取内置的本地化数据（作为后备）
    
    Returns:
        本地化数据字典
    """
    return {
        "Class Mod Editor": "职业模组编辑器",
        "Class": "职业",
        "Rarity": "稀有度",
        "Name": "名称",
        "Random Integer (1–9999)": "随机种子 (1–9999)",
        "Legendary Additions": "传奇附加",
        "Available": "可选",
        "Selected": "已选",
        "Clear": "清空",
        "Full String (copy-ready)": "完整代码 (可复制)",
        "Copy Full String": "复制完整代码",
        "Skill Catalog": "技能目录",
        "Icon": "图标",
        "Skill": "技能",
        "Codes (order)": "代码 (顺序)",
        "+Points": "+点数",
        "Universal Perks": "通用专长",
        "Search perks...": "搜索专长...",
        "Only add 1 Firmware": "仅添加1个固件",
        # Rarity
        "Common": "普通",
        "Uncommon": "稀有",
        "Rare": "特殊",
        "Epic": "传奇",
        "Legendary": "史诗",
    }
