"""对话框几何诊断：通过 QQuickItem 映射打印 addPartDialog/skinDialog 内容的实际布局。

用法: python tools/huskar_dialog_geom.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_huskar.runtime import configure_runtime

runtime = configure_runtime()

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtWidgets import QApplication

from ui_huskar.__main__ import create_bridges
from ui_huskar.app_bridge import PAGE_KEYS


def find_by_name(root, object_name):
    from PyQt6.QtCore import QObject
    return [o for o in root.findChildren(QObject) if o.objectName() == object_name]


def main() -> int:
    sav = str(Path(__file__).resolve().parents[2] / "savbak" / "1.sav.2026-09-18-220302.bak")
    user_id = "76561198161284107"

    app = QApplication([])
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(runtime / "qml"))
    app_bridge, vms = create_bridges()
    engine.rootContext().setContextProperty("appBridge", app_bridge)
    for key, vm in vms.items():
        name = "vm" + "".join(p.title() for p in key.split("_"))
        engine.rootContext().setContextProperty(name, vm)
    qml = Path(__file__).resolve().parents[1] / "ui_huskar" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    window = engine.rootObjects()[0]
    window.resize(1480, 900)

    def step():
        app_bridge.openSave(sav, user_id)
        assert app_bridge.saveLoaded
        app_bridge.navigate(PAGE_KEYS.index("weapon_editor"))
        QTimer.singleShot(700, load)

    def load():
        vm = vms["weapon_editor"]
        vm.loadBrowserItem(0)
        catalog = vm.prepareAddPartCatalog()
        QTimer.singleShot(500, lambda: diag(catalog))

    def diag(catalog):
        dlg = find_by_name(window, "addPartDialog")
        print("addPartDialog objs:", len(dlg))
        if dlg:
            d = dlg[0]
            print("  width/height:", d.property("width"), d.property("height"))
            d.setProperty("catalog", catalog)
            d.open()
            QTimer.singleShot(600, lambda: opened(d))

    def opened(d):
        print("  visible:", d.property("visible"))
        ci = d.property("contentItem")
        print("  content w/h:", ci.property("width"), ci.property("height"))
        from PyQt6.QtCore import QObject
        # 找出对话框树里所有 ListView，打印模型数量与几何
        lists = [o for o in d.findChildren(QObject)
                 if o.metaObject().className() == "QQuickListView"]
        print("  listviews:", len(lists))
        for i, lv in enumerate(lists):
            print(f"    lv[{i}] x={lv.property('x'):.0f} y={lv.property('y'):.0f} "
                  f"w={lv.property('width'):.0f} h={lv.property('height'):.0f} "
                  f"count={lv.property('count')} contentH={lv.property('contentHeight'):.0f} "
                  f"visible={lv.property('visible')}")
        # 逐层打印 contentItem 子树（4 层深）
        def walk(item, depth=0):
            if depth > 9:
                return
            cls = item.metaObject().className()
            print(f"    {'  ' * depth}{cls} x={item.x():.0f} y={item.y():.0f} "
                  f"w={item.width():.0f} h={item.height():.0f} "
                  f"iw={item.implicitWidth():.0f} ih={item.implicitHeight():.0f} "
                  f"vis={item.isVisible()}")
            for c in item.childItems():
                walk(c, depth + 1)
        print("  --- contentItem subtree ---")
        walk(ci)
        app.quit()

    QTimer.singleShot(800, step)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
