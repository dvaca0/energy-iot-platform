#!/usr/bin/env bash
# ===========================================================================
# energy-node hardening package — installer
# ===========================================================================
# Idempotent. Safe to re-run. Creates timestamped backups of everything it
# replaces, so uninstall.sh can put the node back exactly as it was.
#
#   sudo ./install.sh                 install / upgrade
#   sudo ./install.sh --dry-run       show what would happen, change nothing
#   sudo ./install.sh --no-verify     skip the post-install verification
#   sudo ./install.sh --user NAME     service account (default: energy-node owner)
#
# NOTHING EXPERIMENTAL IS ENABLED. ups_wake, rtc_wake and gpio_wake ship
# disabled and stay disabled until validated in a maintenance window.
# ===========================================================================
set -uo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EN_ROOT="${EN_ROOT:-/opt/energy-node}"
DEST="$EN_ROOT/hardening"
CONF="$DEST/config/hardening.conf"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP="$EN_ROOT/backups/hardening-install-$TS"
DRY=0; VERIFY=1; SVC_USER=""; FORCE=0

RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; RST=$'\e[0m'
ok(){ echo "  ${GRN}OK${RST}   $*"; }
warn(){ echo "  ${YEL}WARN${RST} $*"; }
die(){ echo "  ${RED}FAIL${RST} $*" >&2; exit 1; }
step(){ echo; echo "==> $*"; }
run(){ if [ "$DRY" = 1 ]; then echo "       [dry-run] $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1;;
    --no-verify) VERIFY=0;;
    --force) FORCE=1;;
    --user) SVC_USER="${2:-}"; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) die "unknown option: $1";;
  esac; shift
done

[ "$(id -u)" = 0 ] || die "must run as root (sudo ./install.sh)"

# --------------------------------------------------------------- preflight
step "Preflight"
[ -d "$EN_ROOT" ] || die "$EN_ROOT not found — is this an energy-node?"
[ -f "$EN_ROOT/config/node.env" ] || die "$EN_ROOT/config/node.env missing"
NODE_ID="$(grep -oP '(?<=^NODE_ID=).*' "$EN_ROOT/config/node.env" 2>/dev/null || echo '')"
[ -n "$NODE_ID" ] || die "NODE_ID not set in node.env — node-specific config is required"
ok "node identity: $NODE_ID"

if [ -z "$SVC_USER" ]; then
  SVC_USER="$(stat -c %U "$EN_ROOT/app" 2>/dev/null || echo root)"
fi
SVC_GROUP="$(id -gn "$SVC_USER" 2>/dev/null || echo "$SVC_USER")"
id "$SVC_USER" >/dev/null 2>&1 || die "service user '$SVC_USER' does not exist"
ok "service account: $SVC_USER:$SVC_GROUP"

command -v python3 >/dev/null || die "python3 not found"
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
ok "python3 $PYV"
python3 - <<'PY' || die "python stdlib check failed"
import ctypes, fcntl, sqlite3, json, socket   # noqa
PY
ok "stdlib deps present (no pip install required)"

command -v systemctl >/dev/null || die "systemd not found"

# Version compatibility MUST be checked before we replace anything: a config
# written for a newer schema can mean something different to older code.
FORCE_PY=$([ "$FORCE" = 1 ] && echo True || echo False)
COMPAT_OUT="$(python3 -c "
import sys; sys.path.insert(0,'$PKG_DIR/lib')
import version
ok,msg = version.check_upgrade(force=$FORCE_PY)
print(('OK|' if ok else 'NO|')+msg)
" 2>&1)"
case "$COMPAT_OUT" in
  OK*) ok "compatibility: ${COMPAT_OUT#OK|}" ;;
  NO*) die "compatibility: ${COMPAT_OUT#NO|}" ;;
  *)   warn "compatibility check inconclusive: $COMPAT_OUT" ;;
