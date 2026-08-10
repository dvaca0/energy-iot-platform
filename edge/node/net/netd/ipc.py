"""Control-plane IPC between the supervisor and its user interfaces.

The supervisor (running as root) is the only component permitted to mutate
network state.  The portal and the TUI are unprivileged clients that ask it to
act, over a Unix domain socket owned by the ``energy-net`` group.

Protocol: one JSON object per line, request and response.  Deliberately
boring -- it has to work when everything else on the node is broken.

    -> {"command": "wifi.connect", "args": {"ssid": "Lab", "password": "..."}}
    <- {"ok": true, "data": {...}}
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("netd.ipc")

MAX_MESSAGE_BYTES = 64 * 1024
DEFAULT_TIMEOUT = 90

Handler = Callable[[str, Dict[str, Any]], Dict[str, Any]]


class ProtocolError(RuntimeError):
    """Raised when a peer sends something unusable."""


def _encode(payload: Dict[str, Any]) -> bytes:
    return (json.dumps(payload, default=str) + "\n").encode("utf-8")


class ControlClient:
    """Client side of the control socket."""

    def __init__(self, path: Path, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._path = path
        self._timeout = timeout

    @property
    def path(self) -> Path:
        return self._path

    def available(self) -> bool:
        return self._path.exists()

    def call(self, command: str, **args: Any) -> Dict[str, Any]:
        """Send ``command`` and return the decoded response.

        Never raises for a network-level failure: a supervisor that is down is
        reported as a normal ``{"ok": False}`` result so the UIs can render it
        instead of crashing.
        """
        request = {"command": command, "args": args}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self._timeout)
                sock.connect(str(self._path))
                sock.sendall(_encode(request))
                sock.shutdown(socket.SHUT_WR)
                chunks = []
                total = 0
                while True:
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_MESSAGE_BYTES * 8:
                        break
            raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
            if not raw:
                return {"ok": False, "error": "empty response from netd"}
            return json.loads(raw.splitlines()[0])
        except FileNotFoundError:
            return {"ok": False, "error": "netd control socket not present"}
        except (ConnectionError, socket.timeout, OSError) as exc:
            return {"ok": False, "error": f"netd unreachable: {exc}"}
        except ValueError as exc:
            return {"ok": False, "error": f"malformed response from netd: {exc}"}


class _RequestHandler(socketserver.StreamRequestHandler):
    """Handles one control request."""

    timeout = DEFAULT_TIMEOUT
    server: "ControlServer"  # type: ignore[assignment]

    def handle(self) -> None:
        try:
            line = self.rfile.readline(MAX_MESSAGE_BYTES)
        except OSError:
            return
        if not line:
            return
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ProtocolError("request must be an object")
            command = str(request.get("command", "")).strip()
            args = request.get("args") or {}
            if not isinstance(args, dict):
                raise ProtocolError("args must be an object")
            if not command:
                raise ProtocolError("missing command")
        except (ValueError, ProtocolError) as exc:
            self._respond({"ok": False, "error": str(exc)})
            return

        try:
            response = self.server.dispatch(command, args)
        except Exception as exc:  # noqa: BLE001 - a UI must never kill netd
            log.exception("control command %s failed", command)
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._respond(response)

    def _respond(self, payload: Dict[str, Any]) -> None:
        try:
            self.wfile.write(_encode(payload))
            self.wfile.flush()
        except OSError:
            pass


class ControlServer(socketserver.ThreadingUnixStreamServer):
    """Server side of the control socket.

    The socket is created with mode 0660 and, when possible, group ownership
    of ``group``, so unprivileged UI processes can talk to it while ordinary
    users on the node cannot.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        path: Path,
        handler: Handler,
        group: Optional[str] = None,
        mode: int = 0o660,
    ) -> None:
        self._path = path
        self._handler = handler
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        super().__init__(str(path), _RequestHandler)
        self._apply_permissions(group, mode)

    def _apply_permissions(self, group: Optional[str], mode: int) -> None:
        try:
            os.chmod(self._path, mode)
        except OSError as exc:
            log.warning("could not chmod control socket: %s", exc)
        if not group:
            return
        try:
            import grp

            gid = grp.getgrnam(group).gr_gid
            os.chown(self._path, -1, gid)
        except (KeyError, OSError, ImportError) as exc:
            log.warning("could not set control socket group to %s: %s", group, exc)

    def dispatch(self, command: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._handler(command, args)

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="netd-control", daemon=True)
        thread.start()
        return thread

    def shutdown_and_close(self) -> None:
        try:
            self.shutdown()
        finally:
            self.server_close()
            try:
                self._path.unlink()
            except OSError:
                pass
