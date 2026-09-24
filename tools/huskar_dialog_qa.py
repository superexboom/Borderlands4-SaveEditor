"""QA 截图 + QML warnings 全文输出（验证 473 行 undefined 残留是否清除）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_huskar.runtime import configure_runtime

runtime = configure_runtime()

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface
from PyQt6.QtWidgets import QApplication

from ui_huskar.__main__ import create_bridges
from ui_huskar.app_bridge import PAGE_KEYS

QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".local/dialog_qa4")
    out_dir.mkdir(parents=True, exist_ok=True)
    sav = str(Path(__file__).resolve().parents[2] / "savbak" / "1.sav.2026-09-18-220302.bak")
    user_id = "76561198161284107"

    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(runtime / "qml"))
    warnings: list[str] = []
    engine.warnings.connect(lambda values: warnings.extend(
        f"{item.url().toString()}:{item.line()}: {item.description()}" for item in values))
    app_bridge, vms = create_bridges()
    engine.rootContext().setContextProperty("appBridge", app_bridge)
    for key, vm in vms.items():
        name = "vm" + "".join(part.title() for part in key.split("_"))
        engine.rootContext().setContextProperty(name, vm)
    qml_path = Path(__file__).resolve().parents[1] / "ui_huskar" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    window = engine.rootObjects()[0]
    window.resize(1480, 900)
    window.show()

    def step():
        app_bridge.openSave(sav, user_id)
        app_bridge.navigate(PAGE_KEYS.index("weapon_editor"))
        QTimer.singleShot(700, load)

    def load():
        vm = vms["weapon_editor"]
        vm.loadBrowserItem(0)
        catalog = vm.prepareAddPartCatalog()
        from PyQt6.QtCore import QObject
        dialogs = [o for o in window.findChildren(QObject) if o.objectName() == "addPartDialog"]
        if dialogs:
            dialogs[0].setProperty("catalog", catalog)
            dialogs[0].open()
            QTimer.singleShot(700, lambda: shot("addPartDialog", close_then_skin))
        else:
            app.quit()

    def shot(name, next_step):
        window.grabWindow().save(str(out_dir / f"{name}.png"), "PNG")
        print("SHOT", name)
        next_step()

    def close_then_skin():
        from PyQt6.QtCore import QObject
        dialogs = [o for o in window.findChildren(QObject) if o.objectName() == "addPartDialog"]
        dialogs[0].close()
        QTimer.singleShot(400, open_skin)

    def open_skin():
        from PyQt6.QtCore import QObject
        vms["weapon_editor"].prepareSkinOptions()
        dialogs = [o for o in window.findChildren(QObject) if o.objectName() == "skinDialog"]
        dialogs[0].open()
        QTimer.singleShot(700, lambda: shot("skinDialog", finish))

    def finish():
        print("WARNINGS", len(warnings))
        for w in warnings:
            print("W:", w)
        app.quit()

    QTimer.singleShot(900, step)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