esac
grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null \
  && ok "board: $(tr -d '\0' </proc/device-tree/model)" \
  || warn "not a Raspberry Pi — UPS/PMIC features will report unavailable"

# --------------------------------------------------------------- backup
step "Backup"
run mkdir -p "$BACKUP"/{systemd,config}
for u in energy-node-powerlog.service energy-node-selfheal.service \
         energy-node-selfheal.timer energy-node-recovery-arm.service \
         energy-node-verify.service energy-node-verify.timer; do
  [ -f "/etc/systemd/system/$u" ] && run cp -a "/etc/systemd/system/$u" "$BACKUP/systemd/"
done
[ -f "$CONF" ] && run cp -a "$CONF" "$BACKUP/config/"
[ -f /boot/firmware/config.txt ] && run cp -a /boot/firmware/config.txt "$BACKUP/"
[ -f "$EN_ROOT/app/collector.py" ] && run cp -a "$EN_ROOT/app/collector.py" "$BACKUP/"
run bash -c "systemctl list-unit-files 'energy-node-*' --no-pager > '$BACKUP/unit-state-before.txt' 2>/dev/null"
ok "backup: $BACKUP"

# --------------------------------------------------------------- directories
step "Directories"
for d in "$DEST" "$EN_ROOT/database" "$EN_ROOT/state" "$EN_ROOT/logs"; do
  run mkdir -p "$d"
done
run chown -R "$SVC_USER:$SVC_GROUP" "$EN_ROOT/database" "$EN_ROOT/state" "$EN_ROOT/logs"
ok "directories ready"

# --------------------------------------------------------------- files
step "Package files"
if [ "$PKG_DIR" != "$DEST" ]; then
  run mkdir -p "$DEST"
  run cp -a "$PKG_DIR/lib" "$PKG_DIR/bin" "$PKG_DIR/systemd" "$PKG_DIR/docs" "$DEST/"
  run mkdir -p "$DEST/config"
  # Never clobber an existing tuned config; ship .new instead.
  if [ -f "$CONF" ]; then
    run cp -a "$PKG_DIR/config/hardening.conf" "$CONF.new"
    warn "existing config kept; new defaults written to $(basename "$CONF").new"
  else
    run cp -a "$PKG_DIR/config/hardening.conf" "$CONF"
  fi
  [ -d "$PKG_DIR/backend" ] && run cp -a "$PKG_DIR/backend" "$DEST/"
else
  ok "installing in place from $PKG_DIR"
