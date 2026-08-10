"""HTML rendering for the maintenance portal.

Plain server-rendered HTML with a small inline stylesheet and about thirty
lines of vanilla JavaScript for live status refresh.  No framework, no build
step, no external asset: the portal has to work when the node has no internet
at all, on whatever browser a technician happens to have on their phone.

Presentation only -- every value arrives already computed from the supervisor.
"""

from __future__ import annotations

import html
import time
from typing import Any, Dict, Iterable, List, Optional

_STYLE = """
:root {
  --bg: #0f1419; --panel: #182028; --panel-2: #1e2831; --line: #2b3742;
  --text: #e6edf3; --muted: #8b98a5; --accent: #4a9eff;
  --ok: #3fb950; --warn: #d29922; --bad: #f85149;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f4f6f8; --panel: #ffffff; --panel-2: #f0f3f6; --line: #d8dee4;
    --text: #1c2128; --muted: #61707d; --accent: #0969da;
    --ok: #1a7f37; --warn: #9a6700; --bad: #cf222e;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  padding-bottom: 3rem;
}
header {
  background: var(--panel); border-bottom: 1px solid var(--line);
  padding: 1rem 1.25rem; position: sticky; top: 0; z-index: 10;
}
header h1 { margin: 0; font-size: 1.15rem; letter-spacing: .01em; }
header .sub { color: var(--muted); font-size: .85rem; margin-top: .15rem; }
main { max-width: 900px; margin: 0 auto; padding: 1rem; }
nav { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: 1rem; }
nav a {
  color: var(--text); text-decoration: none; padding: .45rem .85rem;
  border: 1px solid var(--line); border-radius: 6px; background: var(--panel);
  font-size: .9rem;
}
nav a.active { background: var(--accent); border-color: var(--accent); color: #fff; }
section {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; padding: 1rem; margin-bottom: 1rem;
}
section h2 {
  margin: 0 0 .75rem; font-size: .8rem; text-transform: uppercase;
  letter-spacing: .08em; color: var(--muted); font-weight: 600;
}
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .6rem; }
.kv { background: var(--panel-2); border-radius: 6px; padding: .6rem .75rem; }
.kv .k { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; }
.kv .v { font-size: 1rem; margin-top: .15rem; word-break: break-word; }
.badge {
  display: inline-block; padding: .15rem .55rem; border-radius: 999px;
  font-size: .75rem; font-weight: 600;
}
.badge.ok { background: rgba(63,185,80,.18); color: var(--ok); }
.badge.warn { background: rgba(210,153,34,.18); color: var(--warn); }
.badge.bad { background: rgba(248,81,73,.18); color: var(--bad); }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { text-align: left; padding: .5rem .4rem; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; }
tr:last-child td { border-bottom: none; }
.actions { display: flex; flex-wrap: wrap; gap: .5rem; }
button, .btn {
  font: inherit; font-size: .9rem; padding: .5rem .9rem; border-radius: 6px;
  border: 1px solid var(--line); background: var(--panel-2); color: var(--text);
  cursor: pointer;
}
button:hover, .btn:hover { border-color: var(--accent); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.danger { color: var(--bad); border-color: rgba(248,81,73,.4); }
input, select {
  font: inherit; padding: .5rem .6rem; border-radius: 6px;
  border: 1px solid var(--line); background: var(--bg); color: var(--text);
  width: 100%; max-width: 100%;
}
form.inline { display: flex; flex-wrap: wrap; gap: .5rem; align-items: end; }
form.inline .field { flex: 1 1 190px; }
label { display: block; font-size: .75rem; color: var(--muted); margin-bottom: .25rem; }
pre {
  background: var(--panel-2); padding: .75rem; border-radius: 6px;
  overflow-x: auto; font-size: .8rem; margin: 0; line-height: 1.45;
}
.log { max-height: 26rem; overflow-y: auto; }
.log div { font-family: ui-monospace, monospace; font-size: .78rem; padding: .1rem 0; }
.log .t { color: var(--muted); }
.log .p3 { color: var(--bad); }
.log .p4 { color: var(--warn); }
.flash {
  padding: .7rem .9rem; border-radius: 6px; margin-bottom: 1rem; font-size: .9rem;
  border: 1px solid;
}
.flash.ok { background: rgba(63,185,80,.12); border-color: rgba(63,185,80,.4); }
.flash.bad { background: rgba(248,81,73,.12); border-color: rgba(248,81,73,.4); }
.muted { color: var(--muted); font-size: .85rem; }
.bars { font-family: ui-monospace, monospace; letter-spacing: -1px; }
@media (max-width: 560px) {
  main { padding: .6rem; }
  .actions button, .actions .btn { flex: 1 1 45%; }
}
"""

