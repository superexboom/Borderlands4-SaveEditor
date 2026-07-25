import copy
import hashlib
import os
import threading
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

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

from . import bl4_functions as bl4f
from . import b_encoder
import os
from datetime import datetime
from . import unlock_logic
from .unlock_data import VAULT_CARD_TOKENS

PUBLIC_KEY = bytes((0x35, 0xEC, 0x33, 0x77, 0xF3, 0x5D, 0xB0, 0xEA, 0xBE, 0x6B, 0x83, 0x11, 0x54, 0x03, 0xEB, 0xFB,
                    0x27, 0x25, 0x64, 0x2E, 0xD5, 0x49, 0x06, 0x29, 0x05, 0x78, 0xBD, 0x60, 0xBA, 0x4A, 0xA7, 0x87))


def validate_user_id_format(user_id: str) -> Tuple[bool, str]:
    user_id = str(user_id or "").strip()
    if not user_id:
        return False, "User ID cannot be empty"
    if user_id.isdigit():
        return (10 <= len(user_id) <= 20, "Valid Steam ID format" if 10 <= len(user_id) <= 20 else "Steam ID should contain 10-20 digits")
    if user_id.replace('-', '').replace('_', '').isalnum():
        return (10 <= len(user_id) <= 50, "Valid Epic Games ID format" if 10 <= len(user_id) <= 50 else "Epic Games ID should contain 10-50 characters")
    return False, "User ID contains invalid characters."


def infer_user_id_from_save_path(save_path: Union[str, Path]) -> str:
    """Return only the account directory anchored by SaveGames/<ID>/Profiles."""
    parts = Path(save_path).parts
    for index, part in enumerate(parts[:-2]):
        if part.casefold() != "savegames" or parts[index + 2].casefold() != "profiles":
            continue
        candidate = parts[index + 1]
        if validate_user_id_format(candidate)[0]:
            return candidate
    return ""


