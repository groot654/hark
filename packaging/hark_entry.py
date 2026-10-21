"""Entry point for the packaged app. The same bundle has two programs: Hark.exe (no console) and
hark-mcp.exe (a console program, which MCP clients talk to over stdin/stdout)."""

import os
import sys

if os.path.basename(sys.executable).lower().startswith("hark-mcp") and "--mcp" not in sys.argv:
    sys.argv.insert(1, "--mcp")

from hark.__main__ import main  # noqa: E402

sys.exit(main())
