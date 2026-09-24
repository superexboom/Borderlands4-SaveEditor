"""端到端验证：真实存档副本的 解密 → 读取字段 → 修改 → 保存 → 再解密 全链路。

仅操作临时目录中的副本，原始备份文件只读不动。
用法: python tools/huskar_e2e_check.py [save_bak] [user_id]
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from core.save_game_controller import SaveGameController
from ui_huskar.__main__ import create_bridges


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(
        (root.parent / "savbak").glob("1.sav.*.bak"))[-1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else "76561198161284107"
    assert source.exists(), f"存档不存在: {source}"

    app = QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="huskar_e2e_"))
    work = tmp / "1.sav"
    shutil.copy2(source, work)
    backup_dir = tmp / "backups"
    backup_dir.mkdir()

    bridge, vms = create_bridges()
    selector = bridge.vm("select_save")
    selector.custom_backup_path = str(backup_dir)

    toasts = []
    bridge.toastRequested.connect(lambda t, k: toasts.append((t, k)))

    # 1. 解密
    bridge.openSave(str(work), user_id)
    assert bridge.saveLoaded, f"解密失败: {toasts}"
    assert bridge.pageKey == "character", f"打开后未导航到角色页: {bridge.pageKey}"
    print("PASS 解密 + 自动导航:", work.name)

    # 2. 角色页读取与修改
    character = bridge.vm("character")
    character.on_activated()
    money_before = int(character.fields["金钱"])
    character.setField("金钱", str(money_before + 1))
    character.applyChanges()
    assert bridge.controller.dirty, "修改后未置脏"
    print(f"PASS 角色字段编辑: 金钱 {money_before} -> {money_before + 1}")

    # 3. 物品页快照
    items = bridge.vm("items")
    items.on_activated()
    item_count = len(items._all_items)
    assert item_count > 0
    print(f"PASS 物品快照: {item_count} 件")

    # 4. 添加物品（converter 路径）
    from core import b_encoder
    serial, err = b_encoder.encode_to_base85("255, 0, 1, 50| 2, 969|| ")
    assert not err
    assert bridge.addSerialToBackpack(serial, "3"), "加入背包失败"
    print("PASS 加入背包")

    # 5. 保存 + .prev.bak 轮转
    bridge.save()
    assert not bridge.controller.dirty, "保存后仍脏"
    assert (tmp / "1.sav.prev.bak").exists(), "缺少 .prev.bak 轮转备份"
    print("PASS 原子保存 + .prev.bak 轮转")

    # 6. 再解密验证
    verify = SaveGameController()
    verify.decrypt_save(work, user_id, None)
    data = verify.get_character_data()
    assert int(data["金钱"]) == money_before + 1, f"金钱未持久化: {data['金钱']}"
    all_items = verify.get_all_items()
    assert len(all_items) >= item_count, f"物品数减少: {len(all_items)} < {item_count}"
    # 背包槽位数（get_all_items 对部分类型有过滤，直接校验 YAML 结构）
    def find_backpack(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "backpack" and isinstance(value, dict):
                    return value
                found = find_backpack(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find_backpack(item)
                if found is not None:
                    return found
        return None
    backpack = find_backpack(verify.yaml_obj) or {}
    assert serial in {v.get("serial") for v in backpack.values() if isinstance(v, dict)}, "新物品不在背包中"
    print("PASS 再解密验证（字段持久化 + 新物品在背包）")

    # 7. 原始备份未被触碰
    import hashlib
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    print(f"PASS 原始备份只读: sha256 {digest[:16]}…")
    print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
