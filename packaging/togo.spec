# PyInstaller build for Togo: `pyinstaller packaging/togo.spec` (see packaging/build.ps1).
# One analysis, two programs in one folder: Togo.exe (windowed) and togo-mcp.exe (console, for MCP clients).
# Models aren't bundled; Togo downloads them on first run.
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas, binaries, hiddenimports = [], [], []
for package in ("onnx_asr", "winrt"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("togo") + collect_submodules("uvicorn") + collect_submodules("comtypes")
# The MCP SDK, without its optional command-line tool (which needs typer).
hiddenimports += collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli"))
datas += collect_data_files("mcp")
hiddenimports += ["pycaw", "keyboard", "win32job", "win32event", "multipart"]

a = Analysis(
    ["togo_entry.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "faster_whisper", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(debug=False, bootloader_ignore_signals=False, strip=False, upx=False, icon="togo.ico",
              version=None, exclude_binaries=True)
togo = EXE(pyz, a.scripts, [], name="Togo", console=False, **common)
togo_mcp = EXE(pyz, a.scripts, [], name="togo-mcp", console=True, **common)

coll = COLLECT(togo, togo_mcp, a.binaries, a.datas, strip=False, upx=False, name="Togo")
