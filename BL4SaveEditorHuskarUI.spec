# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.datastruct import TOC

ROOT = Path(SPECPATH).resolve()
VENDOR = ROOT / "vendor" / "huskarui"


def data_tree(relative: str):
    base = ROOT / relative
    if not base.exists():
        return []
    return [
        (str(path), str(path.relative_to(ROOT).parent).replace("\\", "/"))
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    ]


data = []
for directory in (
    "assets", "class_mods", "enhancement", "Firmware", "grenade", "heavy",
    "i18n", "item", "loadout", "loadouts", "repkit", "shield", "weapon_edit",
    "core/data", "ui_huskar/qml", "vendor/huskarui/qml",
):
    data.extend(data_tree(directory))

binaries = [
    (str(VENDOR / "bin" / "HuskarUIBasic.dll"), "vendor/huskarui/bin"),
    (str(VENDOR / "bin" / "HuskarUIImpl.dll"), "vendor/huskarui/bin"),
]

hidden = [
    "ui_huskar", "ui_huskar.__main__", "ui_huskar.runtime",
    "ui_huskar.viewmodels",
    "main_window", "core", "tabs", "live", "bl4_decoder_py",
]
for package in ("core", "tabs", "live", "bl4_decoder_py"):
    hidden.extend(collect_submodules(package))
hidden.extend(collect_submodules("ui_huskar.viewmodels"))

analysis = Analysis(
    [str(ROOT / "ui_huskar" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=data,
    hookspath=[str(ROOT / "tools" / "pyinstaller_hooks")],
    hiddenimports=hidden,
    excludes=[
        "PySide6", "PySide2", "PyQt5",
        # Not imported by HuskarUI. PyInstaller's Qt hook otherwise pulls
        # WebEngine/Quick3D/PDF/Multimedia stacks into the one-file archive.
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
        "PyQt6.QtQuick3D", "PyQt6.QtQuick3DAssetImport", "PyQt6.QtQuick3DHelpers",
        "PyQt6.QtQuick3DInput", "PyQt6.QtQuick3DLogic", "PyQt6.QtQuick3DParticles",
        "PyQt6.QtQuick3DPhysics", "PyQt6.QtQuick3DRender", "PyQt6.QtQuick3DUtils",
        "PyQt6.QtPdf", "PyQt6.QtPdfWidgets", "PyQt6.QtMultimedia",
        # Development-only transitive hooks from pandas/setuptools.
        "pytest", "_pytest", "openpyxl", "PIL", "matplotlib", "scipy", "numba", "pyarrow",
    ],
    noarchive=False,
)

# These modules are not imported by the source/QML tree. Some Qt hooks can
# still discover their DLLs through the wheel's broad QML dependency graph, so
# remove them at the final TOC boundary as a second, deterministic size gate.
_UNUSED_QT_BINARIES = ("qt6pdf", "qpdf.dll", "qt6test", "quicktest")
analysis.binaries = TOC([
    entry for entry in analysis.binaries
    if not any(marker in str(entry[0]).replace("\\", "/").casefold()
               for marker in _UNUSED_QT_BINARIES)
])
pyz = PYZ(analysis.pure, analysis.zipped_data)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    # Keep the historical executable name, but make it resolve to the
    # canonical HuskarUI entry point instead of an old QWidget build.
    name="BL4SaveEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "BL4.ico"),
)
