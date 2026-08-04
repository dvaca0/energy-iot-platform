#!/usr/bin/env python3
"""Verify every third-party import in the backend is declared in requirements.

Two real defects were found by this check the first time it was run, both of
which meant a clean install could not import the application at all:

  * `requirements.txt` named `google-generativeai`, the legacy SDK, while the
    code imports `from google import genai` — that is `google-genai`.
  * `playwright` and `psutil` were installed in the deployment virtualenv and
    absent from `requirements.txt`.

Neither was visible on a machine that already had the packages, which is
exactly why this runs in CI on a clean runner.

Run from the repository root::

    python3 scripts/check_requirements.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"

# Distribution name -> top-level import name, where the two differ.
ALIASES = {
    "scikit_learn": "sklearn",
    "beautifulsoup4": "bs4",
    "python_dotenv": "dotenv",
    "google_genai": "google",
    "types_requests": "requests",
}

# Packages pulled in transitively that modules may legitimately import.
TRANSITIVE = {"starlette", "anyio"}

# First-party.
LOCAL = {"app", "tests", "migrations"}


def declared() -> set[str]:
    names: set[str] = set()
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = ROOT / "backend" / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#")[0].strip()
            if not line or line.startswith("-r"):
                continue
            dist = line.split("==")[0].split(">=")[0].split("[")[0].strip()
            names.add(dist.replace("-", "_").lower())
    return {ALIASES.get(n, n) for n in names}


def imported() -> dict[str, str]:
    """Top-level import name -> an example file that imports it."""
    found: dict[str, str] = {}
    for py in sorted(APP.rglob("*.py")):
        # `._*` are macOS AppleDouble resource forks left by an SMB copy. They
        # are not Python and are git-ignored.
        if "__pycache__" in py.parts or py.name.startswith("._"):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            continue
        rel = str(py.relative_to(ROOT))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], rel)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.setdefault(node.module.split(".")[0], rel)
    return found


def main() -> int:
    available = declared() | TRANSITIVE | LOCAL | set(sys.stdlib_module_names)
    missing = {
        module: where
        for module, where in imported().items()
        if module.lower() not in {a.lower() for a in available}
    }

    in_actions = "GITHUB_ACTIONS" in os.environ
    for module, where in sorted(missing.items()):
        msg = (
            f"`{module}` is imported in {where} but is not declared in "
            f"backend/requirements.txt — a clean install cannot import the application"
        )
        print(f"::error file={where}::{msg}" if in_actions else f"MISSING  {msg}")

    if missing:
        print(f"\n{len(missing)} undeclared dependency/dependencies.")
        return 1
    print("Every third-party import in backend/app is declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
