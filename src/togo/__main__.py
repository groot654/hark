"""Entry point: `togo` starts the engine and the notch; `togo --engine` runs the engine alone; `togo --mcp` runs an MCP server for the running Togo."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="togo")
    parser.add_argument("--engine", action="store_true", help="run only the local engine (no UI)")
    parser.add_argument("--mcp", action="store_true", help="run an MCP server (stdio) that uses the running Togo")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--stt", choices=["parakeet", "whisper"], default=None)
    parser.add_argument("--model", choices=["small", "medium", "large"], default=None,
                        help="built-in AI model size: small (0.8B), medium (2B) or large (4B)")
    parser.add_argument("--llm", choices=["builtin", "external", "off"], default=None,
                        help="AI model: built-in Qwen, an external server (Ollama or llm/url), or none")
    args = parser.parse_args()

    from togo.logging_setup import setup_logging

    setup_logging()
    log = logging.getLogger("togo")

    if args.mcp:  # stdout belongs to the MCP protocol; logs go to the file and stderr
        from togo.mcp_server import main as mcp_main

        return mcp_main()

    if not args.engine:
        from togo.single_instance import acquire, notify_running

        instance = acquire()  # noqa: F841  (held until this process exits)
        if instance is None:
            log.info("Togo is already running; asking it to show itself")
            notify_running()
            return 0

    from togo.engine.main import start_in_thread

    if args.engine:
        import time

        start_in_thread(args.stt or "parakeet", args.port, args.llm or "builtin", llm_size=args.model or "small")
        log.info("engine only; Ctrl+C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    from PySide6.QtWidgets import QApplication

    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    qt.setApplicationName("Togo")

    from togo.app.settings_store import Settings

    settings = Settings()
    engine, port = start_in_thread(
        args.stt or settings.get("stt/backend"), args.port, args.llm or settings.get("llm/mode"),
        settings.get("llm/url"), settings.get("llm/model"), settings.get("history/retention_days"),
        args.model or settings.get("llm/size"),
    )

    from togo.app.engine_client import EngineClient
    from togo.app.togo_app import TogoApp

    app = TogoApp(qt, EngineClient(port=port, token=engine.token))  # noqa: F841  (kept alive by Qt)
    return qt.exec()


if __name__ == "__main__":
    sys.exit(main())
