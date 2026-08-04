#!/usr/bin/env python3
"""Verify that docs/API.md documents every route the application exposes.

Imports the FastAPI app and compares its route table against the method/path
pairs written in docs/API.md. A route that exists but is undocumented fails;
so does a documented route that no longer exists.

Run from the repository root::

    python3 scripts/check_api_docs.py

Exits 0 when the two agree, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "API.md"

# Routes FastAPI adds for itself, which are not part of the documented surface.
IGNORED_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROW = re.compile(r"^\|\s*`(GET|POST|PUT|PATCH|DELETE)`\s*\|\s*`([^`]+)`\s*\|")


def documented() -> set[tuple[str, str]]:
    if not DOC.exists():
        sys.exit(f"missing {DOC.relative_to(ROOT)}")
    found = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            found.add((m.group(1), m.group(2)))
    return found


def implemented() -> set[tuple[str, str]]:
    backend = ROOT / "backend"
    sys.path.insert(0, str(backend))
    cwd = Path.cwd()
    try:
        # main.py loads .env relative to the working directory.
        import os

        os.chdir(backend)
        from app.main import app
    except Exception as exc:  # pragma: no cover - environment guard
        sys.exit(f"could not import the application: {exc}")
    finally:
        os.chdir(cwd)

    # Walk the resolved schema rather than app.routes: this FastAPI version
    # keeps included routers as opaque _IncludedRouter objects, and the schema
    # is the same surface the generator and the live /docs page expose.
    found = set()
    for path, operations in app.openapi()["paths"].items():
        if path in IGNORED_PATHS:
            continue
        for method in operations:
            if method.upper() in METHODS:
                found.add((method.upper(), path))
    return found


def main() -> int:
    doc, impl = documented(), implemented()

    undocumented = sorted(impl - doc)
    stale = sorted(doc - impl)

    for method, path in undocumented:
        print(f"UNDOCUMENTED  {method:6} {path}")
    for method, path in stale:
        print(f"STALE         {method:6} {path}")

    if undocumented or stale:
        print(
            f"\ndocs/API.md is out of sync: "
            f"{len(undocumented)} undocumented, {len(stale)} stale.\n"
            f"Regenerate with scripts/gen_api_docs.py and splice the Routes section in."
        )
        return 1

    print(f"docs/API.md matches the application: {len(impl)} routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
