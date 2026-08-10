"""Content builders for the terminal console.

Pure formatting: each function turns a data structure from the supervisor into
urwid widgets.  No control-socket calls happen here, which keeps the screen
rendering testable and stops a slow network probe from freezing the UI while
it is drawing.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import urwid

PALETTE: Sequence[Tuple[str, ...]] = [
    ("body", "light gray", "black"),
    ("header", "white", "dark blue", "bold"),
    ("footer", "black", "light gray"),
    ("title", "white", "dark blue", "bold"),
    ("section", "light cyan", "black", "bold"),
    ("key", "light gray", "black"),
    ("value", "white", "black", "bold"),
    ("ok", "light green", "black", "bold"),
    ("warn", "yellow", "black", "bold"),
    ("bad", "light red", "black", "bold"),
    ("muted", "dark gray", "black"),
    ("menu", "light gray", "black"),
    ("menu_focus", "black", "light cyan", "standout"),
    ("button", "white", "dark gray"),
    ("button_focus", "black", "light cyan", "standout"),
    ("edit", "white", "dark gray"),
    ("edit_focus", "black", "light cyan"),
    ("banner_ok", "black", "dark green", "bold"),
    ("banner_warn", "black", "brown", "bold"),
    ("banner_bad", "white", "dark red", "bold"),
]


def text(markup: Any) -> urwid.Text:
    return urwid.Text(markup)


def blank() -> urwid.Text:
    return urwid.Text("")


def section(title: str) -> urwid.Text:
    """A section rule.

    Deliberately ASCII: the Linux virtual console's default font has no
    box-drawing glyphs, so U+2500 renders as mojibake on an attached HDMI
    display -- which is the one place this UI actually has to look right.
    """
    # Sized to fit the content pane on a bare 80x25 Linux console once the
    # 26-column menu is subtracted; wider rules wrap and look broken.
    return urwid.Text(("section", f"-- {title} " + "-" * max(4, 42 - len(title))))


def row(label: str, value: Any, style: str = "value") -> urwid.Columns:
    """A label/value line with a fixed-width label column."""
    return urwid.Columns(
        [
            (22, urwid.Text(("key", label))),
            urwid.Text((style, "" if value is None else str(value))),
        ],
        dividechars=1,
    )


def flag(label: str, ok: Optional[bool], ok_text: str = "OK", bad_text: str = "FAIL") -> urwid.Columns:
    style = "ok" if ok else "bad"
    return row(label, ok_text if ok else bad_text, style)


def duration(seconds: Optional[float]) -> str:
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        return "-"
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60}s"
    if total < 86400:
        return f"{total // 3600}h {(total % 3600) // 60}m"
    return f"{total // 86400}d {(total % 86400) // 3600}h"


def state_style(state: str, available: bool) -> str:
    if available:
        return "banner_ok"
    if state == "MAINTENANCE_AP":
        return "banner_warn"
    return "banner_bad"


# ----------------------------------------------------------------------
def status_view(status: Dict[str, Any], collector: Dict[str, Any]) -> List[urwid.Widget]:
    node = status.get("node", {})
    conn = status.get("connectivity") or {}
    ap = status.get("access_point", {})
    available = bool(status.get("network_available"))
    state = str(status.get("state", "?"))

    banner = urwid.AttrMap(
        urwid.Text(
            f"  {state}  —  network {'AVAILABLE' if available else 'UNAVAILABLE'}", align="left"
        ),
        state_style(state, available),
    )

    widgets: List[urwid.Widget] = [
        banner,
        blank(),
        urwid.Text(("muted", f"  {status.get('state_reason', '')}")),
        blank(),
        section("Node"),
        row("Node ID", node.get("id")),
        row("Hostname", node.get("hostname")),
        row("Model", node.get("model") or "-"),
        row("Time in state", duration(status.get("time_in_state"))),
        blank(),
        section("Networking"),
        row("Uplink", (conn.get("link") or "none").title()),
        row("Interface", conn.get("interface") or "-"),
        row("IP address", conn.get("ipv4") or "-"),
        row("SSID", status.get("ssid") or "-"),
        flag("Gateway", conn.get("gateway_ok")),
        # DNS/internet/backend run on a slower cadence; show "not checked"
        # rather than claiming a failure that was never measured.
        *(
            [
                flag("DNS", conn.get("dns_ok")),
                flag("Internet", conn.get("internet_ok")),
                flag("Backend", conn.get("backend_ok")),
            ]
            if conn.get("deep_measured", True)
            else [
                row("DNS", "not checked yet", "muted"),
                row("Internet", "not checked yet", "muted"),
                row("Backend", "not checked yet", "muted"),
            ]
        ),
        blank(),
        section("Maintenance access point"),
        row(
            "State",
            "ACTIVE" if ap.get("active") else "inactive",
            "warn" if ap.get("active") else "muted",
        ),
        row("SSID", ap.get("ssid")),
        row("Portal", ap.get("url")),
        row("Clients", ap.get("clients", 0)),
        blank(),
        section("Collector"),
    ]

    if collector.get("present"):
        widgets += [
            row("Buffered samples", collector.get("buffered")),
            row("Total samples", collector.get("total")),
            row("Last measurement", collector.get("last_measurement") or "-"),
            row("Last synchronisation", collector.get("last_sync") or "never"),
            flag(
                "Last sync result",
                collector.get("last_sync_ok"),
                "OK",
                "FAILED",
            )
            if collector.get("last_sync") is not None
            else row("Last sync result", "n/a", "muted"),
        ]
    else:
        widgets.append(row("Collector", collector.get("error", "not installed"), "muted"))

    return widgets


def networks_view(networks: List[Dict[str, Any]]) -> List[urwid.Widget]:
    widgets: List[urwid.Widget] = [section("Available networks"), blank()]
    if not networks:
        widgets.append(urwid.Text(("muted", "  No networks found. Press 's' to scan again.")))
        return widgets

    widgets.append(
        urwid.Columns(
            [
                (30, urwid.Text(("key", "SSID"))),
                (12, urwid.Text(("key", "SIGNAL"))),
                (12, urwid.Text(("key", "SECURITY"))),
                (9, urwid.Text(("key", "BAND"))),
                urwid.Text(("key", "SAVED")),
            ]
        )
    )
    for net in networks:
        widgets.append(
            urwid.Columns(
                [
                    (30, urwid.Text(("value", str(net.get("ssid", ""))[:29]))),
                    (12, urwid.Text(("value", f"{net.get('bars', '')} {net.get('signal', 0)}%"))),
                    (12, urwid.Text(("value", str(net.get("security", ""))))),
                    (9, urwid.Text(("value", str(net.get("band") or "-")))),
                    urwid.Text(("ok", "yes") if net.get("saved") else ("muted", "")),
                ]
            )
        )
    return widgets


def saved_view(saved: List[Dict[str, Any]]) -> List[urwid.Widget]:
    widgets: List[urwid.Widget] = [section("Saved networks"), blank()]
    if not saved:
        widgets.append(urwid.Text(("muted", "  No saved networks.")))
        return widgets
    widgets.append(
        urwid.Columns(
            [
                (34, urwid.Text(("key", "SSID"))),
                (12, urwid.Text(("key", "PRIORITY"))),
                (8, urwid.Text(("key", "AUTO"))),
                urwid.Text(("key", "STATE")),
            ]
        )
    )
    for net in saved:
        widgets.append(
            urwid.Columns(
                [
                    (34, urwid.Text(("value", str(net.get("ssid", ""))[:33]))),
                    (12, urwid.Text(("value", str(net.get("priority", 0))))),
                    (8, urwid.Text(("value", "yes" if net.get("autoconnect") else "no"))),
                    urwid.Text(("ok", "connected") if net.get("active") else ("muted", "-")),
                ]
            )
        )
    widgets += [
        blank(),
        urwid.Text(("muted", "  Highest priority network in range wins when roaming.")),
    ]
    return widgets


def diagnostics_view(report: Dict[str, Any]) -> List[urwid.Widget]:
    widgets: List[urwid.Widget] = [section("Connectivity tests"), blank()]
    for testcase in report.get("connectivity", []):
        latency = testcase.get("latency_ms")
        detail = str(testcase.get("detail", ""))[:44]
        widgets.append(
            urwid.Columns(
                [
                    (18, urwid.Text(("key", str(testcase.get("name", ""))))),
                    (8, urwid.Text(("ok", "PASS") if testcase.get("ok") else ("bad", "FAIL"))),
                    (10, urwid.Text(("muted", f"{latency} ms" if latency is not None else "-"))),
                    urwid.Text(("value", detail)),
                ]
            )
        )

    widgets += [blank(), section("Interfaces"), blank()]
    for iface in report.get("interfaces", []):
        widgets.append(
            urwid.Columns(
                [
                    (14, urwid.Text(("value", str(iface.get("device", ""))))),
                    (14, urwid.Text(("muted", str(iface.get("kind", ""))))),
                    (16, urwid.Text(("value", str(iface.get("state", ""))))),
                    urwid.Text(("value", str(iface.get("ipv4") or "-"))),
                ]
            )
        )

    health = report.get("health", {})
    disk = health.get("disk", {})
    memory = health.get("memory", {})
    widgets += [
        blank(),
        section("System health"),
        row("Uptime", duration(health.get("uptime_seconds"))),
        row("CPU", f"{health.get('cpu_percent')} %"),
        row(
            "Temperature",
            f"{health.get('temperature_c')} °C" if health.get("temperature_c") is not None else "-",
        ),
        row(
            "Memory",
            f"{memory.get('used_mb')} / {memory.get('total_mb')} MB "
            f"({memory.get('percent_used')}%)",
        ),
        row(
            "Disk",
            f"{disk.get('used_gb')} / {disk.get('total_gb')} GB ({disk.get('percent_used')}%)",
        ),
        blank(),
        section("Routes"),
        urwid.Text(("muted", str(report.get("routes", "")))),
    ]
    return widgets


def services_view(services: List[Dict[str, Any]]) -> List[urwid.Widget]:
    widgets: List[urwid.Widget] = [section("Services"), blank()]
    for service in services:
        running = service.get("running")
        present = service.get("present")
        if not present:
            style, label = "muted", "not installed"
        else:
            style, label = ("ok", "running") if running else ("bad", service.get("ActiveState", "stopped"))
        widgets.append(
            urwid.Columns(
                [
                    (38, urwid.Text(("value", str(service.get("unit", ""))))),
                    (14, urwid.Text((style, label))),
                    (12, urwid.Text(("muted", str(service.get("UnitFileState") or "-")))),
                    urwid.Text(("muted", f"restarts: {service.get('NRestarts', '0')}")),
                ]
            )
        )
    return widgets


def logs_view(title: str, entries: List[Dict[str, Any]]) -> List[urwid.Widget]:
    widgets: List[urwid.Widget] = [section(title), blank()]
    if not entries:
        widgets.append(urwid.Text(("muted", "  No entries.")))
        return widgets
    for entry in entries:
        priority = str(entry.get("priority", "6"))
        style = "bad" if priority in ("0", "1", "2", "3") else ("warn" if priority == "4" else "value")
        widgets.append(
            urwid.Columns(
                [
                    (20, urwid.Text(("muted", str(entry.get("time", ""))))),
                    urwid.Text((style, str(entry.get("message", ""))[:200])),
                ]
            )
        )
    return widgets