_SCRIPT = """
(function () {
  var el = document.getElementById('live-state');
  if (!el) return;
  function tick() {
    fetch('/api/status', {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) return;
        var s = d.data || {};
        el.textContent = s.state || '?';
        el.className = 'badge ' + (s.network_available ? 'ok'
          : (s.state === 'MAINTENANCE_AP' ? 'warn' : 'bad'));
        var r = document.getElementById('live-reason');
        if (r) r.textContent = s.state_reason || '';
      })
      .catch(function () {});
  }
  setInterval(tick, 5000);
})();
"""

_NAV = [
    ("/", "Status"),
    ("/networks", "Networks"),
    ("/saved", "Saved"),
    ("/diagnostics", "Diagnostics"),
    ("/logs", "Logs"),
    ("/system", "System"),
]


def esc(value: Any) -> str:
    """HTML-escape any value."""
    return html.escape("" if value is None else str(value), quote=True)


def badge(ok: Optional[bool], ok_text: str = "OK", bad_text: str = "FAIL") -> str:
    kind = "ok" if ok else "bad"
    text = ok_text if ok else bad_text
    return f'<span class="badge {kind}">{esc(text)}</span>'


def unknown_badge(text: str = "not checked") -> str:
    """For a probe that has not run yet -- distinct from one that failed."""
    return f'<span class="badge warn">{esc(text)}</span>'


def kv(key: str, value: Any) -> str:
    return f'<div class="kv"><div class="k">{esc(key)}</div><div class="v">{value}</div></div>'


def duration(seconds: Optional[float]) -> str:
    """Human-readable duration."""
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


def page(
    title: str,
    body: str,
    *,
    node_id: str = "",
    hostname: str = "",
    active: str = "/",
    flash: Optional[tuple[str, str]] = None,
) -> str:
    """Wrap ``body`` in the portal shell."""
    nav = "".join(
        f'<a href="{esc(href)}" class="{"active" if href == active else ""}">{esc(label)}</a>'
        for href, label in _NAV
    )
    flash_html = ""
    if flash:
        kind, message = flash
        flash_html = f'<div class="flash {esc(kind)}">{esc(message)}</div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(node_id or "Energy Node")} — {esc(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<header>
  <h1>Energy Node {esc(node_id)} — Maintenance</h1>
  <div class="sub">{esc(hostname)} · {esc(time.strftime("%Y-%m-%d %H:%M:%S"))}</div>
</header>
<main>
  <nav>{nav}</nav>
  {flash_html}
  {body}
</main>
<script>{_SCRIPT}</script>
</body>
</html>"""


def error_page(message: str, detail: str = "") -> str:
    """Shown when the supervisor cannot be reached."""
    body = f"""
<section>
  <h2>Networking service unavailable</h2>
  <p>{esc(message)}</p>
  {f'<pre>{esc(detail)}</pre>' if detail else ''}
  <p class="muted">
    The portal is running but cannot reach <code>energy-node-netd</code>.
    Over SSH, check it with
    <code>systemctl status energy-node-netd</code>.
  </p>
