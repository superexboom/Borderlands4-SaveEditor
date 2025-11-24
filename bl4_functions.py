# bl4_functions.py

from typing import Any, Dict, List, Optional, Tuple, Union
import re
import b_encoder


# Helper to find deeply nested dictionary paths
def _walk_find(node: Any, target_keys: List[str], path: Optional[List[Union[str, int]]] = None) -> Optional[List[Union[str, int]]]:
    if path is None:
        path = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in target_keys:
                return path + [k]
            # Recurse
            found_path = _walk_find(v, target_keys, path + [k])
            if found_path:
                return found_path
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found_path = _walk_find(v, target_keys, path + [i])
            if found_path:
                return found_path
    return None

# Locate paths for currencies
def find_currency_paths(yaml_data: Dict[str, Any]) -> Dict[str, Optional[List[Union[str, int]]]]:
    """Detects paths for cash and eridium in the save data."""
    paths = {"cash": None, "eridium": None}
    
    # Priority 1: Check a standard 'currencies' block
    if "currencies" in yaml_data and isinstance(yaml_data["currencies"], dict):
        for key, target in [("cash", "cash"), ("eridium", "eridium")]:
            if key in yaml_data["currencies"]:
                paths[target] = ["currencies", key]

    # Priority 2: Scan the entire tree for common names if paths are still missing
    if not paths["cash"]:
        paths["cash"] = _walk_find(yaml_data, ["cash", "money"])
    if not paths["eridium"]:
        paths["eridium"] = _walk_find(yaml_data, ["eridium", "vaultcoin"])
        
    return paths

# Generic helper to set a value at a given path
def _set_by_path(root: Any, toks: List[Union[str, int]], val: Any):
    cur = root
    for t in toks[:-1]:
        cur = cur[t]
    cur[toks[-1]] = val

# Main function to apply all character and currency changes
def apply_character_and_currency_changes(data: Dict[str, Any], yaml_data: Dict[str, Any], current_paths: Dict[str, Any]) -> bool:
    """Applies all changes from a data dictionary to the YAML data object."""
    if not isinstance(yaml_data, dict):
        return False

    def maybe_int(x: str) -> int:
        try:
            return int(str(x).strip())
        except (ValueError, TypeError):
            return 0
    
    try:
        # Apply name and difficulty
        char_name = data.get("名称", "")
        difficulty = data.get("难度", "")
        
        root_node = yaml_data.get("state", yaml_data)
        if not isinstance(root_node, dict):
             root_node = yaml_data

        if "char_name" in root_node: root_node["char_name"] = char_name
        if "player_difficulty" in root_node: root_node["player_difficulty"] = difficulty

        # Experience and levels
        exp_list = root_node.setdefault("experience", [])
        if not isinstance(exp_list, list): exp_list = []
        
        char_exp = next((item for item in exp_list if isinstance(item, dict) and item.get("type") == "Character"), None)
        spec_exp = next((item for item in exp_list if isinstance(item, dict) and item.get("type") == "Specialization"), None)

        if char_exp is None:
            char_exp = {"type": "Character"}
            exp_list.append(char_exp)
        if spec_exp is None:
            spec_exp = {"type": "Specialization"}
            exp_list.append(spec_exp)
            
        char_exp["level"] = maybe_int(data.get("角色等级", 0))
        char_exp["points"] = maybe_int(data.get("角色经验值", 0))
        spec_exp["level"] = maybe_int(data.get("专精等级", 0))
        spec_exp["points"] = maybe_int(data.get("专精点数", 0))

        # Apply currencies
        for key, label in [("cash", "金钱"), ("eridium", "镒矿")]:
            path = current_paths.get(key)
            val_str = data.get(label, "").strip()
            if path and val_str:
                _set_by_path(yaml_data, path, maybe_int(val_str))
        
        return True

    except Exception:
        # In a logic-only function, it's better to let exceptions propagate
        # or return False without logging to a UI element.
        return False

