#!/usr/bin/env python3
"""Build the single, canonical HuskarUI Qt6 executable.

This compatibility command is kept because older instructions and scripts
call ``python pyinstaller_config.py``. It deliberately does not generate a
second spec from ``main_window.py``: that module is an internal backend
compatibility layer, not a user-facing application.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SPEC_PATH = BASE_DIR / "BL4SaveEditorHuskarUI.spec"


def create_spec_file() -> Path:
    """Return the maintained HuskarUI spec without rewriting it."""
    if not SPEC_PATH.is_file():
        raise FileNotFoundError(f"Canonical PyInstaller spec is missing: {SPEC_PATH}")
    print(f"Using canonical spec: {SPEC_PATH}")
    return SPEC_PATH


def build_executable() -> bool:
    """Run a clean PyInstaller build and return whether it succeeded."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed; install requirements-huskarui.txt first.")
        return False

    spec_path = create_spec_file()
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_path)],
        cwd=str(BASE_DIR),
        text=True,
    )
    if result.returncode == 0:
        print("Build successful: dist/BL4SaveEditor.exe")
        return True
    print(f"Build failed with exit code {result.returncode}")
    return False


if __name__ == "__main__":
    print("=== PyInstaller Configuration (HuskarUI Qt6) ===")
    print("Install dependencies with: pip install -r requirements-huskarui.txt")
    raise SystemExit(0 if build_executable() else 1)
