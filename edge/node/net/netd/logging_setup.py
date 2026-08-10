"""Logging configuration.

Everything goes to journald via stderr under a stable ``SyslogIdentifier``
declared in each systemd unit, so ``journalctl -u energy-node-netd`` is the
single place to read networking history.  The portal and TUI read the same
journal back, so operators see exactly what the daemon recorded.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_CONFIGURED = False

# journald applies its own timestamps; a bare level/name prefix keeps lines
# readable both in the journal and when running the tools interactively.
_FORMAT = "%(levelname)s %(name)s: %(message)s"
_TTY_FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"


def configure(level: Optional[str] = None, force_tty_format: bool = False) -> None:
    """Configure root logging exactly once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    name = (level or os.environ.get("NETD_LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, name, logging.INFO)
    if not isinstance(numeric, int):
        numeric = logging.INFO

    use_tty = force_tty_format or sys.stderr.isatty()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(_TTY_FORMAT if use_tty else _FORMAT, datefmt="%H:%M:%S")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)

    # These are noisy and never actionable for an operator.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
