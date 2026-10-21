"""Native-library setup shared by everything that loads onnxruntime or CTranslate2."""

from __future__ import annotations

import os
import sys


def use_bundled_msvc_runtime() -> None:
    """onnxruntime and CTranslate2 need the 2015-2022 C++ runtime, but System32 can hold an
    older msvcp140.dll. PySide6 ships current copies, so let Windows find those first."""
    if sys.platform != "win32":
        return
    os.add_dll_directory(_pyside_dir())


MSVC_RUNTIME = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll",
                "concrt140.dll")


def copy_msvc_runtime(dest: str | os.PathLike) -> None:
    """App-local copy of the C++ runtime for a bundled .exe (e.g. llama-server), which
    Windows always looks for next to the executable before System32."""
    if sys.platform != "win32":
        return
    import shutil

    for name in MSVC_RUNTIME:
        if os.path.exists(os.path.join(dest, name)):
            continue
        source = next((os.path.join(d, name) for d in _runtime_dirs() if os.path.exists(os.path.join(d, name))), None)
        if source:
            shutil.copy2(source, os.path.join(dest, name))


def _runtime_dirs() -> list[str]:
    """Folders holding current copies of the C++ runtime: PySide6's when run from source; in the packaged app
    they're spread between the bundle's folder and its PySide6 folder."""
    import PySide6

    dirs = [os.path.dirname(PySide6.__file__), getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
    return [d for d in dirs if d]


def _pyside_dir() -> str:
    return _runtime_dirs()[0]
