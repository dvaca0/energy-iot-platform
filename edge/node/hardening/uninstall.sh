#!/usr/bin/env bash
# ===========================================================================
# energy-node hardening package — uninstaller / rollback
# ===========================================================================
#   sudo ./uninstall.sh                      remove package, keep data
#   sudo ./uninstall.sh --purge              also delete power_telemetry.db
#   sudo ./uninstall.sh --restore <backup>   restore a pre-install backup
#   sudo ./uninstall.sh --dry-run
#
# WHAT IS NOT TOUCHED
#   edge_buffer.db, all historical readings, deployments, attribution, the
#   collector's measurement/buffering/sync logic, and node.env. The only
#   collector change this package makes is inside send_heartbeat(); --restore
#   puts the original collector.py back.
#
# AFTER UNINSTALL the node stops publishing heartbeats and becomes invisible
# to liveness monitoring again — the exact condition that cost 43h37m on
# 2026-08-01. Only uninstall if you are replacing it with something better.
# ===========================================================================
set -uo pipefail

EN_ROOT="${EN_ROOT:-/opt/energy-node}"
DEST="$EN_ROOT/hardening"
PURGE=0; DRY=0; RESTORE=""

RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; RST=$'\e[0m'
ok(){ echo "  ${GRN}OK${RST}   $*"; }
warn(){ echo "  ${YEL}WARN${RST} $*"; }
die(){ echo "  ${RED}FAIL${RST} $*" >&2; exit 1; }
step(){ echo; echo "==> $*"; }
run(){ if [ "$DRY" = 1 ]; then echo "       [dry-run] $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1;;
    --dry-run) DRY=1;;
    --restore) RESTORE="${2:-}"; shift;;
    -h|--help) sed -n '2,22p' "$0"; exit 0;;
    *) die "unknown option: $1";;
  esac; shift
done

[ "$(id -u)" = 0 ] || die "must run as root"

UNITS=(energy-node-powerlog.service energy-node-selfheal.timer
       energy-node-selfheal.service energy-node-recovery-arm.service
       energy-node-verify.timer energy-node-verify.service)

step "Stop and disable units"
for u in "${UNITS[@]}"; do
  if systemctl list-unit-files "$u" >/dev/null 2>&1; then
    run systemctl disable --now "$u" >/dev/null 2>&1
    ok "disabled $u"
  fi
done

step "Remove unit files"
for u in "${UNITS[@]}"; do
  [ -f "/etc/systemd/system/$u" ] && run rm -f "/etc/systemd/system/$u"
done
# Legacy unit from the pre-package implementation.
[ -f /etc/systemd/system/energy-node-agent.service ] && \
  run rm -f /etc/systemd/system/energy-node-agent.service
run systemctl daemon-reload
ok "units removed"

if [ -n "$RESTORE" ]; then
  step "Restore from backup: $RESTORE"
  [ -d "$RESTORE" ] || die "backup directory not found: $RESTORE"
  if [ -f "$RESTORE/collector.py" ]; then
    run cp -a "$RESTORE/collector.py" "$EN_ROOT/app/collector.py"
    ok "collector.py restored (reverts the canonical heartbeat)"
  fi
  if [ -f "$RESTORE/config.txt" ]; then
    run cp -a "$RESTORE/config.txt" /boot/firmware/config.txt
    warn "config.txt restored — this may disable I2C again; reboot to apply"
  fi
  for f in "$RESTORE"/systemd/*; do
    [ -e "$f" ] && run cp -a "$f" /etc/systemd/system/
  done
  run systemctl daemon-reload
  ok "restore complete"
fi

step "Remove package files"
if [ -d "$DEST" ]; then
  run rm -rf "$DEST"
  ok "removed $DEST"
fi

if [ "$PURGE" = 1 ]; then
  step "Purge telemetry data"
  run rm -f "$EN_ROOT"/database/power_telemetry.db*
  run rm -f "$EN_ROOT"/state/selfheal_failures
  ok "power telemetry purged"
else
  echo
  warn "power_telemetry.db kept (use --purge to delete it)"
fi

step "Restart collector"
if systemctl list-unit-files energy-node-collector.service >/dev/null 2>&1; then
  run systemctl restart energy-node-collector.service
  ok "collector restarted"
fi

echo
echo "${YEL}=== UNINSTALL COMPLETE ===${RST}"
echo "edge_buffer.db, historical readings, deployments and attribution untouched."
if [ -z "$RESTORE" ]; then
  echo
  echo "${YEL}NOTE${RST}: collector.py still contains the canonical heartbeat and will"
  echo "log 'Heartbeat UNAVAILABLE' now that the package is gone."
  echo "To fully revert it:  sudo $0 --restore <backup-dir>"
fi
exit 0
