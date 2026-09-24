from __future__ import annotations

import os
from pathlib import Path


def configure_runtime() -> Path:
    """Make the vendored HuskarUI Qt6 plugin visible before importing PyQt6."""
    package_root = Path(__file__).resolve().parents[1]
    runtime_root = Path(os.environ.get("HUSKARUI_RUNTIME", package_root / "vendor" / "huskarui"))
    qt_root_value = os.environ.get("HUSKARUI_QT_ROOT")
    qt_bin = Path(qt_root_value) / "bin" if qt_root_value else None
    search_paths = [runtime_root / "bin"]
    if qt_bin and qt_bin.is_dir():
        search_paths.insert(0, qt_bin)
    for path in search_paths:
        if path.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(path))
    existing = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(str(path) for path in search_paths if path.is_dir()) + os.pathsep + existing
    return runtime_root
