#!/usr/bin/env python3
"""Idempotently add the Smart Plug source to an existing Energy Node collector.

The collector is *extended*, never replaced: this inserts one self-contained
function plus one call site and touches nothing else. Energy Node polling,
buffering, retries, deployment-aware discarding, connectivity tracking and
synchronisation are left byte-identical — the patch is refused outright if any
pre-existing line would change.

Running it twice is safe: the second run detects the integration and exits 0.

Usage:  integrate_collector.py /path/to/collector.py
"""
from __future__ import annotations

import ast
import re
import shutil
import sys

MARKER = "start_smart_plug_source"

BLOCK = '''
# --------------------------------------------------------------- smart plugs
SMART_PLUG_CONF = "/etc/energy-node/smart-plugs.conf"


def _smart_plug_settings():
    """Smart Plug settings: the standard config file, overridden by the environment.

    A file is used rather than the collector's own env file because the nodes
    do not pass configuration the same way — some use EnvironmentFile=, others
    inline Environment= lines. One path works everywhere and keeps the Energy
    Node configuration untouched.
    """
    settings = {}

    try:
        with open(SMART_PLUG_CONF, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                settings[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass

    for key in ("SMART_PLUGS_ENABLED", "NODE_ID", "CENTRAL_API_URL", "SMART_PLUG_BUFFER"):
        value = os.getenv(key)
        if value:
            settings[key] = value

    return settings


def start_smart_plug_source():
    """Start the Smart Plug accessory source alongside the Energy Node pipeline.

    Smart plugs are accessories of a deployment, not Energy Nodes: they answer
    which outlet consumes the most during a measurement campaign. The source
    owns its own daemon threads and its own SQLite buffer, deliberately
    separate from the Energy Node buffer, so Energy Node polling, buffering,
    retries, deployment awareness and synchronisation are untouched.

    Disabled unless SMART_PLUGS_ENABLED is truthy. Every failure is swallowed:
    an accessory must never be able to take down Energy Node collection.
    """
    settings = _smart_plug_settings()

    if settings.get("SMART_PLUGS_ENABLED", "0").strip().lower() not in ("1", "true", "yes", "on"):
        log.info("Smart Plug source disabled (SMART_PLUGS_ENABLED not set in %s).", SMART_PLUG_CONF)
        return None

    node_id = settings.get("NODE_ID")
    backend_url = settings.get("CENTRAL_API_URL")
    buffer_path = settings.get("SMART_PLUG_BUFFER", "/opt/energy-node/state/smart_plugs.db")

    if not node_id or not backend_url:
        log.error("Smart Plug source not started: NODE_ID / CENTRAL_API_URL missing.")
        return None

    try:
        from smart_plug_source import SmartPlugSource

        source = SmartPlugSource(
            node_id=node_id,
            backend_url=backend_url,
            buffer_path=buffer_path,
        )
        source.start()
        log.info("Smart Plug source started | node=%s buffer=%s", node_id, buffer_path)
        return source
    except Exception as exc:
        log.error("Smart Plug source failed to start; Energy Node unaffected: %s", exc)
        return None


'''


def fail(message):
    print(f"  [FAIL] {message}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        fail("usage: integrate_collector.py /path/to/collector.py")

    path = sys.argv[1]

    try:
        with open(path, encoding="utf-8") as handle:
            original = handle.read()
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")

    if MARKER in original:
        print("  [SKIP] already integrated")
        return 0

    # ------------------------------------------------------- compatibility
    for pattern, why in (
        (r"^import os$", "'import os'"),
        (r"^log\s*=", "a module-level 'log' logger"),
        (r"^def main\(\)", "a 'def main()' entry point"),
    ):
        if not re.search(pattern, original, re.MULTILINE):
            fail(f"incompatible collector: missing {why}")

    lines = original.splitlines(keepends=True)

    call_sites = [
        index for index, line in enumerate(lines)
        if "polling_loop(" in line and not line.lstrip().startswith("def ")
    ]
    if not call_sites:
        fail("incompatible collector: no polling_loop() call site found")

    # ------------------------------------------- insert the call inside main()
    call_line = call_sites[-1]
    insert_at = call_line
    indent = " " * (len(lines[call_line]) - len(lines[call_line].lstrip()))

    # When the polling loop is wrapped in try:, start the accessory before the
    # try: so its startup is not swallowed by the loop's exception handling.
    probe = call_line - 1
    while probe >= 0 and not lines[probe].strip():
        probe -= 1
    if probe >= 0 and lines[probe].strip() == "try:":
        insert_at = probe
        indent = " " * (len(lines[probe]) - len(lines[probe].lstrip()))

    lines.insert(insert_at, f"{indent}{MARKER}()\n")
    patched = "".join(lines)

    # ------------------------------------------------ insert the function def
    match = re.search(r"^def main\(\)", patched, re.MULTILINE)
    if not match:
        fail("could not locate 'def main()' after call insertion")

    patched = patched[: match.start()] + BLOCK.lstrip("\n") + patched[match.start():]

    # ------------------------------------------------------------- validate
    try:
        ast.parse(patched)
    except SyntaxError as exc:
        fail(f"patched collector does not parse: {exc}")

    if f"def {MARKER}()" not in patched:
        fail("patch verification failed: function missing")

    patched_lines = set(patched.splitlines())
    altered = [
        line for line in original.splitlines()
        if line.strip() and line not in patched_lines
    ]
    if altered:
        fail(f"patch would alter {len(altered)} existing line(s); refusing")

    temporary = f"{path}.integrating"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(patched)
    shutil.copystat(path, temporary)
    shutil.move(temporary, path)

    print("  [OK] integrated (1 config reader + 1 starter + 1 call, 0 existing lines altered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