fi
run chmod 0755 "$DEST"/bin/*
run chown -R root:root "$DEST/lib" "$DEST/bin" 2>/dev/null
run chown "root:$SVC_GROUP" "$CONF" 2>/dev/null
run chmod 0644 "$CONF" 2>/dev/null
ok "files installed to $DEST"

# Record what was installed: version, checksum, dates, driver versions.
if [ "$DRY" = 0 ]; then
  PYTHONPATH="$DEST/lib" python3 -c "
import sys; sys.path.insert(0,'$DEST/lib')
import version
st = version.write_state()
print('  version state: %s checksum %s' % (st['package_version'], st['package_checksum'][:12]))
" 2>/dev/null || warn "could not record version state"
fi

# --------------------------------------------------------------- i2c
step "I2C (required for UPS visibility)"
BOOTCFG=/boot/firmware/config.txt
[ -f "$BOOTCFG" ] || BOOTCFG=/boot/config.txt
if [ -f "$BOOTCFG" ]; then
  if grep -qE '^\s*dtparam=i2c_arm=on' "$BOOTCFG"; then
    ok "dtparam=i2c_arm=on already persisted"
  elif grep -qE '^\s*#\s*dtparam=i2c_arm=on' "$BOOTCFG"; then
    run sed -i 's/^\s*#\s*dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "$BOOTCFG"
    warn "enabled dtparam=i2c_arm=on — REBOOT REQUIRED for UPS visibility"
  else
    run bash -c "printf '\n# enabled by energy-node hardening: UPS HAT is on I2C\ndtparam=i2c_arm=on\n' >> '$BOOTCFG'"
    warn "appended dtparam=i2c_arm=on — REBOOT REQUIRED for UPS visibility"
  fi
else
  warn "no config.txt found; skipping I2C enablement"
fi
if [ ! -e /dev/i2c-1 ] && [ "$DRY" = 0 ]; then
  dtoverlay i2c1 2>/dev/null && ok "i2c1 overlay applied at runtime (survives until reboot)" \
                             || warn "could not apply runtime i2c overlay"
fi

# --------------------------------------------------------------- systemd
step "systemd units"
for f in "$DEST"/systemd/*.service "$DEST"/systemd/*.timer; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  if [ "$DRY" = 1 ]; then echo "       [dry-run] install $base"; continue; fi
  sed -e "s/__EN_USER__/$SVC_USER/g" -e "s/__EN_GROUP__/$SVC_GROUP/g" \
      "$f" > "/etc/systemd/system/$base"
  chmod 0644 "/etc/systemd/system/$base"
done
ok "units written to /etc/systemd/system"
run systemctl daemon-reload

# --------------------------------------------------------------- enable
step "Enable services"
# Always-on: instrumentation + verification + the shutdown hook (which is
# itself inert unless its flag is set).
run systemctl enable energy-node-powerlog.service
# `enable --now` is a no-op when the unit is already active, which on an
# UPGRADE leaves the OLD process running from the previous (possibly deleted)
# executable. Always restart so re-running the installer actually deploys.
run systemctl restart energy-node-powerlog.service
run systemctl enable energy-node-recovery-arm.service
run systemctl start  energy-node-recovery-arm.service
run systemctl enable --now energy-node-verify.timer
# Self-heal timer is enabled but the check itself is a no-op while its flag
# is 0, so enabling it now costs nothing and avoids a second deploy later.
run systemctl enable --now energy-node-selfheal.timer
ok "services enabled"

step "Restart collector (picks up the canonical heartbeat)"
if systemctl list-unit-files energy-node-collector.service >/dev/null 2>&1; then
  run systemctl restart energy-node-collector.service
  ok "collector restarted"
else
  warn "energy-node-collector.service not present — heartbeat will not publish"
fi

# --------------------------------------------------------------- guard
step "Safety check: no experimental recovery enabled"
BAD=0
for f in RECOVERY_UPS_ARM_ON_SHUTDOWN RECOVERY_RTC_WAKE RECOVERY_GPIO_WAKE; do
  v="$(grep -oP "(?<=^$f=).*" "$CONF" 2>/dev/null || echo 0)"
  if [ "$v" != "0" ]; then warn "$f=$v is ENABLED and is UNVALIDATED"; BAD=1; fi
done
[ "$BAD" = 0 ] && ok "all experimental recovery disabled, as required"

# --------------------------------------------------------------- verify
if [ "$VERIFY" = 1 ] && [ "$DRY" = 0 ]; then
  step "Regression suite"
  if "$DEST/bin/energy-node" selftest; then
    ok "regression suite passed"
  else
    warn "regression suite reported failures (see above)"
  fi

  step "Verification"
  sleep 5
  if "$DEST/bin/energy-node" doctor; then
    echo; echo "${GRN}=== INSTALL SUCCEEDED — $NODE_ID verification PASSED ===${RST}"
    echo "Backup: $BACKUP"
    exit 0
  else
    echo; echo "${RED}=== INSTALL COMPLETED BUT VERIFICATION FAILED ===${RST}"
    echo "Review the FAIL lines above. Roll back with:"
    echo "  sudo $DEST/uninstall.sh --restore $BACKUP"
    exit 1
  fi
fi

echo; echo "${GRN}=== INSTALL COMPLETE (verification skipped) ===${RST}"
echo "Backup: $BACKUP"
exit 0
