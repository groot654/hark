"""Entry point for the packaged app. The same bundle has two programs: Togo.exe (no console) and
togo-mcp.exe (a console program, which MCP clients talk to over stdin/stdout)."""

import os
import sys

if os.path.basename(sys.executable).lower().startswith("togo-mcp") and "--mcp" not in sys.argv:
    sys.argv.insert(1, "--mcp")

from togo.__main__ import main  # noqa: E402

sys.exit(main())
