"""Entry point for the ``energy-node-netd`` service."""

from __future__ import annotations

import sys
from typing import List, Optional

from .config import load_config
from .logging_setup import configure
from .supervisor import Supervisor


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = None
    if "--config" in argv:
        index = argv.index("--config")
        if index + 1 < len(argv):
            config_path = argv[index + 1]

    configure()
    config = load_config(config_path)
    return Supervisor(config).run()


if __name__ == "__main__":
    raise SystemExit(main())
