"""Keep PyQt6 QML collection focused on the modules used by HuskarUI.

The stock QtQml hook recursively collects every QML plugin shipped in the
PyQt6 wheel. That pulls WebEngine, Quick3D, PDF, and Multimedia trees into a
desktop editor that only imports QtQuick/Controls/Layouts/Effects.
"""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyqt6_library_info


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

_UNUSED = (
    "webengine", "quick3d", "qtpdf", "qtquick3d", "multimedia",
    "positioning", "sensors", "remoteobjects", "spatialaudio",
    "statemachine", "texttospeech", "serialport", "bluetooth",
    "nfc", "charts", "datavisualization", "qt6pdf", "qtpdf", "qpdf",
    "quicktest", "qt6test", "qttest",
)


def _keep(path: str) -> bool:
    normalized = str(path).replace("\\", "/").casefold()
    return not any(token in normalized for token in _UNUSED)


qml_binaries, qml_datas = pyqt6_library_info.collect_qtqml_files()
unfiltered_binaries = list(binaries)
binaries = [(src, dst) for src, dst in unfiltered_binaries if _keep(src) and _keep(dst)]
binaries += [(src, dst) for src, dst in qml_binaries if _keep(src) and _keep(dst)]
datas += [(src, dst) for src, dst in qml_datas if _keep(src) and _keep(dst)]
