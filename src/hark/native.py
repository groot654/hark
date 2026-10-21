"""Native-library setup shared by everything that loads onnxruntime or CTranslate2."""

from __future__ import annotations

import os
import sys


def use_bundled_msvc_runtime() -> None:
    """onnxruntime and CTranslate2 need the 2015-2022 C++ runtime, but System32 can hold an
    older msvcp140.dll. PySide6 ships current copies, so let Windows find those first."""
    if sys.platform != "win32":
        return
    import PySide6

    os.add_dll_directory(os.path.dirname(PySide6.__file__))
