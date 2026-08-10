"""The maintenance portal HTTP service.

Built on :mod:`http.server` from the standard library.  That is a deliberate
choice, not a shortcut: the portal must start on a node whose network is
broken, on a Pi 3B+ with limited memory, without a package index to install
from.  Zero third-party dependencies means zero ways for it to fail to start.

The portal holds no privilege of its own.  Every action is forwarded to the
supervisor over the control socket, which owns all mutation.  The portal
process only needs ``CAP_NET_BIND_SERVICE`` to occupy port 80 and membership
of the ``energy-net`` group to reach the socket.
"""

from __future__ import annotations

import ipaddress
import logging
import socketserver
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from ..ipc import ControlClient
from . import render

log = logging.getLogger("netd.portal")

MAX_BODY_BYTES = 16 * 1024


class PortalApplication:
    """Request handling logic, independent of the HTTP server plumbing."""

    def __init__(self, config: Config, client: Optional[ControlClient] = None) -> None:
        self._config = config
        self._client = client or ControlClient(config.paths.control_socket)
        self._trusted = self._parse_networks(config.portal.trusted_networks)

    @property
    def config(self) -> Config:
        return self._config

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_networks(entries: List[str]) -> List[ipaddress._BaseNetwork]:
        networks: List[ipaddress._BaseNetwork] = []
        for entry in entries:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                log.warning("ignoring malformed trusted network %r", entry)
        return networks

    def is_trusted(self, address: str) -> bool:
        """Whether a client address may perform mutating actions."""
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        # An IPv4-mapped IPv6 client (::ffff:192.168.66.5) must be judged on
        # its real address.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return any(ip in network for network in self._trusted)

    # ------------------------------------------------------------------
    def call(self, command: str, **args: Any) -> Dict[str, Any]:
        return self._client.call(command, **args)

    def _shell(self, title: str, body: str, active: str, flash: Optional[Tuple[str, str]]) -> str:
        status = self.call("status")
        node: Dict[str, Any] = {}
        if status.get("ok"):
            node = status.get("data", {}).get("node", {})
        return render.page(
            title,
            body,
            node_id=node.get("id", self._config.node.id),
            hostname=node.get("hostname", self._config.node.hostname),
            active=active,
            flash=flash,
        )

    # ------------------------------------------------------------------
    # pages
    # ------------------------------------------------------------------
    def page_status(self, flash: Optional[Tuple[str, str]]) -> str:
        status = self.call("status")
        if not status.get("ok"):
            return render.error_page(
                "Cannot reach the networking supervisor.", status.get("error", "")
            )
        collector = self.call("diagnostics.collector")
        body = render.status_body(
            status.get("data", {}),
            collector.get("data", {}) if collector.get("ok") else {"present": False},
        )
        return self._shell("Status", body, "/", flash)

    def page_networks(self, flash: Optional[Tuple[str, str]]) -> str:
        response = self.call("wifi.scan", force=False)
        networks = response.get("data", {}).get("networks", []) if response.get("ok") else []
        if not response.get("ok") and flash is None:
            flash = ("bad", response.get("error", "scan failed"))
        return self._shell("Networks", render.networks_body(networks), "/networks", flash)

    def page_saved(self, flash: Optional[Tuple[str, str]]) -> str:
        response = self.call("wifi.saved")
        saved = response.get("data", {}).get("saved", []) if response.get("ok") else []
        return self._shell("Saved networks", render.saved_body(saved), "/saved", flash)

    def page_diagnostics(self, flash: Optional[Tuple[str, str]]) -> str:
        response = self.call("diagnostics.full")
        if not response.get("ok"):
            return render.error_page("Diagnostics unavailable.", response.get("error", ""))
        body = render.diagnostics_body(response.get("data", {}))
        return self._shell("Diagnostics", body, "/diagnostics", flash)

    def page_logs(self, flash: Optional[Tuple[str, str]]) -> str:
        lines = self._config.portal.log_tail_lines
        network = self.call("logs.network", lines=lines)
        collector = self.call("logs.collector", lines=lines)
        body = render.logs_body(
            network.get("data", {}).get("entries", []) if network.get("ok") else [],
            collector.get("data", {}).get("entries", []) if collector.get("ok") else [],
        )
        return self._shell("Logs", body, "/logs", flash)

    def page_system(self, flash: Optional[Tuple[str, str]]) -> str:
        status = self.call("status")
        if not status.get("ok"):
            return render.error_page("System page unavailable.", status.get("error", ""))
        services = self.call("diagnostics.services")
        body = render.system_body(
            status.get("data", {}),
            services.get("data", {}).get("services", []) if services.get("ok") else [],
        )
        return self._shell("System", body, "/system", flash)

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def handle_action(self, name: str, form: Dict[str, str]) -> Tuple[str, str, str]:
        """Execute an action and return ``(redirect_path, kind, message)``."""
        handlers: Dict[str, Callable[[Dict[str, str]], Tuple[str, Dict[str, Any]]]] = {
            "scan": lambda f: ("/networks", self.call("wifi.scan", force=True)),
            "connect": lambda f: (
                "/",
                self.call(
                    "wifi.connect",
                    ssid=f.get("ssid", ""),
                    password=f.get("password") or None,
                    priority=f.get("priority") or None,
                ),
            ),
            "disconnect": lambda f: ("/saved", self.call("wifi.disconnect")),
            "forget": lambda f: ("/saved", self.call("wifi.forget", id=f.get("id", ""))),
            "priority": lambda f: (
                "/saved",
                self.call(
                    "wifi.priority", id=f.get("id", ""), priority=f.get("priority", "0")
                ),
            ),
            "ap-start": lambda f: ("/system", self.call("ap.start")),
            "ap-stop": lambda f: ("/system", self.call("ap.stop")),
            "restart-networking": lambda f: ("/system", self.call("net.restart")),
            "restart-service": lambda f: (
                "/system",
                self.call("service.restart", unit=f.get("unit", "")),
            ),
            "rerun-diagnostics": lambda f: ("/diagnostics", {"ok": True, "message": "Tests re-run"}),
            "reboot": lambda f: ("/system", self.call("system.reboot")),
            "shutdown": lambda f: ("/system", self.call("system.shutdown")),
            "factory-reset": lambda f: (
                "/system",
                self.call("factory.network_reset", confirm=f.get("confirm", "")),
            ),
        }

        handler = handlers.get(name)
        if handler is None:
            return "/", "bad", f"Unknown action '{name}'"

        redirect, response = handler(form)
        if response.get("ok"):
            return redirect, "ok", response.get("message") or "Done."
        return redirect, "bad", response.get("error", "Action failed.")