</section>"""
    return page("Unavailable", body, active="/")


# ----------------------------------------------------------------------
# page bodies
# ----------------------------------------------------------------------
def status_body(status: Dict[str, Any], collector: Dict[str, Any]) -> str:
    node = status.get("node", {})
    conn = status.get("connectivity") or {}
    ap = status.get("access_point", {})
    available = bool(status.get("network_available"))
    state = status.get("state", "?")

    state_class = "ok" if available else ("warn" if state == "MAINTENANCE_AP" else "bad")

    overview = "".join(
        [
            kv("Node", esc(node.get("id"))),
            kv("Hostname", esc(node.get("hostname"))),
            kv(
                "State",
                f'<span class="badge {state_class}" id="live-state">{esc(state)}</span>',
            ),
            kv("Current IP", esc(conn.get("ipv4") or "-")),
            kv("SSID", esc(status.get("ssid") or "-")),
            kv("Uplink", esc((conn.get("link") or "none").title())),
            kv("Time in state", duration(status.get("time_in_state"))),
            kv("Model", esc(node.get("model") or "-")),
        ]
    )

    # DNS/internet/backend run on a slower cadence than the link check; an
    # unmeasured probe must never be rendered as a failed one.
    measured = conn.get("deep_measured", True)
    deep_badge = badge if measured else (lambda _v: unknown_badge())

    checks = "".join(
        [
            kv("Gateway", badge(conn.get("gateway_ok"))),
            kv("DNS", deep_badge(conn.get("dns_ok"))),
            kv("Internet", deep_badge(conn.get("internet_ok"))),
            kv("Backend", deep_badge(conn.get("backend_ok"))),
            kv(
                "Network",
                badge(available, "AVAILABLE", "UNAVAILABLE"),
            ),
            kv(
                "Maintenance AP",
                f'<span class="badge {"warn" if ap.get("active") else "ok"}">'
                f'{"ACTIVE" if ap.get("active") else "inactive"}</span>',
            ),
        ]
    )

    if collector.get("present"):
        collector_cells = "".join(
            [
                kv("Buffered samples", esc(collector.get("buffered"))),
                kv("Total samples", esc(collector.get("total"))),
                kv(
                    "Last synchronisation",
                    esc(collector.get("last_sync") or "never"),
                ),
                kv(
                    "Last sync result",
                    badge(collector.get("last_sync_ok"), "OK", "FAILED")
                    if collector.get("last_sync") is not None
                    else '<span class="muted">n/a</span>',
                ),
                kv("Last measurement", esc(collector.get("last_measurement") or "-")),
            ]
        )
    else:
        collector_cells = kv(
            "Collector",
            f'<span class="muted">{esc(collector.get("error", "not installed"))}</span>',
        )

    ap_note = ""
    if ap.get("active"):
        ap_note = (
            f'<p class="muted">Serving SSID <strong>{esc(ap.get("ssid"))}</strong> '
            f'at <strong>{esc(ap.get("url"))}</strong> — '
            f'{esc(ap.get("clients", 0))} client(s) connected.</p>'
        )

    return f"""
<section>
  <h2>Node</h2>
  <div class="grid">{overview}</div>
  <p class="muted" id="live-reason" style="margin:.75rem 0 0">{esc(status.get("state_reason"))}</p>
</section>

<section>
  <h2>Connectivity</h2>
  <div class="grid">{checks}</div>
  {ap_note}
</section>

<section>
  <h2>Collector</h2>
  <div class="grid">{collector_cells}</div>
</section>

<section>
  <h2>Quick actions</h2>
  <div class="actions">
    <a class="btn" href="/networks">Scan networks</a>
    <a class="btn" href="/saved">Saved networks</a>
    <a class="btn" href="/diagnostics">Diagnostics</a>
    <a class="btn" href="/system">System &amp; power</a>
  </div>
