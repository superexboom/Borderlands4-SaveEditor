"""HuskarUI 界面 QA 截图：真实窗口渲染（offscreen 下 RHI 截屏会丢文字，故用 windows 平台）。

用法:
    python tools/huskar_qa_capture.py [out_dir] [page_index ...]
环境变量:
    HUSKAR_QA_SIZE=1480x900  HUSKAR_QA_LANG=zh-CN
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui_huskar.runtime import configure_runtime

runtime = configure_runtime()

from PyQt6.QtCore import QTimer, QUrl, QSettings
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface
from PyQt6.QtWidgets import QApplication

from ui_huskar.__main__ import create_bridges
from ui_huskar.app_bridge import PAGE_KEYS

QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".local/qa2")
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = [int(a) for a in sys.argv[2:]] or [0]
    size = os.environ.get("HUSKAR_QA_SIZE", "1480x900").split("x")

    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(runtime / "qml"))
    warnings: list[str] = []
    engine.warnings.connect(lambda values: warnings.extend(
        f"{item.url().toString()}:{item.line()}: {item.description()}" for item in values))
    app_bridge, vms = create_bridges(QSettings(str(out_dir.resolve() / "qa.ini"), QSettings.Format.IniFormat))
    lang = os.environ.get("HUSKAR_QA_LANG")
    if lang:
        app_bridge.setLanguage(lang)
    load_yaml = os.environ.get("HUSKAR_QA_LOAD_YAML")
    if load_yaml:
        app_bridge.controller.update_yaml_object(
            Path(load_yaml).read_text(encoding="utf-8"))
        app_bridge.controller.mark_clean()
        for vm in vms.values():
            vm.mark_stale()
    load_sav = os.environ.get("HUSKAR_QA_LOAD_SAV")
    if load_sav:
        app_bridge.openSave(load_sav, os.environ.get("HUSKAR_QA_USER_ID", ""))
        assert app_bridge.saveLoaded, "QA 存档解密失败"
        app_bridge.navigate(0)
    engine.rootContext().setContextProperty("appBridge", app_bridge)
    for key, vm in vms.items():
        name = "vm" + "".join(part.title() for part in key.split("_"))
        engine.rootContext().setContextProperty(name, vm)
    qml_path = Path(__file__).resolve().parents[1] / "ui_huskar" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    roots = engine.rootObjects()
    if not roots:
        print("NO_ROOT_OBJECT")
        print(*warnings, sep="\n")
        return 2
    window = roots[0]
    window.resize(int(size[0]), int(size[1]))
    window.show()

    queue = list(pages)

    def step():
        if queue:
            page = queue.pop(0)
            app_bridge.navigate(page)
            QTimer.singleShot(700, step)
            return
        for page in pages:
            app_bridge.navigate(page)
            app.processEvents()
            shot = window.grabWindow()
            path = out_dir / f"page-{page:02d}-{PAGE_KEYS[page]}.png"
            shot.save(str(path), "PNG")
            print("SHOT", path)
        print("WARNINGS", len(warnings))
        for warning in warnings[:20]:
            print("WARNING", warning)
        app.quit()

    QTimer.singleShot(900, step)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