class _Handler(BaseHTTPRequestHandler):
    """HTTP plumbing: routing, form parsing, responses."""

    server_version = "EnergyNodePortal/1.0"
    protocol_version = "HTTP/1.1"

    app: PortalApplication  # injected by the server

    # Route table: path -> page method name.
    _PAGES = {
        "/": "page_status",
        "/networks": "page_networks",
        "/saved": "page_saved",
        "/diagnostics": "page_diagnostics",
        "/logs": "page_logs",
        "/system": "page_system",
    }

    # -- logging ------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("%s %s", self.address_string(), fmt % args)

    def log_error(self, fmt: str, *args: Any) -> None:
        log.warning("%s %s", self.address_string(), fmt % args)

    # -- helpers ------------------------------------------------------
    def _client_address(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def _send_html(self, body: str, status: int = HTTPStatus.OK) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
        import json

        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @staticmethod
    def _flash_from_query(query: Dict[str, List[str]]) -> Optional[Tuple[str, str]]:
        message = query.get("m", [""])[0]
        if not message:
            return None
        kind = query.get("k", ["ok"])[0]
        return ("ok" if kind == "ok" else "bad", message)

    # -- request handling ---------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/healthz":
            self._send_json({"ok": True, "service": "energy-node-portal"})
            return

        if path == "/api/status":
            self._send_json(self.app.call("status"))
            return

        if path == "/api/diagnostics":
            self._send_json(self.app.call("diagnostics.full"))
            return

        # Some phones probe these to decide whether to show a sign-in sheet.
        # Answering honestly (not hijacking) keeps the portal free of captive
        # portal behaviour while still letting the browser open normally.
        if path in ("/generate_204", "/gen_204"):
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        page_method = self._PAGES.get(path)
        if page_method is None:
            self._send_html(
                render.page(
                    "Not found",
                    "<section><h2>Not found</h2>"
                    '<p class="muted">No such page. <a href="/">Return to status</a>.</p>'
                    "</section>",
                    node_id=self.app.config.node.id,
                ),
                HTTPStatus.NOT_FOUND,
            )
            return

        try:
            body = getattr(self.app, page_method)(self._flash_from_query(query))
        except Exception as exc:  # noqa: BLE001 - never show a stack trace to a technician
            log.exception("rendering %s failed", path)
            body = render.error_page("The portal hit an internal error.", str(exc))
        self._send_html(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not path.startswith("/action/"):
            self._send_html(
                render.error_page("Unknown endpoint."), HTTPStatus.NOT_FOUND
            )
            return

        if not self.app.is_trusted(self._client_address()):
            log.warning(
                "rejected action %s from untrusted address %s", path, self._client_address()
            )
            self._send_html(
                render.error_page(
                    "This action is not permitted from your network.",
                    "Connect to the maintenance access point, the node's local network, "
                    "or use netdctl over SSH.",
                ),
                HTTPStatus.FORBIDDEN,
            )
            return

        form = self._read_form()
        action = path[len("/action/"):]
        try:
            redirect, kind, message = self.app.handle_action(action, form)
        except Exception as exc:  # noqa: BLE001
            log.exception("action %s failed", action)
            redirect, kind, message = "/", "bad", f"Internal error: {exc}"

        query = urllib.parse.urlencode({"k": kind, "m": message[:300]})
        self._redirect(f"{redirect}?{query}")

    def _read_form(self) -> Dict[str, str]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
        except OSError:
            return {}
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}


class PortalServer(ThreadingHTTPServer):
    """Threaded HTTP server bound to the portal application."""

    daemon_threads = True
    allow_reuse_address = True
    # A technician on a phone opens several connections; keep them short so a
    # stalled one cannot occupy the server.
    timeout = 30

    def __init__(self, config: Config, app: Optional[PortalApplication] = None) -> None:
        self.app = app or PortalApplication(config)
        handler = type("BoundHandler", (_Handler,), {"app": self.app})
        super().__init__((config.portal.bind, config.portal.port), handler)