</section>"""


def networks_body(networks: List[Dict[str, Any]]) -> str:
    if networks:
        rows = "".join(
            f"""<tr>
  <td><strong>{esc(n.get("ssid"))}</strong>{' <span class="badge ok">saved</span>' if n.get("saved") else ''}</td>
  <td class="bars">{esc(n.get("bars"))} {esc(n.get("signal"))}%</td>
  <td>{esc(n.get("security"))}</td>
  <td>{esc(n.get("band") or "-")}</td>
  <td>
    <form method="post" action="/action/connect" style="display:flex;gap:.3rem">
      <input type="hidden" name="ssid" value="{esc(n.get("ssid"))}">
      <input type="password" name="password" placeholder="passphrase"
             autocomplete="off" style="min-width:8rem">
      <button class="primary" type="submit">Connect</button>
    </form>
  </td>
</tr>"""
            for n in networks
        )
        table = f"""<table>
<thead><tr><th>SSID</th><th>Signal</th><th>Security</th><th>Band</th><th>Action</th></tr></thead>
<tbody>{rows}</tbody></table>"""
    else:
        table = '<p class="muted">No networks found. Try scanning again.</p>'

    return f"""
<section>
  <h2>Available networks</h2>
  <div class="actions" style="margin-bottom:.75rem">
    <form method="post" action="/action/scan"><button class="primary">Scan networks</button></form>
  </div>
  {table}
</section>

<section>
  <h2>Join a hidden or out-of-range network</h2>
  <form class="inline" method="post" action="/action/connect">
    <div class="field"><label>SSID</label><input name="ssid" required autocomplete="off"></div>
    <div class="field"><label>Passphrase</label>
      <input name="password" type="password" autocomplete="off"
             placeholder="leave empty for an open network"></div>
    <div class="field" style="flex:0 0 7rem"><label>Priority</label>
      <input name="priority" type="number" placeholder="auto"></div>
    <div class="field" style="flex:0 0 auto">
      <label>&nbsp;</label><button class="primary" type="submit">Connect</button></div>
  </form>
  <p class="muted" style="margin-bottom:0">
    Higher priority wins when several saved networks are in range.
  </p>
</section>"""


def saved_body(saved: List[Dict[str, Any]]) -> str:
    if not saved:
        return """
<section><h2>Saved networks</h2>
<p class="muted">No saved networks. Add one from the Networks page.</p></section>"""

    rows = "".join(
        f"""<tr>
  <td><strong>{esc(n.get("ssid"))}</strong>
      {' <span class="badge ok">connected</span>' if n.get("active") else ''}</td>
  <td>{esc(n.get("priority"))}</td>
  <td>{"yes" if n.get("autoconnect") else "no"}</td>
  <td>
    <form method="post" action="/action/priority" style="display:flex;gap:.3rem">
      <input type="hidden" name="id" value="{esc(n.get("uuid"))}">
      <input type="number" name="priority" value="{esc(n.get("priority"))}" style="width:5.5rem">
      <button type="submit">Set priority</button>
    </form>
  </td>
  <td>
    <form method="post" action="/action/forget"
          onsubmit="return confirm('Forget {esc(n.get("ssid"))}?')">
      <input type="hidden" name="id" value="{esc(n.get("uuid"))}">
      <button class="danger" type="submit">Forget</button>
    </form>
  </td>
</tr>"""
        for n in saved
    )

    return f"""
<section>
  <h2>Saved networks</h2>
  <table>
    <thead><tr><th>SSID</th><th>Priority</th><th>Auto</th><th>Roaming order</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="muted">
    The node roams automatically between these networks. Highest priority in range wins.
  </p>
</section>

<section>
  <h2>Connection control</h2>
  <div class="actions">
    <form method="post" action="/action/disconnect"><button>Disconnect Wi-Fi</button></form>
    <form method="post" action="/action/restart-networking">
      <button class="danger">Restart networking</button></form>
  </div>
