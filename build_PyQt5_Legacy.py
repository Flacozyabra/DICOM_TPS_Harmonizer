#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build script for the legacy-compatible standalone EXE (PyQt5 + Python 3.8)."""

import os
import sys

os.environ["FORCE_PYQT5"] = "1"

from build_PyQt6 import run_pyinstaller_build


def main() -> None:
    if sys.version_info[:2] > (3, 8):
        print(
            f"[WARNING] Building with Python {sys.version_info.major}.{sys.version_info.minor}: "
            "PyQt5 compatibility covers legacy Windows 10/8.1, while Windows 7 requires Python 3.8."
        )

    install_missing = "--install-deps" in sys.argv or bool(os.environ.get("CI"))
    try:
        run_pyinstaller_build(
            exe_name="DICOM_TPS_Harmonizer_Legacy",
            qt_backend="PyQt5",
            exclude_qt="PyQt6",
            runtime_dlls=("vcruntime140.dll",),
            extra_hidden_imports=(
                "PyQt5",
                "PyQt5.QtCore",
                "PyQt5.QtGui",
                "PyQt5.QtWidgets",
                "PyQt5.sip",
            ),
            install_missing=install_missing,
        )
    except Exception as exc:
        print(f"\n[FATAL ERROR] PyQt5 Legacy build failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

