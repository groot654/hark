"""Entry point: `hark` starts the engine and the notch; `hark --engine` runs the engine alone."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="hark")
    parser.add_argument("--engine", action="store_true", help="run only the local engine (no UI)")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--stt", choices=["parakeet", "whisper"], default=None)
    args = parser.parse_args()

    from hark.logging_setup import setup_logging

    setup_logging()
    log = logging.getLogger("hark")

    from hark.engine.main import start_in_thread

    if args.engine:
        import time

        start_in_thread(args.stt or "parakeet", args.port)
        log.info("engine only; Ctrl+C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    from PySide6.QtWidgets import QApplication

    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    qt.setApplicationName("Hark")

    from hark.app.settings_store import Settings

    backend = args.stt or Settings().get("stt/backend")
    engine, port = start_in_thread(backend, args.port)

    from hark.app.engine_client import EngineClient
    from hark.app.hark_app import HarkApp

    app = HarkApp(qt, EngineClient(port=port, token=engine.token))  # noqa: F841  (kept alive by Qt)
    return qt.exec()


if __name__ == "__main__":
    sys.exit(main())