</section>"""


def diagnostics_body(report: Dict[str, Any]) -> str:
    tests = report.get("connectivity", [])
    test_rows = "".join(
        f"<tr><td>{esc(t.get('name'))}</td><td>{badge(t.get('ok'), 'PASS', 'FAIL')}</td>"
        f"<td>{esc(t.get('detail'))}</td>"
        f"<td>{esc(t.get('latency_ms')) if t.get('latency_ms') is not None else '-'} ms</td></tr>"
        for t in tests
    )

    iface_rows = "".join(
        f"<tr><td>{esc(i.get('device'))}</td><td>{esc(i.get('kind'))}</td>"
        f"<td>{esc(i.get('state'))}</td><td>{esc(i.get('connection') or '-')}</td>"
        f"<td>{esc(i.get('ipv4') or '-')}</td><td>{esc(i.get('gateway') or '-')}</td></tr>"
        for i in report.get("interfaces", [])
    )

    health = report.get("health", {})
    disk = health.get("disk", {})
    memory = health.get("memory", {})
    health_cells = "".join(
        [
            kv("Uptime", duration(health.get("uptime_seconds"))),
            kv("CPU", f"{esc(health.get('cpu_percent'))} %"),
            kv(
                "Temperature",
                f"{esc(health.get('temperature_c'))} °C"
                if health.get("temperature_c") is not None
                else "-",
            ),
            kv("Load average", esc(", ".join(f"{x:.2f}" for x in health.get("load_average", [])))),
            kv(
                "Memory",
                f"{esc(memory.get('used_mb'))} / {esc(memory.get('total_mb'))} MB "
                f"({esc(memory.get('percent_used'))}%)",
            ),
            kv(
                "Disk",
                f"{esc(disk.get('used_gb'))} / {esc(disk.get('total_gb'))} GB "
                f"({esc(disk.get('percent_used'))}%)",
            ),
        ]
    )

    service_rows = "".join(
        f"<tr><td>{esc(s.get('unit'))}</td>"
        f"<td>{badge(s.get('running'), 'RUNNING', s.get('ActiveState') or 'STOPPED')}</td>"
        f"<td>{esc(s.get('UnitFileState') or '-')}</td>"
        f"<td>{esc(s.get('NRestarts') or '0')}</td></tr>"
        for s in report.get("services", [])
    )

    collector = report.get("collector", {})
    collector_html = (
        f"<div class='grid'>{kv('Buffered', esc(collector.get('buffered')))}"
        f"{kv('Total', esc(collector.get('total')))}"
        f"{kv('Last sync', esc(collector.get('last_sync') or 'never'))}</div>"
        if collector.get("present")
        else f"<p class='muted'>{esc(collector.get('error', 'not installed'))}</p>"
    )

    return f"""
<section>
  <h2>Connectivity tests</h2>
  <table><thead><tr><th>Test</th><th>Result</th><th>Detail</th><th>Latency</th></tr></thead>
  <tbody>{test_rows}</tbody></table>
  <div class="actions" style="margin-top:.75rem">
    <form method="post" action="/action/rerun-diagnostics">
      <button class="primary">Run tests again</button></form>
  </div>
</section>

<section>
  <h2>Interfaces</h2>
  <table><thead><tr><th>Device</th><th>Type</th><th>State</th><th>Profile</th>
  <th>Address</th><th>Gateway</th></tr></thead><tbody>{iface_rows}</tbody></table>
</section>

<section><h2>Routes</h2><pre>{esc(report.get("routes"))}</pre></section>
<section><h2>Addresses</h2><pre>{esc(report.get("addresses"))}</pre></section>
<section><h2>DNS configuration</h2><pre>{esc(report.get("dns"))}</pre></section>

<section><h2>System health</h2><div class="grid">{health_cells}</div></section>

<section>
  <h2>Services</h2>
  <table><thead><tr><th>Unit</th><th>State</th><th>Enabled</th><th>Restarts</th></tr></thead>
  <tbody>{service_rows}</tbody></table>
