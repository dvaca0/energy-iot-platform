"""System metrics without psutil.

The canonical heartbeat is produced by the collector, whose venv contains only
`requests`. Everything here reads /proc, /sys and os.* so the hardening
package never depends on a pip install succeeding on a field node.

Also provides a capability probe for Pi-model differences: `vcgencmd
pmic_read_adc` exists on a Pi 5 but NOT on a Pi 4, so per-rail power must
degrade honestly rather than silently record nulls forever.
"""

from __future__ import annotations

__version__ = "1.0.0"

import os
import re
import socket
import subprocess
import time
from typing import Optional

_boot_time: Optional[float] = None
_caps: Optional[dict] = None


# --------------------------------------------------------------- helpers
def _read(path: str) -> Optional[str]:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def vcgencmd(*args: str) -> Optional[str]:
    try:
        r = subprocess.run(["vcgencmd", *args], capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def capabilities() -> dict:
    """Probe once what this board can actually report."""
    global _caps
    if _caps is not None:
        return _caps
    model = _read("/proc/device-tree/model") or ""
    model = model.replace("\x00", "").strip()
    _caps = {
        "model": model,
        "is_pi5": "Raspberry Pi 5" in model,
        "vcgencmd": vcgencmd("version") is not None,
        # Pi 5 only. On a Pi 4 this returns None and per-rail power is simply
        # unavailable - we report that rather than fabricating zeros.
        "pmic_adc": vcgencmd("pmic_read_adc") is not None,
        "throttled": vcgencmd("get_throttled") is not None,
        "watchdog": os.path.exists("/dev/watchdog0"),
        "rtc_wakealarm": os.path.exists("/sys/class/rtc/rtc0/wakealarm"),
    }
    return _caps


# --------------------------------------------------------------- metrics
def hostname() -> str:
    return socket.gethostname()


def boot_time() -> float:
    global _boot_time
    if _boot_time is None:
        stat = _read("/proc/stat") or ""
        m = re.search(r"^btime (\d+)", stat, re.M)
        _boot_time = float(m.group(1)) if m else time.time()
    return _boot_time


def uptime_seconds() -> Optional[float]:
    up = _read("/proc/uptime")
    if up:
        try:
            return round(float(up.split()[0]), 1)
        except ValueError:
            pass
    return None


def loadavg() -> tuple:
    try:
        return os.getloadavg()
    except OSError:
        return (None, None, None)


def cpu_count() -> int:
    return os.cpu_count() or 1


_prev_cpu = None


def _cpu_sample():
    line = (_read("/proc/stat") or "").split("\n")[0]
    if not line.startswith("cpu "):
        return None
    parts = [int(x) for x in line.split()[1:]]
    return parts[3] + (parts[4] if len(parts) > 4 else 0), sum(parts)


def cpu_percent(prime: float = 0.2) -> Optional[float]:
    """CPU usage from two /proc/stat samples.

    In a long-running process consecutive calls give a free delta. For one-shot
    invocations there is no previous sample, so we take a short priming sample
    rather than returning null - a null here made cpu_percent absent from every
    heartbeat produced by a short-lived process.
    """
    global _prev_cpu
    cur = _cpu_sample()
    if cur is None:
        return None
    if _prev_cpu is None:
        time.sleep(prime)
        prev, cur = cur, _cpu_sample()
        if cur is None:
            return None
    else:
        prev = _prev_cpu
    _prev_cpu = cur
    di, dt = cur[0] - prev[0], cur[1] - prev[1]
    if dt <= 0:
        return None
    return round(100.0 * (1.0 - di / dt), 1)


def memory() -> dict:
    info = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            try:
                info[k.strip()] = int(v.split()[0])
            except (ValueError, IndexError):
                pass
    total, avail = info.get("MemTotal"), info.get("MemAvailable")
    st, sf = info.get("SwapTotal"), info.get("SwapFree")
    return {
        "memory_percent": round(100.0 * (total - avail) / total, 1)
        if total and avail is not None else None,
        "swap_percent": round(100.0 * (st - sf) / st, 1)
        if st and sf is not None and st > 0 else 0.0,
    }


def disk(path: str = "/") -> dict:
    try:
        s = os.statvfs(path)
        total = s.f_blocks * s.f_frsize
        free = s.f_bavail * s.f_frsize
        return {"disk_percent": round(100.0 * (total - free) / total, 1) if total else None,
                "disk_free_mb": round(free / 1e6, 1)}
    except OSError:
        return {"disk_percent": None, "disk_free_mb": None}


def cpu_temperature_c() -> Optional[float]:
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    if raw:
        try:
            return round(int(raw) / 1000.0, 1)
        except ValueError:
            pass
    out = vcgencmd("measure_temp")
    if out and "=" in out:
        try:
            return float(out.split("=", 1)[1].rstrip("'C"))
        except ValueError:
            pass
    return None


def filesystem_readonly(mount: str = "/") -> Optional[bool]:
    """True only if the mount is genuinely mounted read-only."""
    try:
        with open("/proc/mounts") as fh:
            for line in fh:
                p = line.split()
                if len(p) > 3 and p[1] == mount:
                    return "ro" in p[3].split(",")
    except OSError:
        pass
    return None


def throttled_mask() -> Optional[int]:
    raw = vcgencmd("get_throttled")
    if raw and "=" in raw:
        try:
            return int(raw.split("=", 1)[1], 16)
        except ValueError:
            pass
    return None


THROTTLE_BITS = {
    0: "undervoltage_now", 1: "arm_freq_capped_now",
    2: "throttled_now", 3: "soft_temp_limit_now",
    16: "undervoltage_occurred", 17: "arm_freq_capped_occurred",
    18: "throttling_occurred", 19: "soft_temp_limit_occurred",
}


def decode_throttle(mask: int) -> list:
    return [n for b, n in THROTTLE_BITS.items() if mask >> b & 1]


# --------------------------------------------------------------- network
IFF_UP = 0x1
IFF_RUNNING = 0x40


def _iface_up(name: str) -> Optional[bool]:
    """True if the interface is up AND running.

    operstate alone is not enough: TUN devices such as tailscale0 report
    "unknown" even when fully operational, which made tailscale_up read false
    on a node whose VPN was working. Fall back to the interface flags, where
    IFF_UP|IFF_RUNNING is authoritative for every device type.
    """
    st = _read(f"/sys/class/net/{name}/operstate")
    if st is None:
        return None                      # interface does not exist
    if st == "up":
        return True
    if st == "down":
        return False
    # "unknown" / "dormant": TUN devices such as tailscale0 sit here
    # permanently and never set IFF_RUNNING, so IFF_UP is the honest signal.
    # Verified on N001: tailscale0 operstate=unknown flags=0x1091 carrier=1
    # with a working VPN - requiring IFF_RUNNING reported it as down.
    flags = _read(f"/sys/class/net/{name}/flags")
    try:
        return bool(int(flags, 16) & IFF_UP)
    except (TypeError, ValueError):
        return False


def network() -> dict:
    out = {"ethernet_up": _iface_up("eth0"), "wifi_up": _iface_up("wlan0"),
           "tailscale_up": _iface_up("tailscale0"), "ip_address": None}
    for iface in ("eth0", "wlan0", "tailscale0"):
        addr = _primary_ipv4(iface)
        if addr:
            out["ip_address"] = addr
            break
    return out


def _primary_ipv4(iface: str) -> Optional[str]:
    try:
        r = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", iface],
                           capture_output=True, text=True, timeout=5)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r.stdout)
        return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def systemd_is_active(unit: str) -> Optional[str]:
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def systemd_main_pid(unit: str) -> Optional[int]:
    try:
        r = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", unit],
                           capture_output=True, text=True, timeout=10)
        pid = r.stdout.strip()
        return int(pid) if pid.isdigit() and int(pid) > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def time_synchronized() -> Optional[bool]:
    """Has the clock been disciplined by NTP since boot?

    These boards do not hold time across a power cut: the kernel sets the clock
    to 1970, systemd advances it to a saved timestamp that may be days stale,
    and only then does NTP correct it. Anything that stamps a record before
    that last step writes a wrong timestamp, so the answer must be knowable.

    None when it cannot be determined — never a silent True.
    """
    # systemd creates this the moment timesyncd accepts a sample.
    if os.path.exists("/run/systemd/timesync/synchronized"):
        return True
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized",
                            "--value"],
                           capture_output=True, text=True, timeout=10)
        out = r.stdout.strip().lower()
        if out in ("yes", "true", "1"):
            return True
        if out in ("no", "false", "0"):
            return False
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def watchdog_state() -> dict:
    base = "/sys/class/watchdog/watchdog0"
    if not os.path.isdir(base):
        return {"present": False}
    return {"present": True,
            "state": _read(f"{base}/state"),
            "timeout": _read(f"{base}/timeout"),
            "identity": _read(f"{base}/identity"),
            "bootstatus": _read(f"{base}/bootstatus")}
