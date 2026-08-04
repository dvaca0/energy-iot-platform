#!/usr/bin/env python3
"""Verify that every relative Markdown link and image resolves to a real file.

Relative links between documents are the ones that rot when a file moves, and
they are the ones a reader actually clicks. External URLs are deliberately not
checked here — a third-party site being down is not a defect in this
repository, and treating it as one makes the build lie.

Run from the repository root::

    python3 scripts/check_links.py

Exits 0 when everything resolves, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {"node_modules", "venv", ".venv", "dist", ".git", "__pycache__"}

# ![alt](target) and [text](target); the leading "!" is captured to tell images
# from links only for reporting.
LINK = re.compile(r"(!?)\[[^\]]*\]\(([^)]+)\)")

# Anything with a scheme, a protocol-relative URL, an anchor-only link, or a
# mailto: is out of scope for this check.
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.I)


def markdown_files() -> list[Path]:
    return sorted(
        p
        for p in ROOT.rglob("*.md")
        if not (SKIP_DIRS & set(p.relative_to(ROOT).parts))
    )


def slugify(heading: str) -> str:
    """GitHub's heading-to-anchor transformation, closely enough."""
    text = heading.strip().lower()
    # Punctuation is dropped, but underscores and existing hyphens survive —
    # `energy_source` stays `energy_source`, it does not become `energy-source`.
    text = re.sub(r"[^\w\s-]", "", text)
    # Each whitespace character becomes its own hyphen, so a heading like
    # "`energy_source` — why…" (two spaces once the dash is stripped) yields
    # "energy_source--why…", matching GitHub rather than collapsing the run.
    return re.sub(r"\s", "-", text).strip("-")


def anchors_in(path: Path) -> set[str]:
    anchors = set()
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return anchors
    for line in body.splitlines():
        if line.startswith("#"):
            anchors.add(slugify(line.lstrip("#")))
    # Explicit HTML anchors, e.g. <a id="x"> or <a name="x">
    anchors.update(re.findall(r'<a\s+(?:id|name)="([^"]+)"', body))
    return anchors


def main() -> int:
    problems: list[str] = []
    checked = 0
    anchor_cache: dict[Path, set[str]] = {}

    for md in markdown_files():
        try:
            body = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel_md = md.relative_to(ROOT)

        for bang, raw in LINK.findall(body):
            target = raw.strip().split(" ", 1)[0].strip("<>")
            if not target or EXTERNAL.match(target):
                continue

            checked += 1
            parsed = urlparse(target)
            file_part = unquote(parsed.path)
            resolved = (md.parent / file_part).resolve()

            if not resolved.exists():
                kind = "image" if bang else "link"
                problems.append(f"{rel_md}: broken {kind} -> {target}")
                continue

            # Anchor into a Markdown file: check the heading exists.
            if parsed.fragment and resolved.suffix == ".md":
                if resolved not in anchor_cache:
                    anchor_cache[resolved] = anchors_in(resolved)
                if parsed.fragment.lower() not in anchor_cache[resolved]:
                    problems.append(
                        f"{rel_md}: anchor not found -> {target} "
                        f"(#{parsed.fragment})"
                    )

    for p in problems:
        print(f"::error::{p}" if "GITHUB_ACTIONS" in __import__("os").environ else p)

    print(f"\n{checked} relative links checked across {len(markdown_files())} files.")
    if problems:
        print(f"{len(problems)} broken.")
        return 1
    print("All resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