# ── Item Processing Logic ─────────────────────────────────────────────────────
import decoder_logic
import lookup
from typing import TypedDict, List
from resource_loader import load_json_resource

# 全局本地化缓存
localization_cache = None
current_localization_lang = 'zh-CN'

def set_language(lang: str):
    """Sets the current language and clears the localization cache."""
    global current_localization_lang, localization_cache
    current_localization_lang = lang
    localization_cache = None

def get_localized_string(key: str) -> str:
    """获取本地化字符串，如果未找到则返回原始键"""
    global localization_cache
    if localization_cache is None:
        if current_localization_lang == 'zh-CN':
            # 尝试加载武器本地化文件
            weapon_loc = load_json_resource('weapon_edit/weapon_localization_zh-CN.json') or {}
            # 尝试加载物品本地化文件
            item_loc = load_json_resource('item_localization_zh-CN.json') or {}
            # 合并字典
            localization_cache = {**weapon_loc, **item_loc}
        else:
            # For English or other languages, assume keys are already English
            # or load specific EN files if they exist in future
            localization_cache = {}
            
    return localization_cache.get(key, key)

class ProcessedItem(TypedDict):
    name: str
    type: str
    type_en: str
    container: str
    slot: str
    manufacturer: str
    manufacturer_en: str
    id: int
    level: int
    serial: str
    decoded_full: str
    decoded_parts: str

def _walk_for_serials(node: Any, path: List[str]) -> List[Tuple[List[str], Any]]:
    """
    Recursively walks through the YAML object to find all items with a 'serial' key.
    Returns a list of tuples, where each tuple is (path_to_item, item_object).
    """
    found_items = []
    if isinstance(node, dict):
        # If a 'serial' key exists, we've found an item.
        if 'serial' in node and isinstance(node['serial'], str) and node['serial'].startswith('@U'):
            found_items.append((path, node))
        # Otherwise, continue walking through the dictionary.
        else:
            for k, v in node.items():
                found_items.extend(_walk_for_serials(v, path + [str(k)]))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found_items.extend(_walk_for_serials(v, path + [str(i)]))
    return found_items


def process_and_load_items(yaml_data: Dict[str, Any]) -> List[ProcessedItem]:
    """
    Scans the YAML data for all items using a recursive walk, decodes their serials,
    and returns a structured list of processed item data.
    """
    if not isinstance(yaml_data, dict):
        return []

    all_items: List[ProcessedItem] = []
    
    discovered_items = _walk_for_serials(yaml_data, [])

    for path, item_data in discovered_items:
        # Rule: Ignore items under 'unknown_items'
        if "unknown_items" in path:
            continue

        serial = item_data.get("serial", "")
        if not serial:
            continue

        try:
            formatted_str, _, err = decoder_logic.decode_serial_to_string(serial)
            if err:
                continue
        except Exception as e:
            # This is a hard guard against a C-level crash in the decoder
            # We log it and move on, preventing a full application crash.
            print(f"严重解码错误，序列号: {serial}, 错误: {e}")
            continue
        
        split_marker = "||"
        if split_marker not in formatted_str:
            continue
        
        header_part, parts_part = formatted_str.split(split_marker, 1)
        
        try:
            id_section = header_part.strip().split('|')[0]
            id_part = id_section.strip().split(',')
            if len(id_part) < 4:
                continue
            item_id = int(id_part[0].strip())
            item_level = int(id_part[3].strip())

            manufacturer, item_type, found = lookup.get_kind_enums(item_id)
            if not found:
                manufacturer, item_type = "Unknown", "Unknown"

            # 应用本地化
            localized_manufacturer = get_localized_string(manufacturer)
            localized_item_type = get_localized_string(item_type)
            
            item_name = f"{localized_manufacturer} {localized_item_type}"
            display_parts = parts_part.strip()

            # Determine container and slot from the path
            container_name = "Unknown"
            slot_key = "—" # Default for items without a slot, like lost loot

            if "lostloot" in path:
                container_name = "丢失物品"
            elif "equipped_inventory" in path or "equipped" in path:
                container_name = "Equipped"
            elif "inventory" in path and "backpack" in path:
                container_name = "Backpack"

            # Only find a slot_key if not in lost loot
            if container_name != "丢失物品":
                for p_part in reversed(path):
                    if p_part.startswith("slot_"):
                        slot_key = p_part
                        break

            processed_item: ProcessedItem = {
                "original_path": path,
                "name": item_name,
                "type": localized_item_type,
                "type_en": item_type,
                "container": container_name,
                "slot": slot_key,
                "manufacturer": localized_manufacturer,
                "manufacturer_en": manufacturer,
                "id": item_id,
                "level": item_level,
                "serial": serial,
                "decoded_full": formatted_str,
                "decoded_parts": display_parts,
            }
            all_items.append(processed_item)

        except (ValueError, IndexError):
            continue
            
    return all_items