</section>

<section><h2>Collector buffer</h2>{collector_html}</section>"""


def logs_body(network: List[Dict[str, Any]], collector: List[Dict[str, Any]]) -> str:
    def render(entries: Iterable[Dict[str, Any]]) -> str:
        items = list(entries)
        if not items:
            return '<p class="muted">No entries.</p>'
        return '<div class="log">' + "".join(
            f'<div class="p{esc(e.get("priority"))}">'
            f'<span class="t">{esc(e.get("time"))}</span> {esc(e.get("message"))}</div>'
            for e in items
        ) + "</div>"

    return f"""
<section><h2>Networking events</h2>{render(network)}</section>
<section><h2>Collector events</h2>{render(collector)}</section>"""


def system_body(status: Dict[str, Any], services: List[Dict[str, Any]]) -> str:
    ap = status.get("access_point", {})
    overrides = status.get("overrides", {})

    service_buttons = "".join(
        f"""<form method="post" action="/action/restart-service">
  <input type="hidden" name="unit" value="{esc(s.get("unit"))}">
  <button type="submit">Restart {esc((s.get("unit") or "").replace(".service", ""))}</button>
</form>"""
        for s in services
        if s.get("present") and s.get("unit") != "energy-node-netd.service"
    )

    ap_controls = (
        """<form method="post" action="/action/ap-stop">
             <button class="danger">Disable maintenance AP</button></form>"""
        if ap.get("active")
        else """<form method="post" action="/action/ap-start"
                     onsubmit="return confirm('This drops the current Wi-Fi connection. Continue?')">
             <button>Force maintenance AP</button></form>"""
    )

    override_note = ""
    if overrides.get("force_ap"):
        override_note = (
            '<p class="muted">The maintenance AP is pinned open by an operator. '
            "It will be released automatically when a network is joined.</p>"
        )
    elif overrides.get("suppress_ap"):
        override_note = (
            '<p class="muted">Automatic AP activation is deferred until the node '
            "next comes back online.</p>"
        )

    return f"""
<section>
  <h2>Maintenance access point</h2>
  <div class="grid">
    {kv("SSID", esc(ap.get("ssid")))}
    {kv("Portal address", esc(ap.get("url")))}
    {kv("State", badge(ap.get("active"), "ACTIVE", "inactive"))}
    {kv("Clients", esc(ap.get("clients", 0)))}
  </div>
  <div class="actions" style="margin-top:.75rem">{ap_controls}</div>
  {override_note}
</section>

<section>
  <h2>Services</h2>
  <div class="actions">
    {service_buttons}
    <form method="post" action="/action/restart-networking">
      <button class="danger">Restart networking</button></form>
  </div>
</section>

<section>
  <h2>Power</h2>
  <div class="actions">
    <form method="post" action="/action/reboot"
          onsubmit="return confirm('Reboot this node now?')">
      <button class="danger">Reboot node</button></form>
    <form method="post" action="/action/shutdown"
          onsubmit="return confirm('Shut this node down? It will need physical access to restart.')">
      <button class="danger">Shutdown</button></form>
  </div>
</section>

<section>
  <h2>Factory network reset</h2>
  <p class="muted">
    Deletes every saved Wi-Fi profile and raises the maintenance access point.
    Measurements, the SQLite buffer, logs, node identity and configuration are
    <strong>not</strong> touched.
  </p>
  <form method="post" action="/action/factory-reset"
        onsubmit="return confirm('Delete all saved Wi-Fi networks? Measurement data is preserved.')">
    <div class="field" style="max-width:22rem">
      <label>Type RESET-NETWORK to confirm</label>
      <input name="confirm" autocomplete="off" required placeholder="RESET-NETWORK">
    </div>
    <div style="margin-top:.6rem">
      <button class="danger" type="submit">Reset network configuration</button>
    </div>
  </form>
</section>"""
