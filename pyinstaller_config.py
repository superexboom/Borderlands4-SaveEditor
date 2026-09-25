#!/usr/bin/env python3
"""Build the HuskarUI Qt6 executable (``dist/BL4SaveEditor.exe``) from the maintained spec."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SPEC_PATH = BASE_DIR / "BL4SaveEditor.spec"


def create_spec_file() -> Path:
    """Return the maintained spec without rewriting it."""
    if not SPEC_PATH.is_file():
        raise FileNotFoundError(f"Canonical PyInstaller spec is missing: {SPEC_PATH}")
    print(f"Using canonical spec: {SPEC_PATH}")
    return SPEC_PATH


def build_executable() -> bool:
    """Run a clean PyInstaller build and return whether it succeeded."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed; install requirements.txt first.")
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
    print("=== PyInstaller build (BL4SaveEditor) ===")
    print("Install dependencies with: pip install -r requirements.txt")
    raise SystemExit(0 if build_executable() else 1)