def add_item_to_backpack(yaml_data: Dict[str, Any], serial: str, state_flags: str) -> Optional[List[Union[str, int]]]:
    """
    Adds a new item to the first available slot in the backpack.
    Returns the full path to the new item on success, otherwise None.
    """
    try:
        # Find the path to the backpack dynamically
        backpack_path = _walk_find(yaml_data, ["backpack"])
        if not backpack_path:
            return None

        # Get a reference to the backpack node
        backpack_node = yaml_data
        temp_path = []
        for key in backpack_path:
            backpack_node = backpack_node[key]
            temp_path.append(key)

        # Find the highest existing slot number
        max_slot = -1
        if isinstance(backpack_node, dict):
            for key in backpack_node.keys():
                if isinstance(key, str) and key.startswith("slot_"):
                    try:
                        num = int(key.split('_')[1])
                        if num > max_slot:
                            max_slot = num
                    except (ValueError, IndexError):
                        continue
        
        # Determine the new slot key
        new_slot_key = f"slot_{max_slot + 1}"

        # Create the new item structure
        new_item = {
            'serial': serial,
            'state_flags': int(state_flags)
        }
        
        # Add the new item to the backpack
        backpack_node[new_slot_key] = new_item
        
        # Return the full path to the newly added item
        return temp_path + [new_slot_key]

    except Exception:
        return None

        
        # Return the full path to the newly added item
        return temp_path + [new_slot_key]

    except Exception:
        return None

def update_level_in_decoded_str(decoded_full: str, new_level: int) -> Optional[str]:
    """
    Updates the level within the full decoded item string.
    Example input: '12345, 6, 7, 50 | ... || part1, part2, ...'
    """
    try:
        header_part, parts_part = decoded_full.split("||", 1)
        
        id_section, *other_header_parts = header_part.strip().split('|')
        
        id_parts = [p.strip() for p in id_section.split(',')]
        
        if len(id_parts) >= 4:
            id_parts[3] = str(new_level)
        else:
            return None # Not a valid format

        new_id_section = ", ".join(id_parts)
        
        new_header_part = "|".join([new_id_section] + other_header_parts)

        return f"{new_header_part} ||{parts_part}"
        
    except (ValueError, IndexError):
        return None

def get_yaml_loader():
    """返回一个能忽略未知标签的PyYAML加载器"""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML is not installed. Install with: pip install pyyaml")

    class AnyTagLoader(yaml.SafeLoader): pass

    def _ignore_any(loader: AnyTagLoader, tag_suffix: str, node: 'yaml.Node'):
        if isinstance(node, yaml.ScalarNode): return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode): return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode): return loader.construct_mapping(node)
        return None

    AnyTagLoader.add_multi_constructor("", _ignore_any)
    return AnyTagLoader