class SaveGameController:
    """
    处理所有与存档文件相关的业务逻辑，独立于UI框架。
    """

    def __init__(self):
        self.user_id: Optional[str] = None
        self.save_path: Optional[Path] = None
        self.platform: Optional[str] = None
        self.yaml_obj: Optional[Any] = None
        # 线程锁：后台 worker（批量添加等）会直接改 yaml_obj，dump/加密必须与之互斥
        self._lock = threading.RLock()
        # 脏标记与版本号：任何 mutation 都会 bump version 并置脏，供自动保存与视图按需刷新
        self._dirty = False
        self.version = 0
        self._dirty_listeners: List[Callable[[], None]] = []
        # 加载时深拷贝快照，用于"变更对比"与节点重置
        self._snapshot: Optional[Any] = None
        # 上次成功写盘内容的摘要（对 get_yaml_string() 的结果取 sha1），避免无变化重复写盘
        self._last_saved_digest: Optional[str] = None

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
        return validate_user_id_format(user_id)

    # ------------------------------------------------------------------
    # 脏标记 / 版本号（自动保存与按需刷新的基础）
    # ------------------------------------------------------------------
    @property
    def dirty(self) -> bool:
        return self._dirty

    def add_dirty_listener(self, callback: Callable[[], None]) -> None:
        if callback not in self._dirty_listeners:
            self._dirty_listeners.append(callback)

    def mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            self.version += 1
        for cb in list(self._dirty_listeners):
            try:
                cb()
            except Exception:
                pass

    def mark_clean(self, digest: Optional[str] = None) -> None:
        with self._lock:
            self._dirty = False
            if digest is not None:
                self._last_saved_digest = digest

    def compute_digest(self, yaml_string: Optional[str] = None) -> str:
        if yaml_string is None:
            yaml_string = self.get_yaml_string()
        return hashlib.sha1(yaml_string.encode("utf-8")).hexdigest()

    def is_content_saved(self) -> bool:
        """当前内容摘要与上次写盘一致（无需重复保存）。"""
        if self.yaml_obj is None or self._last_saved_digest is None:
            return False
        return self.compute_digest() == self._last_saved_digest

    # ------------------------------------------------------------------
    # 路径级读写 API（树编辑 / 批量删除的基础；全部加锁并置脏）
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_path(path: Union[tuple, list]) -> tuple:
        return tuple(path)

    def _resolve(self, path: Union[tuple, list]) -> Any:
        """按路径取节点。路径元素：dict 用 str 键，list 用 int 下标。"""
        node = self.yaml_obj
        for part in path:
            if isinstance(node, list):
                node = node[int(part)]
            elif isinstance(node, dict):
                node = node[part]
            else:
                raise KeyError(f"路径中断于: {part!r}")
        return node

    def get_node(self, path: Union[tuple, list]) -> Any:
        with self._lock:
            if self.yaml_obj is None:
                raise ValueError("存档未加载")
            return self._resolve(path)

    def set_value(self, path: Union[tuple, list], value: Any) -> None:
        with self._lock:
            if not path:
                raise ValueError("不能替换根节点")
            parent = self._resolve(path[:-1])
            last = path[-1]
            if isinstance(parent, list):
                parent[int(last)] = value
            else:
                parent[last] = value
        self.mark_dirty()

    def rename_key(self, path: Union[tuple, list], new_key: str) -> None:
        """重命名 dict 键（保持键的原始位置与值不变）。"""
        with self._lock:
            parent = self._resolve(path[:-1])
            old_key = path[-1]
            if not isinstance(parent, dict):
                raise ValueError("只有字典节点的键可以重命名")
            if old_key not in parent:
                raise KeyError(old_key)
            if new_key in parent:
                raise ValueError(f"键已存在: {new_key}")
            # 重建 dict 以保持键顺序
            rebuilt = {}
            for k, v in parent.items():
                rebuilt[new_key if k == old_key else k] = v
            parent.clear()
            parent.update(rebuilt)
        self.mark_dirty()

    def add_child(self, path: Union[tuple, list], key: Union[str, int, None], value: Any) -> tuple:
        """向 dict/list 节点添加子项，返回新子节点的完整路径。"""
        with self._lock:
            node = self._resolve(path)
            if isinstance(node, dict):
                skey = str(key)
                if skey in node:
                    raise ValueError(f"键已存在: {skey}")
                node[skey] = value
                new_path = tuple(path) + (skey,)
            elif isinstance(node, list):
                node.append(value)
                new_path = tuple(path) + (len(node) - 1,)
            else:
                raise ValueError("只能向字典或列表添加子节点")
        self.mark_dirty()
        return new_path

    def delete_node(self, path: Union[tuple, list]) -> Any:
        """删除单个节点，返回被删除的值（深拷贝，供撤销恢复）。"""
        with self._lock:
            parent = self._resolve(path[:-1])
            last = path[-1]
            if isinstance(parent, list):
                removed = parent.pop(int(last))
            else:
                removed = parent.pop(last)
        self.mark_dirty()
        return copy.deepcopy(removed)

    def delete_nodes(self, paths: List[Union[tuple, list]]) -> List[Tuple[tuple, Any]]:
        """批量删除。同父的列表下标按降序删除避免位移。返回 [(path, 深拷贝值)]。"""
        def sort_key(p):
            return (tuple(str(x) for x in p[:-1]), 1 if isinstance(p[-1], int) else 0,
                    -int(p[-1]) if isinstance(p[-1], int) else 0)
        ordered = sorted((tuple(p) for p in paths), key=sort_key)
        deleted: List[Tuple[tuple, Any]] = []
        with self._lock:
            for p in ordered:
                parent = self._resolve(p[:-1])
                last = p[-1]
                if isinstance(parent, list):
                    removed = parent.pop(int(last))
                else:
                    removed = parent.pop(last)
                deleted.append((p, copy.deepcopy(removed)))
        if deleted:
            self.mark_dirty()
        return deleted

    def restore_nodes(self, deleted: List[Tuple[tuple, Any]]) -> None:
        """撤销删除：按原路径写回（dict 按键，list 按下标 insert）。供 QUndoCommand 使用。"""
        def sort_key(item):
            p, _ = item
            return (tuple(str(x) for x in p[:-1]), 0 if isinstance(p[-1], int) else 1,
                    int(p[-1]) if isinstance(p[-1], int) else 0)
        with self._lock:
            for p, value in sorted(deleted, key=sort_key):
                parent = self._resolve(p[:-1])
                last = p[-1]
                if isinstance(parent, list):
                    parent.insert(min(int(last), len(parent)), copy.deepcopy(value))
                else:
                    parent[last] = copy.deepcopy(value)
        if deleted:
            self.mark_dirty()

    def find_backpack(self) -> Optional[Tuple[List[Any], Dict[str, Any]]]:
        """定位背包字典，返回 (路径, dict)。优先走已知结构，失败则递归兜底。"""
        root = self.yaml_obj
        if not isinstance(root, dict):
            return None
        try:
            node = root["state"]["inventory"]["items"]["backpack"]
            if isinstance(node, dict):
                return (["state", "inventory", "items", "backpack"], node)
        except (KeyError, TypeError):
            pass

        def walk(n, p):
            if isinstance(n, dict):
                for k, v in n.items():
                    if k == "backpack" and isinstance(v, dict) and any(str(kk).startswith("slot_") for kk in v):
                        return (p + [k], v)
                    r = walk(v, p + [k])
                    if r:
                        return r
            elif isinstance(n, list):
                for i, v in enumerate(n):
                    r = walk(v, p + [i])
                    if r:
                        return r
            return None
        return walk(root, [])

    def delete_backpack_range(self, start_slot: int, end_slot: int) -> List[Tuple[tuple, Any]]:
        """删除背包 slot_start 到 slot_end（含）的物品，返回 [(path, 深拷贝值)] 供撤销。"""
        if start_slot > end_slot:
            start_slot, end_slot = end_slot, start_slot
        found = self.find_backpack()
        if not found:
            raise ValueError("未找到背包节点")
        bp_path, backpack = found
        targets = [tuple(bp_path) + (f"slot_{n}",)
                   for n in range(start_slot, end_slot + 1)
                   if f"slot_{n}" in backpack]
        if not targets:
            return []
        return self.delete_nodes(targets)

    # ------------------------------------------------------------------
    # 快照 / 变更对比
    # ------------------------------------------------------------------
    def get_snapshot(self) -> Optional[Any]:
        return self._snapshot

    def diff_from_snapshot(self, cap: int = 2000) -> Tuple[set, set, set]:
        """与加载时快照对比，返回 (added, removed, modified) 路径集合（叶子级）。"""
        added: set = set()
        removed: set = set()
        modified: set = set()
        if self._snapshot is None or self.yaml_obj is None:
            return added, removed, modified

        def walk(old, new, path):
            if len(added) + len(removed) + len(modified) >= cap:
                return
            if isinstance(old, bool) != isinstance(new, bool):
                modified.add(path)
                return
            if isinstance(old, dict) and isinstance(new, dict):
                for k in old.keys() | new.keys():
                    if k not in old:
                        added.add(path + (k,))
                    elif k not in new:
                        removed.add(path + (k,))
                    else:
                        walk(old[k], new[k], path + (k,))
            elif isinstance(old, list) and isinstance(new, list):
                for i in range(min(len(old), len(new))):
                    walk(old[i], new[i], path + (i,))
                for i in range(len(old), len(new)):
                    added.add(path + (i,))
                for i in range(len(new), len(old)):
                    removed.add(path + (i,))
            elif type(old) is not type(new) or old != new:
                modified.add(path)
        with self._lock:
            walk(self._snapshot, self.yaml_obj, ())
        return added, removed, modified

    # ------------------------------------------------------------------
    # 持久化（原子写盘）
    # ------------------------------------------------------------------
    def save_to_disk(self, path_to_save: Optional[Union[str, Path]] = None) -> Path:
        """加密并原子写入：先写临时文件再 os.replace，写前把旧文件轮转为 .prev.bak。"""
        with self._lock:
            target = Path(path_to_save) if path_to_save else self.save_path
            if target is None:
                raise RuntimeError("没有可保存的目标路径")
            yaml_string = self.get_yaml_string()
            data = self.encrypt_save(yaml_string)

            target = Path(target)
            tmp_path = target.with_name(target.name + ".tmp")
            prev_bak = target.with_name(target.name + ".prev.bak")
            try:
                tmp_path.write_bytes(data)
                if target.exists():
                    prev_bak.write_bytes(target.read_bytes())
                os.replace(tmp_path, target)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            self.mark_clean(digest=hashlib.sha1(yaml_string.encode("utf-8")).hexdigest())
            return target

    def decrypt_save(self, file_path: Path, user_id: str, custom_backup_dir: Optional[str] = None) -> Tuple[str, str, str]:
        file_path = Path(file_path)
        candidate_user_id = user_id.strip()

        is_valid, validation_msg = self.validate_user_id(candidate_user_id)
        if not is_valid:
            raise ValueError(validation_msg)

        enc_data = file_path.read_bytes()

        # 尝试解密
        plain_data, platform_id, error = (None, None, None)
        try:
            # 尝试Epic
            plain_data = self._try_once(self._key_epic(candidate_user_id), enc_data, True)
            platform_id = "epic"
        except Exception as e:
            error = e
            try:
                # 尝试Steam
                plain_data = self._try_once(self._key_steam(candidate_user_id), enc_data, False)
                platform_id = "steam"
                error = None 
            except Exception as e2:
                error = e2

        if plain_data is not None and platform_id:
            yaml_obj = yaml.load(plain_data, Loader=self._get_yaml_loader())

            # 解密成功后创建备份
            ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            
            if custom_backup_dir and os.path.exists(custom_backup_dir) and os.path.isdir(custom_backup_dir):
                backup_name = f"{file_path.name}.{ts}.bak"
                backup_path = Path(custom_backup_dir) / backup_name
            else:
                backup_path = file_path.with_suffix(f".{ts}.bak")
            
            backup_path.write_bytes(enc_data)

            # Commit only after validation, decrypt, YAML parsing, and backup succeed.
            self.user_id = candidate_user_id
            self.save_path = file_path
            self.platform = platform_id
            self.yaml_obj = yaml_obj
            # 加载成功：记录快照与内容摘要，重置脏标记
            with self._lock:
                self._snapshot = copy.deepcopy(yaml_obj)
                self._dirty = False
                self.version += 1
                self._last_saved_digest = self.compute_digest()
            
            # 返回YAML内容、平台和备份文件名
            return plain_data.decode(errors="ignore"), platform_id, backup_path.name
        else:
            raise ValueError(f"Decryption failed: {error}")

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
        with self._lock:
            if not self.yaml_obj:
                return ""
            return yaml.safe_dump(self.yaml_obj, sort_keys=False, allow_unicode=True, indent=2)

    def update_yaml_object(self, yaml_string: str) -> bool:
        """Updates the internal yaml_obj from a string. Returns True on success."""
        try:
            new_obj = yaml.load(yaml_string, Loader=self._get_yaml_loader())
        except Exception:
            return False
        with self._lock:
            self.yaml_obj = new_obj
        self.mark_dirty()
        return True

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
        with self._lock:
            if not self.yaml_obj:
                return None
            result = bl4f.add_item_to_backpack(self.yaml_obj, serial, flag)
        if result:
            self.mark_dirty()
        return result

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

        data["is_profile_save"] = unlock_logic.is_profile_save(self.yaml_obj)

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

        for card in VAULT_CARD_TOKENS:
            currency_key = card.get("currency_key") if isinstance(card, dict) else None
            if not isinstance(currency_key, str):
                continue
            path = cur_paths.get(currency_key)
            value = ""
            if path:
                try:
                    node = self.yaml_obj
                    for part in path:
                        node = node[part]
                    value = str(node)
                except (KeyError, IndexError, TypeError):
                    pass
            data[currency_key] = value
        
        return data

    def apply_character_data(self, data: Dict[str, Any], cur_paths: Dict) -> bool:
        """将角色和货币数据应用到 self.yaml_obj。"""
        with self._lock:
            if not self.yaml_obj:
                return False
            # bl4_functions.apply_character_and_currency_changes 现在直接接收数据字典。
            ok = bl4f.apply_character_and_currency_changes(data, self.yaml_obj, cur_paths)
        if ok:
            self.mark_dirty()
        return ok

    def sync_inventory_levels(self) -> Tuple[int, int, List[str]]:
        """同步背包物品等级到角色等级。"""
        with self._lock:
            if not self.yaml_obj:
                return 0, 0, ["存档未加载"]
            result = bl4f.sync_inventory_item_levels(self.yaml_obj)
        if result[0] > 0:
            self.mark_dirty()
        return result

    def scan_save_folders(self, custom_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """扫描无主之地4存档文件夹并返回找到的存档文件列表。"""
        found_files = []
        try:
            target_path = None
            if custom_path and os.path.exists(custom_path) and os.path.isdir(custom_path):
                target_path = Path(custom_path)

            if not target_path or not target_path.is_dir():
                return []

            for full_path in target_path.rglob('*'):
                if not full_path.is_file() or full_path.suffix.lower() != '.sav':
                    continue
                try:
                    stat = full_path.stat()
                    found_files.append({
                        "name": full_path.name,
                        "id": infer_user_id_from_save_path(full_path),
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                        "size_kb": stat.st_size / 1024,
                        "full_path": str(full_path),
                    })
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

        result_msg: Optional[str] = None
        try:
            with self._lock:
                # 在YAML对象中定位到物品节点
                node = self.yaml_obj
                # Handle path traversal including list indices which might be strings
                for key in item_path[:-1]:
                    if isinstance(node, list) and isinstance(key, str) and key.isdigit():
                        node = node[int(key)]
                    else:
                        node = node[key]

                last_key = item_path[-1]
                if isinstance(node, list) and isinstance(last_key, str) and last_key.isdigit():
                    item_node = node[int(last_key)]
                else:
                    item_node = node[last_key]

                new_level_val = new_item_data.get("level")
                decoded_id_str = new_item_data.get("decoded_parts", "").strip()

                # 优先级1: 等级改变，需要重编码
                # Handle both int and string input for level
                new_level_int = None
                if isinstance(new_level_val, int):
                    new_level_int = new_level_val
                elif isinstance(new_level_val, str) and new_level_val.isdigit():
                    new_level_int = int(new_level_val)

                if new_level_int is not None and str(new_level_int) != str(original_item_data.get("level")):
                    new_level = new_level_int
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
                    result_msg = f"成功从新等级 {new_level} 重新编码物品。"

                # 优先级2: 解码ID改变，需要重编码
                elif decoded_id_str and decoded_id_str != original_item_data.get("decoded_parts"):
                    full_decoded_str_base = original_item_data.get("decoded_full", "").split("||")[0]
                    reconstructed_full_str = f"{full_decoded_str_base}|| {decoded_id_str} |"

                    new_serial, err = b_encoder.encode_to_base85(reconstructed_full_str)
                    if err:
                        raise ValueError(f"从解码ID重新编码失败: {err}")

                    item_node['serial'] = new_serial
                    result_msg = "成功从解码ID重新编码物品。"

                # 如果没有重编码，只更新序列号
                else:
                    new_serial = new_item_data.get("serial")
                    if new_serial and new_serial != item_node.get('serial'):
                        item_node['serial'] = new_serial
                        result_msg = "成功更新物品序列号。"

        except (KeyError, IndexError) as e:
            raise ValueError(f"在存档中找不到物品路径: {item_path} ({e})")

        if result_msg is not None:
            self.mark_dirty()
            return result_msg
        return "未检测到任何更改。"

    def apply_unlock_preset(self, preset_name: str, params: Dict[str, Any] = None) -> bool:
        with self._lock:
            if not self.yaml_obj:
                raise RuntimeError("No save loaded")
            ok = self._apply_unlock_preset_locked(preset_name, params)
        if ok:
            self.mark_dirty()
        return ok

    def _apply_unlock_preset_locked(self, preset_name: str, params: Dict[str, Any] = None) -> bool:
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
            elif preset_name == "unlock_all_cosmetics":
                unlock_logic.unlock_all_cosmetics(data)
            elif preset_name == "unlock_all_vault_card_rewards":
                unlock_logic.unlock_all_vault_card_rewards(data)
            elif preset_name == "max_ammo":
                unlock_logic.max_ammo(data)
            elif preset_name == "unlock_all_specialization":
                unlock_logic.unlock_all_specialization(data)
            elif preset_name == "unlock_postgame":
                unlock_logic.unlock_postgame(data)
            elif preset_name == "unlock_max_everything":
                if unlock_logic.is_profile_save(data):
                    unlock_logic.clear_map_fog(data)
                    unlock_logic.discover_all_locations(data)
                    unlock_logic.complete_all_safehouse_missions(data)
                    unlock_logic.complete_all_missions(data)
                    unlock_logic.complete_all_collectibles(data)
                    unlock_logic.set_max_sdu(data)
                    unlock_logic.unlock_vault_powers(data)
                    unlock_logic.unlock_all_hover_drives(data)
                    unlock_logic.unlock_all_cosmetics(data)
                    unlock_logic.unlock_all_vault_card_rewards(data)
                else:
                    unlock_logic.max_ammo(data)
                    unlock_logic.max_currency(data)
                    unlock_logic.complete_all_collectibles(data)
                    unlock_logic.complete_all_achievements(data)
                    unlock_logic.complete_all_missions(data)
                    unlock_logic.unlock_vault_powers(data)
                    unlock_logic.unlock_postgame(data)
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
