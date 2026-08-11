"""``netdctl`` -- command line client for the networking subsystem.

A thin front end over the control socket, used by operators over SSH, by the
deployment tooling for verification, and by anyone debugging a node that still
has a shell but has lost its portal.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from .config import load_config
from .ipc import ControlClient
from .logging_setup import configure


def _client() -> ControlClient:
    config = load_config()
    return ControlClient(config.paths.control_socket)


def _emit(response: Dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(response, indent=2, default=str))
        return 0 if response.get("ok") else 1

    if not response.get("ok"):
        print(f"error: {response.get('error', 'unknown error')}", file=sys.stderr)
        return 1
    if response.get("message"):
        print(response["message"])
    data = response.get("data")
    if data is not None:
        print(json.dumps(data, indent=2, default=str))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    response = _client().call("status")
    if args.json or not response.get("ok"):
        return _emit(response, args.json)

    data = response.get("data", {})
    node = data.get("node", {})
    conn = data.get("connectivity") or {}
    ap = data.get("access_point", {})
    print(f"Node          : {node.get('id')} ({node.get('hostname')})")
    print(f"State         : {data.get('state')}  -- {data.get('state_reason')}")
    print(f"Link          : {conn.get('link')} on {conn.get('interface') or '-'}")
    print(f"Address       : {conn.get('ipv4') or '-'}")
    print(f"SSID          : {data.get('ssid') or '-'}")
    # DNS/internet/backend are not measured on every cycle; never present an
    # unmeasured probe as a failure.
    measured = conn.get("deep_measured", True)
    deep = (lambda v: _yn(v)) if measured else (lambda _v: "n/a")
    age = conn.get("deep_age")
    suffix = f"   (checked {int(age)}s ago)" if measured and age else ""
    print(
        "Checks        : "
        f"gateway={_yn(conn.get('gateway_ok'))} dns={deep(conn.get('dns_ok'))} "
        f"internet={deep(conn.get('internet_ok'))} backend={deep(conn.get('backend_ok'))}"
        f"{suffix}"
    )
    print(f"Network       : {'available' if data.get('network_available') else 'unavailable'}")
    print(
        f"Maintenance AP: {'ACTIVE' if ap.get('active') else 'inactive'} "
        f"(SSID {ap.get('ssid')}, {ap.get('url')}, {ap.get('clients', 0)} client(s))"
    )
    return 0


def _yn(value: Optional[bool]) -> str:
    return "ok" if value else "FAIL"


def _cmd_scan(args: argparse.Namespace) -> int:
    response = _client().call("wifi.scan", force=True)
    if args.json or not response.get("ok"):
        return _emit(response, args.json)
    networks: List[Dict[str, Any]] = response.get("data", {}).get("networks", [])
    if not networks:
        print("no networks found")
        return 0
    print(f"{'SSID':<32} {'SIGNAL':>7}  {'SECURITY':<10} {'BAND':<7} SAVED")
    for net in networks:
        print(
            f"{net.get('ssid', '')[:32]:<32} {net.get('signal', 0):>6}%  "
            f"{net.get('security', ''):<10} {net.get('band') or '-':<7} "
            f"{'yes' if net.get('saved') else ''}"
        )
    return 0


def _cmd_saved(args: argparse.Namespace) -> int:
    response = _client().call("wifi.saved")
    if args.json or not response.get("ok"):
        return _emit(response, args.json)
    saved: List[Dict[str, Any]] = response.get("data", {}).get("saved", [])
    if not saved:
        print("no saved networks")
        return 0
    print(f"{'SSID':<32} {'PRIORITY':>8} {'AUTO':>5} ACTIVE")
    for net in saved:
        print(
            f"{net.get('ssid', '')[:32]:<32} {net.get('priority', 0):>8} "
            f"{'yes' if net.get('autoconnect') else 'no':>5} "
            f"{'yes' if net.get('active') else ''}"
        )
    return 0


def _cmd_networks(args: argparse.Namespace) -> int:
    """The effective whitelist: where each entry came from, and its health."""
    if getattr(args, "reset_operator", False):
        response = _client().call("wifi.reset_operator")
        return _emit(response, args.json)

    response = _client().call("wifi.networks")
    if args.json or not response.get("ok"):
        return _emit(response, args.json)
    data = response.get("data", {})
    ranked: List[Dict[str, Any]] = data.get("ranked", [])
    health: Dict[str, Any] = data.get("health", {})
    creds = set(data.get("secrets", {}).get("ssids_with_credentials", []))

    if not ranked:
        print("no known networks declared or saved")
        return 0

    print(f"{'#':>2} {'SSID':<24} {'SOURCE':<9} {'PRIO':>4} {'CRED':>4} "
          f"{'SIG':>4} {'FAILS':>5}  WHY")
    for i, c in enumerate(ranked, 1):
        ssid = c.get("ssid", "")
        h = health.get(ssid, {})
        mark = " " if c.get("eligible") else "-"
        print(f"{i:>2}{mark}{ssid[:24]:<24} {c.get('source', ''):<9} "
              f"{c.get('priority', 0):>4} "
              f"{'yes' if ssid in creds else 'NO':>4} "
              f"{(c.get('signal') if c.get('signal') is not None else '-'):>4} "
              f"{h.get('consecutive_failures', 0):>5}  {c.get('reason', '')}")
    sup = data.get("suppressed") or []
    if sup:
        print(f"\nsuppressed baseline networks: {', '.join(sup)}")
    print(f"\ncredentials: {data.get('secrets', {}).get('path')} "
          f"(mode {data.get('secrets', {}).get('mode')})")
    print("entries marked '-' are not being tried right now; see WHY")
    return 0


def _cmd_connect(args: argparse.Namespace) -> int:
    password = args.password
    if password is None and not args.open:
        import getpass

        password = getpass.getpass(f"Passphrase for {args.ssid}: ")
    return _emit(
        _client().call(
            "wifi.connect",
            ssid=args.ssid,
            password=password,
            priority=args.priority,
            hidden=args.hidden,
        ),
        args.json,
    )


def _cmd_forget(args: argparse.Namespace) -> int:
    return _emit(_client().call("wifi.forget", id=args.network), args.json)


def _cmd_priority(args: argparse.Namespace) -> int:
    return _emit(
        _client().call("wifi.priority", id=args.network, priority=args.priority), args.json
    )


def _cmd_disconnect(args: argparse.Namespace) -> int:
    return _emit(_client().call("wifi.disconnect"), args.json)


#: 'auto' is NOT a synonym for 'stop'. Stopping SUPPRESSES the AP so it is not
#: raised again straight away, which is right for an operator but wrong for
#: SAFE MODE - it needs the AP permitted, just not pinned. Mapping every
#: non-start action to ap.stop silently did the opposite.
_AP_COMMANDS = {"start": "ap.start", "stop": "ap.stop", "auto": "ap.auto"}


def _cmd_ap(args: argparse.Namespace) -> int:
    command = _AP_COMMANDS.get(args.action)
    if command is None:
        print(f"unknown ap action '{args.action}'")
        return 2
    return _emit(_client().call(command), args.json)


def _cmd_diagnostics(args: argparse.Namespace) -> int:
    response = _client().call("diagnostics.full")
    return _emit(response, True if not args.json else True)


def _cmd_logs(args: argparse.Namespace) -> int:
    command = "logs.collector" if args.source == "collector" else "logs.network"
    response = _client().call(command, lines=args.lines)
    if args.json or not response.get("ok"):
        return _emit(response, args.json)
    for entry in response.get("data", {}).get("entries", []):
        print(f"{entry.get('time', ''):<20} {entry.get('message', '')}")
    return 0


def _cmd_restart(args: argparse.Namespace) -> int:
    if args.target == "networking":
        return _emit(_client().call("net.restart"), args.json)
    return _emit(_client().call("service.restart", unit=args.target), args.json)


def _cmd_factory_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "This deletes all saved Wi-Fi profiles and raises the maintenance AP.\n"
            "Measurements, logs, node identity and configuration are preserved.\n"
            "Re-run with --yes to proceed.",
            file=sys.stderr,
        )
        return 1
    return _emit(_client().call("factory.network_reset", confirm="RESET-NETWORK"), args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netdctl",
        description="Control the Energy Node networking subsystem.",
    )
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show current network status").set_defaults(func=_cmd_status)
    sub.add_parser("scan", help="scan for Wi-Fi networks").set_defaults(func=_cmd_scan)
    sub.add_parser("saved", help="list saved networks").set_defaults(func=_cmd_saved)
    sub.add_parser("disconnect", help="disconnect Wi-Fi").set_defaults(func=_cmd_disconnect)

    networks = sub.add_parser(
        "networks",
        help="effective whitelist: git baseline + operator networks, with health")
    networks.add_argument(
        "--reset-operator", action="store_true",
        help="DELETE all operator-added networks and their credentials, "
             "returning to the git baseline")
    networks.set_defaults(func=_cmd_networks)

    connect = sub.add_parser("connect", help="join and save a Wi-Fi network")
    connect.add_argument("ssid")
    connect.add_argument("-p", "--password")
    connect.add_argument("--open", action="store_true", help="network has no passphrase")
    connect.add_argument("--priority", type=int, default=None)
    connect.add_argument("--hidden", action="store_true")
    connect.set_defaults(func=_cmd_connect)

    forget = sub.add_parser("forget", help="delete a saved network")
    forget.add_argument("network", help="SSID, profile name or UUID")
    forget.set_defaults(func=_cmd_forget)

    priority = sub.add_parser("priority", help="set roaming priority (higher wins)")
    priority.add_argument("network")
    priority.add_argument("priority", type=int)
    priority.set_defaults(func=_cmd_priority)

    ap = sub.add_parser("ap", help="control the maintenance access point")
    ap.add_argument("action", choices=["start", "stop", "auto"],
                    help="start pins the AP open; auto returns it to the "
                         "state machine (what SAFE MODE uses)")
    ap.set_defaults(func=_cmd_ap)

    sub.add_parser("diagnostics", help="full diagnostic report").set_defaults(
        func=_cmd_diagnostics
    )

    logs = sub.add_parser("logs", help="recent events")
    logs.add_argument("source", choices=["network", "collector"], nargs="?", default="network")
    logs.add_argument("-n", "--lines", type=int, default=100)
    logs.set_defaults(func=_cmd_logs)

    restart = sub.add_parser("restart", help="restart networking or a managed service")
    restart.add_argument("target", help="'networking' or a systemd unit name")
    restart.set_defaults(func=_cmd_restart)

    reset = sub.add_parser("factory-network-reset", help="delete all saved Wi-Fi and raise the AP")
    reset.add_argument("--yes", action="store_true", help="confirm the operation")
    reset.set_defaults(func=_cmd_factory_reset)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    configure(level="WARNING")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
