"""Entry point for the ``energy-node-console`` service.

Runs on tty1 as a getty replacement.  When the console exits (or crashes) the
unit restarts it, so the appliance screen is what a display always shows.
"""

from __future__ import annotations

import logging
import sys
from typing import List, Optional

from ..config import load_config
from ..logging_setup import configure

log = logging.getLogger("netd.tui")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = None
    if "--config" in argv:
        index = argv.index("--config")
        if index + 1 < len(argv):
            config_path = argv[index + 1]

    # The console owns the terminal; logging to stderr would corrupt the
    # display, so send it to the journal at warning level only.
    configure(level="WARNING")

    try:
        import urwid  # noqa: F401
    except ImportError:
        print(
            "The terminal console requires python3-urwid.\n"
            "Install it with: sudo apt-get install -y python3-urwid",
            file=sys.stderr,
        )
        return 1

    from .app import ConsoleApplication

    config = load_config(config_path)
    return ConsoleApplication(config).run()


if __name__ == "__main__":
    raise SystemExit(main())
