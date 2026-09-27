from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Force UTF-8 stdio so bilingual log prints don't crash a frozen Windows build
# (cp1252 can't encode Chinese). A windowed exe has no stdout/stderr at all, so
# route those to the null device.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is None:
        setattr(sys, _stream_name, open(os.devnull, "w", encoding="utf-8"))
    else:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

from ui_huskar.runtime import configure_runtime

RUNTIME = configure_runtime()

from PyQt6.QtCore import QLibraryInfo, QTimer, QUrl
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface
from PyQt6.QtWidgets import QApplication

from ui_huskar.app_bridge import AppBridge
from ui_huskar.viewmodels.base import REGISTRY

# 退出期 QML 拆毁时，仍存活的绑定会对已失效的上下文对象重估，
# 打印一批 "TypeError: Cannot read/call ... of null"。这些是无害的拆毁噪音，
# 仅在 exec 返回后过滤（正常运行期同型错误仍然照打，避免掩盖真问题）。
_TEARDOWN = False
_TEARDOWN_PATTERN = None


def _install_teardown_filter():
    import re

    from PyQt6.QtCore import qInstallMessageHandler

    global _TEARDOWN_PATTERN
    _TEARDOWN_PATTERN = re.compile(r"TypeError: Cannot (read property|call method) .* of null")

    def handler(_mode, _context, message):
        if _TEARDOWN and _TEARDOWN_PATTERN.search(message):
            return
        print(message, file=sys.stderr)

    qInstallMessageHandler(handler)


def _install_exception_hook(app_bridge) -> None:
    """Unhandled exceptions in slots / QML calls: log and toast instead of aborting.

    With the default sys.excepthook PyQt6 calls qFatal() for an exception that
    escapes a slot, which terminates the whole editor (a bad key in the YAML
    editor used to close it). The traceback goes to stderr and errors.log in
    the app data folder; the user sees an error toast.
    """
    import traceback
    from datetime import datetime

    from PyQt6.QtCore import QStandardPaths

    log_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    log_path = Path(log_dir) / "errors.log" if log_dir else None

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr)
        if log_path is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                if log_path.exists() and log_path.stat().st_size > 1_000_000:
                    log_path.replace(log_path.with_suffix(".old.log"))
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}\n")
            except OSError:
                pass
        if _TEARDOWN:
            return
        try:
            app_bridge.toast(f"{app_bridge.tr('main_window.dialogs.critical')}: "
                             f"{exc_type.__name__}: {exc}", "error")
        except Exception:
            pass

    sys.excepthook = hook


def create_bridges(settings=None, *, lazy: bool = False) -> tuple[AppBridge, dict[str, object]]:
    """创建壳桥接层与全部页面视图模型（供启动器和测试复用）。

    自动发现 viewmodels/ 下所有用 @register 注册的 VM。
    """
    import importlib
    import pkgutil

    from ui_huskar import viewmodels

    for module_info in pkgutil.iter_modules(viewmodels.__path__):
        if module_info.name != "base":
            importlib.import_module(f"ui_huskar.viewmodels.{module_info.name}")

    app_bridge = AppBridge(settings=settings)
    vms: dict[str, object] = {}
    keys = (app_bridge.pageKey,) if lazy else tuple(REGISTRY)
    for key in keys:
        cls, _qml = REGISTRY[key]
        vms[key] = cls(app_bridge)
        app_bridge.register_vm(key, vms[key])
    return app_bridge, vms


def _qml_name(key: str) -> str:
    return "vm" + "".join(part.title() for part in key.split("_"))


def main() -> int:
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QApplication(sys.argv)
    app.setApplicationName("Borderlands 4 Save Editor")
    app.setOrganizationName("SuperExboom")
    _install_teardown_filter()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(RUNTIME / "qml"))
    from ui_huskar.card_images import PROVIDER_ID, CardTintProvider
    # keep a Python reference: the engine does not own the provider wrapper
    engine.card_tint_provider = CardTintProvider()
    engine.addImageProvider(PROVIDER_ID, engine.card_tint_provider)
    warnings: list[str] = []
    engine.warnings.connect(lambda values: warnings.extend(
        f"{item.url().toString()}:{item.line()}: {item.description()}" for item in values))
    app_bridge, vms = create_bridges(lazy=True)
    _install_exception_hook(app_bridge)
    engine.rootContext().setContextProperty("appBridge", app_bridge)
    for key, vm in vms.items():
        engine.rootContext().setContextProperty(_qml_name(key), vm)

    # 页面 VM 按需创建：导航到新页面、以及跨页跳转（God Roll→武器编辑器、
    # YAML→各编辑器）往未打开过的页面灌数据时都由 AppBridge.ensure_vm 调用。
    # 必须在页面 QML 加载前暴露上下文属性，navigate 会在 pageChanged 之前创建。
    def create_page_vm(key: str):
        cls, _qml = REGISTRY[key]
        vm = cls(app_bridge)
        vms[key] = vm
        app_bridge.register_vm(key, vm)
        engine.rootContext().setContextProperty(_qml_name(key), vm)
        return vm

    app_bridge.set_vm_factory(create_page_vm)
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    qml_path = bundle_root / "ui_huskar" / "qml" / "Main.qml"
    if not qml_path.is_file():
        qml_path = Path(__file__).with_name("qml") / "Main.qml"
    report_value = os.environ.get("HUSKARUI_SMOKE_REPORT")
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    roots = engine.rootObjects()
    if not roots:
        if report_value:
            report_path = Path(report_value)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({
                "qt": QLibraryInfo.version().toString(),
                "rootObjects": 0,
                "warnings": warnings,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2
    if report_value:
        def write_report():
            report_path = Path(report_value)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            window = roots[0]
            screenshot = report_path.with_suffix(".png")
            window.grabWindow().save(str(screenshot), "PNG")
            report_path.write_text(json.dumps({
                "qt": QLibraryInfo.version().toString(),
                "rootObjects": len(roots),
                "width": window.width(),
                "height": window.height(),
                "warnings": warnings,
                "screenshot": str(screenshot),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        delay_ms = max(1, int(os.environ.get("HUSKARUI_SMOKE_REPORT_DELAY_MS", "1400")))
        QTimer.singleShot(delay_ms, write_report)
    autoquit = os.environ.get("HUSKARUI_AUTOQUIT_MS")
    if autoquit:
        QTimer.singleShot(max(1, int(autoquit)), app.quit)
    global _TEARDOWN
    try:
        return app.exec()
    finally:
        _TEARDOWN = True
        app_bridge.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
