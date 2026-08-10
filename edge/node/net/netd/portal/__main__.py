"""Entry point for the ``energy-node-portal`` service."""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import Any, List, Optional

from ..config import load_config
from ..logging_setup import configure
from .app import PortalServer

log = logging.getLogger("netd.portal")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = None
    if "--config" in argv:
        index = argv.index("--config")
        if index + 1 < len(argv):
            config_path = argv[index + 1]

    configure()
    config = load_config(config_path)

    if not config.portal.enabled:
        log.info("portal disabled in configuration; exiting cleanly")
        return 0

    try:
        server = PortalServer(config)
    except OSError as exc:
        log.error(
            "could not bind portal to %s:%d — %s",
            config.portal.bind,
            config.portal.port,
            exc,
        )
        return 1

    log.info(
        "maintenance portal listening on http://%s:%d (AP address http://%s)",
        config.portal.bind,
        config.portal.port,
        config.access_point.address,
    )

    def shutdown(signum: int, _frame: Any) -> None:
        log.info("received signal %d; shutting down portal", signum)
        # shutdown() blocks until serve_forever() returns, and the signal
        # handler runs *in* the serve_forever thread -- calling it directly
        # deadlocks until systemd loses patience and SIGKILLs us, leaving the
        # unit in 'failed'. Do it from another thread so serve_forever can
        # observe the request and unwind.
        threading.Thread(target=server.shutdown, name="portal-shutdown", daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, shutdown)
        except (ValueError, OSError):
            pass

    try:
        server.serve_forever(poll_interval=1.0)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