def find_node_by_path(yaml_data: Dict[str, Any], path_str: str) -> Optional[Any]:
    """通过点分隔的路径字符串查找节点，例如 'inventory.backpack'。"""
    keys = path_str.split('.')
    node = yaml_data
    try:
        for key in keys:
            # 首先尝试作为字典键
            if isinstance(node, dict) and key in node:
                node = node[key]
            # 如果是列表，而键是数字，则尝试作为索引
            elif isinstance(node, list) and key.isdigit():
                node = node[int(key)]
            # 如果都失败，则路径无效
            else:
                return None
    except (KeyError, IndexError, TypeError):
        return None
    return node


def find_last_backpack_slot(yaml_data: Dict[str, Any]) -> int:
    """在背包中找到最后一个或最大的slot ID。"""
    # 动态查找背包节点
    backpack_node = find_node_by_path(yaml_data, 'state.inventory.backpack')
    if backpack_node is None:
        backpack_node = find_node_by_path(yaml_data, 'inventory.backpack')

    if not isinstance(backpack_node, dict):
        raise ValueError("在存档中无法找到或访问背包（Backpack）。")

    max_slot = -1
    slot_pattern = re.compile(r"slot_(\d+)")

    for key in backpack_node.keys():
        match = slot_pattern.match(key)
        if match:
            num = int(match.group(1))
            if num > max_slot:
                max_slot = num
    
    return max_slot


def sync_inventory_item_levels(yaml_data: Dict[str, Any]) -> Tuple[int, int, List[str]]:
    """
    Synchronizes the level of all items in the 'inventory' container to the character's level.
    """
    success_count = 0
    fail_count = 0
    failed_items_info = []

    if not isinstance(yaml_data, dict):
        return 0, 0, ["YAML data is not a valid dictionary."]

    # 1. Get Character Level
    try:
        exp_list = yaml_data.get("state", yaml_data).get("experience", [])
        char_exp = next((item for item in exp_list if isinstance(item, dict) and item.get("type") == "Character"), {})
        character_level = char_exp.get("level")
        if character_level is None:
            return 0, 0, ["无法确定角色等级。"]
    except (AttributeError, StopIteration):
        return 0, 0, ["在YAML数据中找不到角色经验值/等级信息。"]

    # 2. Find all items in the inventory
    # We use the existing walker to find all items, then filter by container.
    all_discovered_items = _walk_for_serials(yaml_data, [])
    
    inventory_items = []
    for path, item_data in all_discovered_items:
        # Heuristic to identify backpack items. This should be robust.
        is_in_inventory = False
        path_str = '/'.join(map(str, path))
        if 'inventory' in path and 'backpack' in path_str:
            is_in_inventory = True
        
        if is_in_inventory:
            inventory_items.append((path, item_data))

    if not inventory_items:
        return 0, 0, ["在背包中未找到任何物品。"]

    # 3. Iterate, decode, update, re-encode
    for path, item_data in inventory_items:
        original_serial = item_data.get("serial")
        slot_identifier = next((p for p in reversed(path) if p.startswith("slot_")), "未知格")

        if not original_serial:
            fail_count += 1
            failed_items_info.append(f"{slot_identifier}: 缺少序列号")
            continue

        # Decode
        decoded_full, _, err = decoder_logic.decode_serial_to_string(original_serial)
        if err:
            fail_count += 1
            failed_items_info.append(f"{slot_identifier}: 解码失败 ({err})")
            continue
            
        # Update level
        updated_decoded_str = update_level_in_decoded_str(decoded_full, character_level)
        if not updated_decoded_str:
            fail_count += 1
            failed_items_info.append(f"{slot_identifier}: 更新解码字符串中的等级失败")
            continue

        # Re-encode
        new_serial, err = b_encoder.encode_to_base85(updated_decoded_str)
        if err:
            fail_count += 1
            failed_items_info.append(f"{slot_identifier}: 重新编码失败 ({err})")
            continue
            
        # Write back to YAML object
        try:
            _set_by_path(yaml_data, path + ['serial'], new_serial)
            success_count += 1
        except (KeyError, IndexError) as e:
            fail_count += 1
            failed_items_info.append(f"{slot_identifier}: 回写YAML失败 ({e})")

    return success_count, fail_count, failed_items_info
