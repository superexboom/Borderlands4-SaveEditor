import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
except ImportError:
    AES = None
    pad = None

try:
    import yaml
except ImportError:
    yaml = None

import bl4_functions as bl4f
import b_encoder
import os
from datetime import datetime
import unlock_logic
from unlock_data import CHARACTER_CLASSES

PUBLIC_KEY = bytes((0x35, 0xEC, 0x33, 0x77, 0xF3, 0x5D, 0xB0, 0xEA, 0xBE, 0x6B, 0x83, 0x11, 0x54, 0x03, 0xEB, 0xFB,
                    0x27, 0x25, 0x64, 0x2E, 0xD5, 0x49, 0x06, 0x29, 0x05, 0x78, 0xBD, 0x60, 0xBA, 0x4A, 0xA7, 0x87))


class SaveGameController:
    """
    处理所有与存档文件相关的业务逻辑，独立于UI框架。
    """

    def __init__(self):
        self.user_id: Optional[str] = None
        self.save_path: Optional[Path] = None
        self.platform: Optional[str] = None
        self.yaml_obj: Optional[Any] = None

    def _adler32(self, b: bytes) -> int:
        return zlib.adler32(b) & 0xFFFFFFFF

    def _get_yaml_loader(self):
        if yaml is None:
            raise RuntimeError("PyYAML is not installed. Install with: pip install pyyaml")

        class AnyTagLoader(yaml.SafeLoader):
            pass

        def _ignore_any(loader: AnyTagLoader, tag_suffix: str, node: 'yaml.Node'):
            if isinstance(node, yaml.ScalarNode): return loader.construct_scalar(node)
            if isinstance(node, yaml.SequenceNode): return loader.construct_sequence(node)
            if isinstance(node, yaml.MappingNode): return loader.construct_mapping(node)
            return None

        AnyTagLoader.add_multi_constructor("", _ignore_any)
        return AnyTagLoader

    def _key_epic(self, uid: str) -> bytes:
        wid = uid.strip().encode("utf-16le")
        k = bytearray(PUBLIC_KEY)
        n = min(len(wid), len(k))
        for i in range(n):
            k[i] ^= wid[i]
        return bytes(k)

    def _key_steam(self, uid: str) -> bytes:
        digits = ''.join(ch for ch in uid if ch.isdigit())
        sid = int(digits or "0", 10).to_bytes(8, "little", signed=False)
        k = bytearray(PUBLIC_KEY)
        for i, b in enumerate(sid):
            k[i % len(k)] ^= b
        return bytes(k)

    def _strip_pkcs7(self, buf: bytes) -> bytes:
        n = buf[-1]
        if 1 <= n <= 16 and all(buf[-i] == n for i in range(1, n + 1)):
            return buf[:-n]
        return buf

    def _aes_dec(self, b, k):
        if AES is None:
            raise RuntimeError("PyCryptodome is required for encrypt/decrypt. Install with: pip install pycryptodome")
        return AES.new(k, AES.MODE_ECB).decrypt(b)

    def _aes_enc(self, b, k):
        if AES is None:
            raise RuntimeError("PyCryptodome is required for encrypt/decrypt. Install with: pip install pycryptodome")
        return AES.new(k, AES.MODE_ECB).encrypt(b)

    def _try_once(self, key: bytes, enc: bytes, checksum_be: bool) -> bytes:
        try:
            dec = self._aes_dec(enc, key)
        except Exception as e:
            raise ValueError(f"AES decryption failed: {e}")
        try:
            unp = self._strip_pkcs7(dec)
        except Exception as e:
            raise ValueError(f"PKCS7 padding removal failed: {e}")
        if len(unp) < 8:
            raise ValueError(f"Data too short after unpadding: {len(unp)} bytes (min 8 required)")

        trailer = unp[-8:]
        chk = int.from_bytes(trailer[:4], "big" if checksum_be else "little")
        ln = int.from_bytes(trailer[4:], "little")

        try:
            plain = zlib.decompress(unp)
        except Exception:
            try:
                plain = zlib.decompress(unp[:-8])
            except Exception as e2:
                raise ValueError(f"Zlib decompression failed: {e2}")

        actual_checksum = self._adler32(plain)
        if actual_checksum != chk:
            pass  # Or log a warning
        if len(plain) != ln:
            raise ValueError(f"Length mismatch: got {len(plain)}, expected {ln}")
        return plain

    def validate_user_id(self, user_id: str) -> Tuple[bool, str]:
        if not user_id or not user_id.strip():
            return False, "User ID cannot be empty"
        user_id = user_id.strip()
        if user_id.isdigit():
            if len(user_id) < 10: return False, "Steam ID too short (should be 17 digits)"
            if len(user_id) > 20: return False, "Steam ID too long (should be 17 digits)"
            return True, "Valid Steam ID format"
        if user_id.replace('-', '').replace('_', '').isalnum():
            if len(user_id) < 10: return False, "Epic Games ID too short"
            if len(user_id) > 50: return False, "Epic Games ID too long"
            return True, "Valid Epic Games ID format"
        return False, "User ID contains invalid characters."

    def decrypt_save(self, file_path: Path, user_id: str) -> Tuple[str, str, str]:
        self.user_id = user_id.strip()
        self.save_path = file_path

        is_valid, validation_msg = self.validate_user_id(self.user_id)
        if not is_valid:
            raise ValueError(f"无效的用户ID: {validation_msg}")

        enc_data = self.save_path.read_bytes()

        # 尝试解密
        plain_data, platform_id, error = (None, None, None)
        try:
            # 尝试Epic
            plain_data = self._try_once(self._key_epic(self.user_id), enc_data, True)
            platform_id = "epic"
        except Exception as e:
            error = e
            try:
                # 尝试Steam
                plain_data = self._try_once(self._key_steam(self.user_id), enc_data, False)
                platform_id = "steam"
                error = None 
            except Exception as e2:
                error = e2

        if plain_data is not None and platform_id:
            # 解密成功后创建备份
            ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            backup_path = self.save_path.with_suffix(f".{ts}.bak")
            backup_path.write_bytes(enc_data)

            self.platform = platform_id
            self.yaml_obj = yaml.load(plain_data, Loader=self._get_yaml_loader())
            
            # 返回YAML内容、平台和备份文件名
            return plain_data.decode(errors="ignore"), platform_id, backup_path.name
        else:
            # 如果两种方法都失败，则抛出详细错误
            error_msg = ("解密存档文件失败。这通常意味着:\n"
                         "1. 错误的用户ID - 请确保您使用的是正确的Epic Games或Steam用户ID\n"
                         "2. 损坏的存档文件 - 存档文件可能已损坏\n"
                         "3. 错误的存档文件 - 这可能不是一个有效的BL4存档文件\n\n"
                         f"错误详情: {error}")
            raise ValueError(error_msg)

    def encrypt_save(self, yaml_string: str) -> bytes:
        if not self.platform or not self.user_id:
            raise RuntimeError("Cannot encrypt without a decrypted platform and user ID.")
        if AES is None or pad is None:
            raise RuntimeError("PyCryptodome is required for encryption.")

        key = self._key_epic(self.user_id) if self.platform == "epic" else self._key_steam(self.user_id)
        
        # We use the provided yaml_string to ensure manual edits are included
        yb = yaml_string.encode("utf-8")
        comp = zlib.compress(yb, 9)
        trailer = self._adler32(yb).to_bytes(4, "big" if self.platform == "epic" else "little") + len(yb).to_bytes(4, "little")
        pt = pad(comp + trailer, 16, style="pkcs7")
        return self._aes_enc(pt, key)

    def get_yaml_string(self) -> str:
        if not self.yaml_obj:
            return ""
        return yaml.safe_dump(self.yaml_obj, sort_keys=False, allow_unicode=True, indent=2)

    def update_yaml_object(self, yaml_string: str) -> bool:
        """Updates the internal yaml_obj from a string. Returns True on success."""
        try:
            self.yaml_obj = yaml.load(yaml_string, Loader=self._get_yaml_loader())
            return True
        except Exception:
            return False

    def get_all_items(self) -> List[Dict[str, Any]]:
        if not self.yaml_obj:
            print("[CONTROLLER_LOG] get_all_items: No YAML object found, returning empty list.")
            return []
        print("[CONTROLLER_LOG] get_all_items: YAML object found, calling bl4f.process_and_load_items.")
        try:
            items = bl4f.process_and_load_items(self.yaml_obj)
            print(f"[CONTROLLER_LOG] get_all_items: Successfully processed {len(items)} items.")
            return items
        except Exception as e:
            print(f"[CONTROLLER_LOG] CRITICAL: Exception in bl4f.process_and_load_items: {e}")
            return []

    def add_item_to_backpack(self, serial: str, flag: str) -> Optional[List[Union[str, int]]]:
        if not self.yaml_obj:
            return None
        return bl4f.add_item_to_backpack(self.yaml_obj, serial, flag)

    def encode_serial(self, decoded_str: str) -> Tuple[Optional[str], Optional[str]]:
        return b_encoder.encode_to_base85(decoded_str)

    def get_character_data(self) -> Optional[Dict[str, Any]]:
        """从 self.yaml_obj 提取角色和货币数据。"""
        if not isinstance(self.yaml_obj, dict):
            return None

        data = {}
        # 查找货币路径
        cur_paths = bl4f.find_currency_paths(self.yaml_obj)
        data['cur_paths'] = cur_paths

        root_node = self.yaml_obj.get("state", self.yaml_obj)
        if not isinstance(root_node, dict):
            root_node = self.yaml_obj

        data["名称"] = str(root_node.get("char_name", ""))
        data["难度"] = str(root_node.get("player_difficulty", ""))

        exp_list = root_node.get("experience", [])
        char_exp = next((item for item in exp_list if isinstance(item, dict) and item.get("type") == "Character"), {})
        spec_exp = next((item for item in exp_list if isinstance(item, dict) and item.get("type") == "Specialization"), {})

        data["角色等级"] = str(char_exp.get("level", ""))
        data["角色经验值"] = str(char_exp.get("points", ""))
        data["专精等级"] = str(spec_exp.get("level", ""))
        data["专精点数"] = str(spec_exp.get("points", ""))

        for key, label in [("cash", "金钱"), ("eridium", "镒矿")]:
            path = cur_paths.get(key)
            val = ""
            if path:
                try:
                    temp = self.yaml_obj
                    for p in path: temp = temp[p]
                    val = str(temp)
                except (KeyError, IndexError, TypeError):
                    val = ""
            data[label] = val
        
        return data

    def apply_character_data(self, data: Dict[str, Any], cur_paths: Dict) -> bool:
        """将角色和货币数据应用到 self.yaml_obj。"""
        if not self.yaml_obj:
            return False
        
        # bl4_functions.apply_character_and_currency_changes 现在直接接收数据字典。
        return bl4f.apply_character_and_currency_changes(data, self.yaml_obj, cur_paths)

    def sync_inventory_levels(self) -> Tuple[int, int, List[str]]:
        """同步背包物品等级到角色等级。"""
        if not self.yaml_obj:
            return 0, 0, ["存档未加载"]
        
        return bl4f.sync_inventory_item_levels(self.yaml_obj)

    def scan_default_save_folders(self) -> List[Dict[str, Any]]:
        """扫描默认的无主之地4存档文件夹并返回找到的存档文件列表。"""
        found_files = []
        try:
            # documents_path = 'C:/Users/SuperExboom/Documents' # Hardcoded for this environment
            documents_path = os.path.expanduser('~/Documents')
            save_games_path = Path(documents_path) / "My Games" / "Borderlands 4" / "Saved" / "SaveGames"

            if not save_games_path.is_dir():
                return []

            for id_dir in save_games_path.iterdir():
                if id_dir.is_dir() and id_dir.name.isalnum(): # 文件夹名通常是ID
                    platform_id = id_dir.name
                    # 遍历ID文件夹内的所有.sav文件
                    for sub_dir, _, files in os.walk(id_dir):
                        for file in files:
                            if file.lower().endswith('.sav'):
                                full_path = Path(sub_dir) / file
                                try:
                                    stat = full_path.stat()
                                    file_info = {
                                        "name": full_path.name,
                                        "id": platform_id,
                                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                                        "size_kb": stat.st_size / 1024,
                                        "full_path": str(full_path)
                                    }
                                    found_files.append(file_info)
                                except FileNotFoundError:
                                    continue
        except Exception as e:
            print(f"扫描存档文件夹时出错: {e}")
        
        return sorted(found_files, key=lambda x: x['modified'], reverse=True)

    def update_item(self, item_path: List[Any], original_item_data: Dict[str, Any], new_item_data: Dict[str, Any]) -> str:
        """
        更新单个物品。根据变化的字段决定是否需要重新编码。
        返回一个表示操作结果的字符串消息。
        """
        if not self.yaml_obj:
            raise ValueError("存档未加载，无法更新物品。")
        
        try:
            # 在YAML对象中定位到物品节点
            node = self.yaml_obj
            for key in item_path[:-1]:
                node = node[key]
            item_node = node[item_path[-1]]

            new_level_str = new_item_data.get("level")
            decoded_id_str = new_item_data.get("decoded_parts", "").strip()

            # 优先级1: 等级改变，需要重编码
            if new_level_str and new_level_str.isdigit() and new_level_str != str(original_item_data.get("level")):
                new_level = int(new_level_str)
                full_decoded_str = original_item_data.get("decoded_full", "")
                if not full_decoded_str:
                    raise ValueError("无法更新，原始物品缺少'decoded_full'信息。")
                
                updated_decoded_str = bl4f.update_level_in_decoded_str(full_decoded_str, new_level)
                if not updated_decoded_str:
                    raise ValueError("无法在解码字符串中更新等级。")
                
                new_serial, err = b_encoder.encode_to_base85(updated_decoded_str, new_level=new_level)
                if err:
                    raise ValueError(f"从新等级重新编码失败: {err}")
                
                item_node['serial'] = new_serial
                return f"成功从新等级 {new_level} 重新编码物品。"

            # 优先级2: 解码ID改变，需要重编码
            elif decoded_id_str and decoded_id_str != original_item_data.get("decoded_parts"):
                full_decoded_str_base = original_item_data.get("decoded_full", "").split("||")[0]
                reconstructed_full_str = f"{full_decoded_str_base}|| {decoded_id_str} |"
                
                new_serial, err = b_encoder.encode_to_base85(reconstructed_full_str)
                if err:
                    raise ValueError(f"从解码ID重新编码失败: {err}")
                
                item_node['serial'] = new_serial
                return "成功从解码ID重新编码物品。"
            
            # 如果没有重编码，只更新序列号
            else:
                new_serial = new_item_data.get("serial")
                if new_serial and new_serial != item_node.get('serial'):
                    item_node['serial'] = new_serial
                    return "成功更新物品序列号。"

            return "未检测到任何更改。"

        except (KeyError, IndexError) as e:
            raise ValueError(f"在存档中找不到物品路径: {item_path} ({e})")

    def apply_unlock_preset(self, preset_name: str, params: Dict[str, Any] = None) -> bool:
        if not self.yaml_obj:
            raise RuntimeError("No save loaded")
            
        data = self.yaml_obj
        params = params or {}
        
        try:
            if preset_name == "clear_map_fog":
                unlock_logic.clear_map_fog(data)
            elif preset_name == "discover_all_locations":
                unlock_logic.discover_all_locations(data)
            elif preset_name == "complete_all_safehouse_missions":
                unlock_logic.complete_all_safehouse_missions(data)
            elif preset_name == "complete_all_collectibles":
                unlock_logic.complete_all_collectibles(data)
            elif preset_name == "complete_all_challenges":
                unlock_logic.complete_all_challenges(data)
            elif preset_name == "complete_all_achievements":
                unlock_logic.complete_all_achievements(data)
            elif preset_name == "complete_all_story_missions":
                unlock_logic.complete_all_story_missions(data)
            elif preset_name == "complete_all_missions":
                unlock_logic.complete_all_missions(data)
            elif preset_name == "set_character_class":
                class_key = params.get("class_key")
                if class_key:
                    unlock_logic.set_character_class(data, class_key)
            elif preset_name == "set_character_to_max_level":
                unlock_logic.set_character_to_max_level(data)
            elif preset_name == "set_max_sdu":
                unlock_logic.set_max_sdu(data)
            elif preset_name == "unlock_vault_powers":
                unlock_logic.unlock_vault_powers(data)
            elif preset_name == "unlock_all_hover_drives":
                unlock_logic.unlock_all_hover_drives(data)
            elif preset_name == "unlock_all_specialization":
                unlock_logic.unlock_all_specialization(data)
            elif preset_name == "unlock_postgame":
                unlock_logic.unlock_postgame(data)
            elif preset_name == "unlock_max_everything":
                # Implement the combo manually or add a helper in unlock_logic
                # Based on JS:
                unlock_logic.max_ammo(data)
                unlock_logic.max_currency(data)
                unlock_logic.clear_map_fog(data)
                unlock_logic.discover_all_locations(data)
                unlock_logic.complete_all_collectibles(data)
                unlock_logic.complete_all_achievements(data)
                unlock_logic.complete_all_missions(data)
                unlock_logic.set_max_sdu(data)
                unlock_logic.unlock_vault_powers(data)
                unlock_logic.unlock_postgame(data)
                unlock_logic.unlock_all_hover_drives(data)
                unlock_logic.unlock_all_specialization(data)
                unlock_logic.complete_all_challenges(data)
                unlock_logic.set_character_to_max_level(data)
            else:
                print(f"Unknown preset: {preset_name}")
                return False
            return True
        except Exception as e:
            print(f"Error applying preset {preset_name}: {e}")
            import traceback
            traceback.print_exc()
            return False
