# node.filesystem_readonly — root cause

## Verdict: monitoring logic bug. The storage is healthy.

The collector runs under systemd sandboxing:

    ProtectSystem=strict
    ProtectHome=true
    PrivateTmp=true
    ReadWritePaths=/opt/energy-node

`ProtectSystem=strict` places the service in a **private mount namespace** in
which `/` is genuinely mounted read-only. Measured:

| View | mount namespace | `/` options | probe result |
|---|---|---|---|
| Collector (PID 1305) | `mnt:[4026532625]` | `ro,nosuid,noatime` | **True** |
| Host / SSH shell | `mnt:[4026531832]` | `rw,noatime` | **False** |

Verified with `nsenter -t 1305 -m`: inside the namespace the probe returns
`True`; outside it returns `False`. Same code, same file, same host.

`disk_percent` diverges for the same reason (17.5 inside vs 13.9 on host):
`PrivateTmp=true` substitutes a different `/tmp`.

## Consequence

`sysinfo.filesystem_readonly("/")` measures **the service's sandbox**, not the
storage device. Every hardened service would report the same. The value is not
wrong about the namespace — it is the wrong question.

The collector writes normally to its `ReadWritePaths=/opt/energy-node`: 75,261
buffered measurements, newest seconds before capture, SQLite commit verified.

## Storage evidence (unchanged from audit, re-verified)

* `/proc/mounts` host: `rw,noatime`; `statvfs ST_RDONLY`: False
* Write tests: `/tmp`, `$HOME`, rootfs, `/opt/energy-node` — all OK
* SQLite: table created, row inserted, committed, dropped — OK
* `tune2fs`: `Filesystem state: clean`, no error count
* remount-ro events, all boots: **0**; mmc errors: **0**; ext4 errors: **0**
* Card `SN64G`, manufactured 06/2025, 46 GB lifetime writes

## Required fix

1. Probe the path the service is *responsible for* (its state directory), not `/`.
2. Report tri-state honestly: True = confirmed ro, False = confirmed rw, NULL = unknown.
3. Corroborate before alarming: a read-only claim alongside successful writes,
   growing buffers and an active collector is a contradiction, not a fault.
4. Never assert SD-card failure without ext4 / I/O / mmc / remount-ro evidence.
