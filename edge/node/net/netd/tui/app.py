"""The appliance terminal console.

Runs on tty1 in place of a login prompt, so plugging in HDMI and a keyboard
shows an appliance, not kernel messages and a shell.  Built on urwid, which is
packaged in Debian (``python3-urwid``) and needs no compiler -- relevant on a
Pi 3B+ where pip-building a UI toolkit is not a reasonable install step.

The console is a *client*.  It holds no privilege and performs no network
mutation itself; every action is a control-socket call to the supervisor, so
the console and the web portal cannot disagree about the node's state.

Business logic lives in the supervisor, rendering lives in
:mod:`netd.tui.views`, and this module is only the shell: navigation, refresh
timing and input handling.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import urwid

from ..config import Config, load_config
from ..ipc import ControlClient
from . import views

log = logging.getLogger("netd.tui")

REFRESH_SECONDS = 5.0


class ConsoleApplication:
    """The appliance console."""

    #: Menu entries: (key, label, screen id)
    MENU: List[Tuple[str, str, str]] = [
        ("1", "Network Status", "status"),
        ("2", "Scan Networks", "networks"),
        ("3", "Saved Networks", "saved"),
        ("4", "Diagnostics", "diagnostics"),
        ("5", "Collector Status", "collector"),
        ("6", "Service Status", "services"),
        ("7", "Networking Logs", "logs_network"),
        ("8", "Collector Logs", "logs_collector"),
        ("9", "Restart Services", "restart"),
        ("0", "Power", "power"),
    ]

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or load_config()
        self._client = ControlClient(self._config.paths.control_socket, timeout=30)
        self._screen_id = "status"
        self._message: Optional[Tuple[str, str]] = None
        self._loop: Optional[urwid.MainLoop] = None
        self._alarm: Any = None

        self._body = urwid.SimpleFocusListWalker([])
        self._listbox = urwid.ListBox(self._body)

        self._header = urwid.AttrMap(urwid.Text(" Energy Node ", align="left"), "header")
        self._footer = urwid.AttrMap(urwid.Text(""), "footer")
        self._menu = self._build_menu()

        self._frame = urwid.Frame(
            body=urwid.Columns(
                [(26, urwid.AttrMap(self._menu, "menu")), urwid.AttrMap(self._listbox, "body")],
                dividechars=1,
            ),
            header=self._header,
            footer=self._footer,
        )

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_menu(self) -> urwid.ListBox:
        items: List[urwid.Widget] = [urwid.Text(("section", " MENU")), urwid.Divider()]
        for key, label, screen in self.MENU:
            button = urwid.Button(f"{key}  {label}")
            urwid.connect_signal(button, "click", self._on_menu_click, screen)
            items.append(urwid.AttrMap(button, "menu", focus_map="menu_focus"))
        items += [urwid.Divider(), urwid.Text(("muted", " q  Exit"))]
        return urwid.ListBox(urwid.SimpleFocusListWalker(items))

    def _on_menu_click(self, _button: urwid.Button, screen: str) -> None:
        self.show(screen)

    # ------------------------------------------------------------------
    # control socket
    # ------------------------------------------------------------------
    def _call(self, command: str, **args: Any) -> Dict[str, Any]:
        return self._client.call(command, **args)

    def _data(self, command: str, **args: Any) -> Dict[str, Any]:
        """Call and return the payload, recording any error as a message."""
        response = self._call(command, **args)
        if not response.get("ok"):
            self._message = ("bad", response.get("error", "command failed"))
            return {}
        return response.get("data", {}) or {}

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def show(self, screen_id: str) -> None:
        self._screen_id = screen_id
        self.refresh()

    def refresh(self, clear_stale_error: bool = False) -> None:
        """Rebuild the current screen from fresh data.

        ``clear_stale_error`` drops a previously shown error before
        re-rendering.  Without it, a transient failure at startup -- the
        console commonly comes up a second before the supervisor's control
        socket exists -- stays pinned in the footer forever, contradicting the
        live data on screen.
        """
        if clear_stale_error and self._message and self._message[0] == "bad":
            self._message = None
        try:
            widgets = self._render_screen(self._screen_id)
        except Exception as exc:  # noqa: BLE001 - a broken screen must not kill the console
            log.exception("rendering screen %s failed", self._screen_id)
            widgets = [
                views.section("Error"),
                urwid.Text(("bad", f"  Could not render this screen: {exc}")),
            ]

        self._body.clear()
        self._body.extend(widgets)
        # Replacing the contents leaves the walker's focus at its old index,
        # which makes the ListBox render scrolled past the top -- hiding the
        # status banner. Pin it back to the first row on every rebuild.
        if len(self._body):
            self._body.set_focus(0)
        self._update_chrome()

    def _render_screen(self, screen_id: str) -> List[urwid.Widget]:
        builders: Dict[str, Callable[[], List[urwid.Widget]]] = {
            "status": self._screen_status,
            "networks": self._screen_networks,
            "saved": self._screen_saved,
            "diagnostics": self._screen_diagnostics,
            "collector": self._screen_collector,
            "services": self._screen_services,
            "logs_network": lambda: views.logs_view(
                "Networking events",
                self._data("logs.network", lines=120).get("entries", []),
            ),
            "logs_collector": lambda: views.logs_view(
                "Collector events",
                self._data("logs.collector", lines=120).get("entries", []),
            ),
            "restart": self._screen_restart,
            "power": self._screen_power,
        }
        builder = builders.get(screen_id, self._screen_status)
        return builder()

    def _screen_status(self) -> List[urwid.Widget]:
        status = self._data("status")
        if not status:
            return [
                views.section("Networking service unavailable"),
                urwid.Text(("bad", "  Cannot reach energy-node-netd.")),
                urwid.Text(("muted", "  Check: systemctl status energy-node-netd")),
            ]
        collector = self._data("diagnostics.collector") or {"present": False}
        return views.status_view(status, collector)

    def _screen_networks(self) -> List[urwid.Widget]:
        networks = self._data("wifi.scan", force=False).get("networks", [])
        widgets = views.networks_view(networks)
        widgets += [
            urwid.Divider(),
            urwid.Text(("muted", "  Press 's' to rescan.")),
            urwid.Text(
                ("muted", "  To join a network, use the web portal or 'netdctl connect <ssid>'.")
            ),
        ]
        return widgets

    def _screen_saved(self) -> List[urwid.Widget]:
        return views.saved_view(self._data("wifi.saved").get("saved", []))

    def _screen_diagnostics(self) -> List[urwid.Widget]:
        return views.diagnostics_view(self._data("diagnostics.full"))

    def _screen_collector(self) -> List[urwid.Widget]:
        stats = self._data("diagnostics.collector")
        if not stats.get("present"):
            return [
                views.section("Collector"),
                urwid.Text(("muted", f"  {stats.get('error', 'not installed on this node')}")),
            ]
        return [
            views.section("Collector buffer"),
            views.blank(),
            views.row("Database", stats.get("database")),
            views.row("Buffered samples", stats.get("buffered")),
            views.row("Total samples", stats.get("total")),
            views.row("Last measurement", stats.get("last_measurement") or "-"),
            views.row("Last synchronisation", stats.get("last_sync") or "never"),
            views.row(
                "Last sync result",
                "OK" if stats.get("last_sync_ok") else "FAILED",
                "ok" if stats.get("last_sync_ok") else "bad",
            ),
            views.blank(),
            urwid.Text(
                (
                    "muted",
                    "  Buffering continues while offline; synchronisation resumes\n"
                    "  automatically once the network becomes available again.",
                )
            ),
        ]

    def _screen_services(self) -> List[urwid.Widget]:
        return views.services_view(self._data("diagnostics.services").get("services", []))

    def _screen_restart(self) -> List[urwid.Widget]:
        widgets: List[urwid.Widget] = [views.section("Restart services"), views.blank()]
        services = self._data("diagnostics.services").get("services", [])
        for service in services:
            unit = service.get("unit", "")
            if not service.get("present") or unit == "energy-node-netd.service":
                continue
            button = urwid.Button(f"Restart {unit}")
            urwid.connect_signal(button, "click", self._on_restart_service, unit)
            widgets.append(urwid.AttrMap(button, "button", focus_map="button_focus"))
        widgets.append(views.blank())

        networking = urwid.Button("Restart networking (NetworkManager)")
        urwid.connect_signal(networking, "click", self._on_restart_networking)
        widgets.append(urwid.AttrMap(networking, "button", focus_map="button_focus"))

        widgets += [
            views.blank(),
            urwid.Text(("muted", "  Restarting networking briefly drops connectivity.")),
        ]
        return widgets

    def _screen_power(self) -> List[urwid.Widget]:
        status = self._data("status")
        ap = status.get("access_point", {}) if status else {}

        widgets: List[urwid.Widget] = [views.section("Maintenance access point"), views.blank()]
        if ap.get("active"):
            button = urwid.Button("Disable maintenance AP")
            urwid.connect_signal(button, "click", self._on_ap, False)
        else:
            button = urwid.Button("Force maintenance AP  (drops current Wi-Fi)")
            urwid.connect_signal(button, "click", self._on_ap, True)
        widgets.append(urwid.AttrMap(button, "button", focus_map="button_focus"))
        widgets += [
            views.blank(),
            views.row("AP SSID", ap.get("ssid")),
            views.row("Portal", ap.get("url")),
            views.blank(),
            views.section("Power"),
            views.blank(),
        ]

        reboot = urwid.Button("Reboot node")
        urwid.connect_signal(reboot, "click", self._on_power, "reboot")
        widgets.append(urwid.AttrMap(reboot, "button", focus_map="button_focus"))

        shutdown = urwid.Button("Shutdown node")
        urwid.connect_signal(shutdown, "click", self._on_power, "shutdown")
        widgets.append(urwid.AttrMap(shutdown, "button", focus_map="button_focus"))

        widgets += [
            views.blank(),
            urwid.Text(("muted", "  Confirmation is required for power actions.")),
        ]
        return widgets

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _on_restart_service(self, _button: urwid.Button, unit: str) -> None:
        response = self._call("service.restart", unit=unit)
        self._flash(response, f"Restarted {unit}")

    def _on_restart_networking(self, _button: urwid.Button) -> None:
        response = self._call("net.restart")
        self._flash(response, "Restarting networking")

    def _on_ap(self, _button: urwid.Button, start: bool) -> None:
        if start:
            self._confirm(
                "Force the maintenance access point?\n"
                "The current Wi-Fi connection will be dropped.",
                lambda: self._flash(self._call("ap.start"), "Maintenance AP enabled"),
            )
        else:
            self._flash(self._call("ap.stop"), "Maintenance AP disabled")

    def _on_power(self, _button: urwid.Button, action: str) -> None:
        verb = "Reboot" if action == "reboot" else "Shut down"
        self._confirm(
            f"{verb} this node now?",
            lambda: self._flash(self._call(f"system.{action}"), f"{verb} requested"),
        )

    def _flash(self, response: Dict[str, Any], success: str) -> None:
        if response.get("ok"):
            self._message = ("ok", response.get("message") or success)
        else:
            self._message = ("bad", response.get("error", "action failed"))
        self.refresh()

    # ------------------------------------------------------------------
    # confirmation dialog
    # ------------------------------------------------------------------
    def _confirm(self, question: str, on_yes: Callable[[], None]) -> None:
        """Show a modal yes/no overlay."""
        if self._loop is None:
            on_yes()
            return

        yes = urwid.Button("Yes")
        no = urwid.Button("No")

        def dismiss() -> None:
            if self._loop is not None:
                self._loop.widget = self._frame

        urwid.connect_signal(yes, "click", lambda _b: (dismiss(), on_yes()))
        urwid.connect_signal(no, "click", lambda _b: dismiss())

        content = urwid.Pile(
            [
                urwid.Text(question),
                urwid.Divider(),
                urwid.Columns(
                    [
                        urwid.AttrMap(no, "button", focus_map="button_focus"),
                        urwid.AttrMap(yes, "button", focus_map="button_focus"),
                    ],
                    dividechars=2,
                ),
            ]
        )
        dialog = urwid.LineBox(urwid.Filler(urwid.Padding(content, left=2, right=2)), title="Confirm")
        self._loop.widget = urwid.Overlay(
            urwid.AttrMap(dialog, "body"),
            self._frame,
            align="center",
            width=("relative", 60),
            valign="middle",
            height=10,
        )

    # ------------------------------------------------------------------
    # chrome and input
    # ------------------------------------------------------------------
    def _update_chrome(self) -> None:
        status = self._call("status")
        if status.get("ok"):
            data = status.get("data", {})
            node = data.get("node", {})
            state = data.get("state", "?")
            available = data.get("network_available")
            marker = "●" if available else "○"
            self._header.original_widget = urwid.Text(
                f" Energy Node {node.get('id', '')} — {node.get('hostname', '')}"
                f"     {marker} {state}     {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self._header.set_attr_map({None: views.state_style(str(state), bool(available))})
        else:
            self._header.original_widget = urwid.Text(" Energy Node — supervisor unreachable")
            self._header.set_attr_map({None: "banner_bad"})

        if self._message:
            kind, text = self._message
            self._footer.original_widget = urwid.Text(f" {text}")
            self._footer.set_attr_map({None: "banner_ok" if kind == "ok" else "banner_bad"})
        else:
            self._footer.original_widget = urwid.Text(
                " 1-9 screens   TAB move   ENTER select   r refresh   s scan   q exit"
            )
            self._footer.set_attr_map({None: "footer"})

    def _handle_input(self, key: str) -> None:
        if isinstance(key, tuple):  # mouse event
            return
        self._message = None

        if key in ("q", "Q"):
            raise urwid.ExitMainLoop()
        if key in ("r", "R"):
            self.refresh()
            return
        if key in ("s", "S"):
            self._message = ("ok", "Scanning…")
            self._update_chrome()
            if self._loop is not None:
                self._loop.draw_screen()
            response = self._call("wifi.scan", force=True)
            self._screen_id = "networks"
            self._flash(response, "Scan complete")
            return

        for menu_key, _label, screen in self.MENU:
            if key == menu_key:
                self.show(screen)
                return

    def _on_timer(self, loop: urwid.MainLoop, _data: Any = None) -> None:
        # Only auto-refresh passive screens; refreshing under someone's cursor
        # while they are choosing a button is hostile.
        if self._screen_id in ("status", "services", "collector"):
            self.refresh(clear_stale_error=True)
        else:
            self._update_chrome()
        self._alarm = loop.set_alarm_in(REFRESH_SECONDS, self._on_timer)

    # ------------------------------------------------------------------
    def run(self) -> int:
        self.refresh()
        self._loop = urwid.MainLoop(
            self._frame,
            palette=list(views.PALETTE),
            unhandled_input=self._handle_input,
            handle_mouse=False,
        )
        self._alarm = self._loop.set_alarm_in(REFRESH_SECONDS, self._on_timer)
        try:
            self._loop.run()
        except KeyboardInterrupt:
            pass
        return 0
