#!/usr/bin/env bash
#
# Install or upgrade the Smart Plug collection source on an Energy Node Pi.
#
# Extends the collector already running on the node; never replaces it and
# never touches the Energy Node pipeline. Every step is idempotent, so this is
# both the install path and the upgrade path.
#
#   ./install-smart-plugs.sh --node-id N001 [--backend URL] [--enable|--disable]
#   ./install-smart-plugs.sh --node-id N001 --dry-run
#
# Steps: inspect -> compare versions -> verify compatibility -> backup ->
# install changed files -> integrate -> configure -> restart if needed ->
# verify -> write deployment report.
#
set -euo pipefail

TS="$(date +%Y%m%d_%H%M%S)"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_DIR="/etc/energy-node"
CONF="${CONF_DIR}/smart-plugs.conf"
AVAILABLE="$(cat "${SRC_DIR}/VERSION" 2>/dev/null || echo unknown)"
REPORT_DIR="${SRC_DIR}/reports"

NODE_ID=""
BACKEND=""
ENABLE=""
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --node-id) NODE_ID="$2"; shift 2 ;;
    --backend) BACKEND="$2";  shift 2 ;;
    --enable)  ENABLE="1";    shift   ;;
    --disable) ENABLE="0";    shift   ;;
    --dry-run) DRY_RUN="1";   shift   ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf '  [FAIL] %s\n' "$*" >&2; exit 1; }

CHANGED_FILES=()
RESTART_REQUIRED="0"

say "Smart Plug installer  |  host=$(hostname)  |  ${TS}"

# ----------------------------------------------------------------- 1. inspect
step "1. Inspect current state"

UNIT=""
for candidate in energy-node-collector.service udec-edge.service; do
  if systemctl cat "${candidate}" >/dev/null 2>&1; then UNIT="${candidate}"; break; fi
done
[[ -n "${UNIT}" ]] || die "no known Energy Node collector unit found"

COLLECTOR="$(systemctl cat "${UNIT}" | awk -F' ' '/^ExecStart=/{print $NF; exit}')"
[[ -f "${COLLECTOR}" ]] || die "collector script not found: ${COLLECTOR}"

APP_DIR="$(dirname "${COLLECTOR}")"
NODE_ROOT="$(dirname "${APP_DIR}")"
PYTHON="$(systemctl cat "${UNIT}" | sed -nE 's/^ExecStart=([^ ]+).*/\1/p' | head -1)"
[[ -x "${PYTHON}" ]] || PYTHON="$(command -v python3)"
SVC_USER="$(systemctl cat "${UNIT}" | sed -nE 's/^User=(.*)/\1/p' | head -1)"
SVC_USER="${SVC_USER:-root}"
WAS_ACTIVE="$(systemctl is-active "${UNIT}" || true)"
ENVFILE="$(systemctl cat "${UNIT}" | sed -nE 's/^EnvironmentFile=-?(.*)/\1/p' | head -1)"

unit_env() { systemctl show "${UNIT}" -p Environment --value | tr ' ' '\n' | sed -nE "s/^$1=(.*)/\1/p" | head -1; }
file_env() { [[ -n "${ENVFILE}" && -r "${ENVFILE}" ]] && sed -nE "s/^$1=(.*)/\1/p" "${ENVFILE}" | head -1; }
conf_env() { [[ -r "${CONF}" ]] && sed -nE "s/^$1=(.*)/\1/p" "${CONF}" | head -1; }

# Existing installation, if any. Configuration is preserved across upgrades.
INSTALLED="none"
if [[ -f "${APP_DIR}/smart_plug_source.py" ]]; then
  INSTALLED="$("${PYTHON}" - "${APP_DIR}/smart_plug_source.py" <<'PYEOF' || echo unknown
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'^__version__\s*=\s*["\']([^"\']+)', src, re.M)
print(m.group(1) if m else "pre-1.2.0")
PYEOF
)"
fi

[[ -z "${NODE_ID}" ]] && NODE_ID="$(conf_env NODE_ID)"
[[ -z "${NODE_ID}" ]] && NODE_ID="$(unit_env NODE_ID)"
[[ -z "${NODE_ID}" ]] && NODE_ID="$(file_env NODE_ID)"
[[ -n "${NODE_ID}" ]] || die "cannot determine node code; pass --node-id"

[[ -z "${BACKEND}" ]] && BACKEND="$(conf_env CENTRAL_API_URL)"
[[ -z "${BACKEND}" ]] && BACKEND="$(unit_env CENTRAL_API_URL)"
[[ -z "${BACKEND}" ]] && BACKEND="$(file_env CENTRAL_API_URL)"
[[ -n "${BACKEND}" ]] || die "cannot determine backend URL; pass --backend"

# Preserve the existing enable state unless the caller overrides it.
if [[ -z "${ENABLE}" ]]; then
  ENABLE="$(conf_env SMART_PLUGS_ENABLED)"
  ENABLE="${ENABLE:-0}"
  [[ "${INSTALLED}" != "none" ]] && say "  (preserving SMART_PLUGS_ENABLED=${ENABLE})"
fi

BUFFER="$(conf_env SMART_PLUG_BUFFER)"
if [[ -z "${BUFFER}" ]]; then
  RW_PATHS="$(systemctl show "${UNIT}" -p ReadWritePaths --value || true)"
  BUFFER_DIR="${APP_DIR}"
  for base in ${RW_PATHS}; do
    [[ -d "${base}" ]] && { BUFFER_DIR="${base}/state"; break; }
  done
  BUFFER="${BUFFER_DIR}/smart_plugs.db"
fi
BUFFER_DIR="$(dirname "${BUFFER}")"

say "  unit             : ${UNIT} (${WAS_ACTIVE})"
say "  collector        : ${COLLECTOR}"
say "  python           : ${PYTHON}"
say "  service user     : ${SVC_USER}"
say "  node id          : ${NODE_ID}"
say "  backend          : ${BACKEND}"
say "  plug buffer      : ${BUFFER}"

# -------------------------------------------------------------- 2. versions
step "2. Version comparison"
say "  installed version: ${INSTALLED}"
say "  available version: ${AVAILABLE}"

if [[ "${INSTALLED}" == "${AVAILABLE}" ]]; then
  say "  -> already at the available version; re-running to verify and reconcile config"
elif [[ "${INSTALLED}" == "none" ]]; then
  say "  -> fresh installation"
else
  say "  -> upgrade ${INSTALLED} to ${AVAILABLE}"
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  say ""
  say "Dry run: nothing was modified."
  exit 0
fi

# ------------------------------------------------------------ 3. compatibility
step "3. Verify compatibility"
"${PYTHON}" - "$COLLECTOR" <<'PYEOF' || die "collector is not compatible; nothing was changed"
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
ok = True
for pattern, label in ((r"^import os$", "import os"),
                       (r"^log\s*=", "module-level logger"),
                       (r"^def main\(\)", "def main()"),
                       (r"polling_loop\(", "polling_loop() call")):
    hit = re.search(pattern, src, re.MULTILINE) is not None
    print(f"  [{'OK' if hit else 'FAIL'}] {label}")
    ok &= hit
sys.exit(0 if ok else 1)
PYEOF
"${PYTHON}" -c 'import sqlite3,json,threading,urllib.request,concurrent.futures' \
  || die "python runtime lacks a required stdlib module"
say "  [OK] python runtime"

# ---------------------------------------------------------------- 4. backup
step "4. Timestamped backup"
BACKUP="${NODE_ROOT}/backups/smart-plugs-${TS}"
sudo mkdir -p "${BACKUP}"
sudo cp -a "${COLLECTOR}" "${BACKUP}/$(basename "${COLLECTOR}")"
[[ -f "${APP_DIR}/smart_plug_source.py" ]] && sudo cp -a "${APP_DIR}/smart_plug_source.py" "${BACKUP}/"
[[ -f "${CONF}" ]] && sudo cp -a "${CONF}" "${BACKUP}/smart-plugs.conf"
[[ -n "${ENVFILE}" && -r "${ENVFILE}" ]] && sudo cp -a "${ENVFILE}" "${BACKUP}/" || true
systemctl cat "${UNIT}" | sudo tee "${BACKUP}/${UNIT}.txt" >/dev/null
say "  ${BACKUP}"
sudo ls -1 "${BACKUP}" | sed 's/^/    /'

# ------------------------------------------------- 5. install changed files
step "5. Install (changed files only)"
install_if_changed() {
  local src="$1" dest="$2" mode="$3"
  if [[ -f "${dest}" ]] && cmp -s "${src}" "${dest}"; then
    say "  [SAME] $(basename "${dest}")"
    return 1
  fi
  sudo install -m "${mode}" "${src}" "${dest}"
  say "  [NEW ] ${dest}"
  CHANGED_FILES+=("${dest}")
  return 0
}

if install_if_changed "${SRC_DIR}/smart_plug_source.py" "${APP_DIR}/smart_plug_source.py" 644; then
  sudo chown "${SVC_USER}:${SVC_USER}" "${APP_DIR}/smart_plug_source.py"
  RESTART_REQUIRED="1"
fi

sudo install -d -m 755 "${NODE_ROOT}/docs"
install_if_changed "${SRC_DIR}/README-smart-plugs.md" "${NODE_ROOT}/docs/README-smart-plugs.md" 644 || true
install_if_changed "${SRC_DIR}/CHANGELOG.md" "${NODE_ROOT}/docs/CHANGELOG.md" 644 || true
install_if_changed "${SRC_DIR}/smart-plug-health" "/usr/local/bin/smart-plug-health" 755 || true

sudo install -d -o "${SVC_USER}" -g "${SVC_USER}" -m 755 "${BUFFER_DIR}"

# ------------------------------------------------------------- 6. integrate
step "6. Integrate into the collector"
BEFORE_HASH="$(sudo sha256sum "${COLLECTOR}" | cut -d' ' -f1)"
sudo "${PYTHON}" "${SRC_DIR}/integrate_collector.py" "${COLLECTOR}"
AFTER_HASH="$(sudo sha256sum "${COLLECTOR}" | cut -d' ' -f1)"
if [[ "${BEFORE_HASH}" != "${AFTER_HASH}" ]]; then
  CHANGED_FILES+=("${COLLECTOR}")
  RESTART_REQUIRED="1"
fi
sudo "${PYTHON}" -m py_compile "${COLLECTOR}" && say "  [OK] collector compiles"

# ------------------------------------------------------------- 7. configure
step "7. Configure (preserving existing settings)"
NEW_CONF="$(mktemp)"
cat > "${NEW_CONF}" <<EOF
# Smart Plug collection source — ${AVAILABLE}, written ${TS}
# Read by the collector; the environment overrides any value set here.
#
# Only ONE node per subnet should be enabled. The backend enforces plug
# ownership, so a second node's reports are rejected rather than accepted.
SMART_PLUGS_ENABLED=${ENABLE}
NODE_ID=${NODE_ID}
CENTRAL_API_URL=${BACKEND}
SMART_PLUG_BUFFER=${BUFFER}
EOF

sudo install -d -m 755 "${CONF_DIR}"

# Compare the settings only, not the header: it carries a timestamp, so a
# byte comparison would rewrite the file — and restart the collector — on
# every run, which would defeat idempotency.
settings_only() { grep -vE '^[[:space:]]*(#|$)' "$1" | sort; }

if [[ -f "${CONF}" ]] && diff -q <(settings_only "${NEW_CONF}") <(settings_only "${CONF}") >/dev/null 2>&1; then
  say "  [SAME] ${CONF}"
else
  sudo install -m 644 "${NEW_CONF}" "${CONF}"
  say "  [NEW ] ${CONF}"
  CHANGED_FILES+=("${CONF}")
  RESTART_REQUIRED="1"
fi
rm -f "${NEW_CONF}"
sed 's/^/    /' "${CONF}"

# --------------------------------------------------- 8. restart only if needed
step "8. Restart"
if [[ "${RESTART_REQUIRED}" == "0" ]]; then
  say "  [SKIP] nothing changed; collector left running undisturbed"
elif [[ "${WAS_ACTIVE}" == "active" ]]; then
  sudo systemctl restart "${UNIT}"
  sleep 6
  systemctl is-active --quiet "${UNIT}" || die "collector did not come back up — restore from ${BACKUP}"
  say "  [OK] ${UNIT} restarted (pid $(systemctl show -p MainPID --value "${UNIT}"))"
else
  say "  [SKIP] unit was ${WAS_ACTIVE} before install; not starting it"
fi

# ---------------------------------------------------------------- 9. verify
step "9. Verify"
sleep 4
VERIFY_STATUS="unknown"
if journalctl -u "${UNIT}" --since "-3 min" --no-pager 2>/dev/null | grep -q "Smart Plug source started"; then
  VERIFY_STATUS="running"; say "  [OK] plug source started"
elif journalctl -u "${UNIT}" --since "-3 min" --no-pager 2>/dev/null | grep -q "Smart Plug source disabled"; then
  VERIFY_STATUS="disabled"; say "  [OK] installed but disabled"
elif [[ "${RESTART_REQUIRED}" == "0" ]]; then
  VERIFY_STATUS="unchanged"; say "  [OK] unchanged, collector still running"
else
  say "  [WARN] no plug source line in the journal yet"
fi

INSTALLED_NOW="$("${PYTHON}" -c "
import re;print(re.search(r'__version__\s*=\s*[\"\']([^\"\']+)',open('${APP_DIR}/smart_plug_source.py',encoding='utf-8').read()).group(1))" 2>/dev/null || echo unknown)"
say "  version on node  : ${INSTALLED_NOW}"

STORED="$(journalctl -u "${UNIT}" --since '-2 min' --no-pager 2>/dev/null | grep -ciE 'stored|batch' || true)"
ERRORS="$(journalctl -u "${UNIT}" --since '-2 min' --no-pager 2>/dev/null | grep -ciE 'error|traceback' || true)"
say "  energy node activity (2 min): ${STORED}"
say "  errors (2 min)              : ${ERRORS}"

# -------------------------------------------------------------- 10. report
step "10. Deployment report"
mkdir -p "${REPORT_DIR}"
REPORT="${REPORT_DIR}/$(hostname)-${TS}.md"
{
  echo "# Deployment report — $(hostname)"
  echo
  echo "| Field | Value |"
  echo "|---|---|"
  echo "| Timestamp | ${TS} |"
  echo "| Hostname | $(hostname) |"
  echo "| Node ID | ${NODE_ID} |"
  echo "| Smart Plug version (before) | ${INSTALLED} |"
  echo "| Smart Plug version (after) | ${INSTALLED_NOW} |"
  echo "| Available version | ${AVAILABLE} |"
  echo "| Collector | ${COLLECTOR} |"
  echo "| Collector unit | ${UNIT} |"
  echo "| Service status | $(systemctl is-active "${UNIT}" 2>/dev/null || echo unknown) |"
  echo "| Plug source enabled | ${ENABLE} |"
  echo "| Backend | ${BACKEND} |"
  echo "| Buffer | ${BUFFER} |"
  echo "| Backup location | ${BACKUP} |"
  echo "| Restart required | ${RESTART_REQUIRED} |"
  echo
  echo "## Files modified"
  echo
  if [[ ${#CHANGED_FILES[@]} -eq 0 ]]; then
    echo "None — already up to date."
  else
    for f in "${CHANGED_FILES[@]}"; do echo "- \`${f}\`"; done
  fi
  echo
  echo "## Checksums"
  echo
  echo '```'
  sudo sha256sum "${APP_DIR}/smart_plug_source.py" "${COLLECTOR}" 2>/dev/null
  echo '```'
  echo
  echo "## Test results"
  echo
  echo "| Check | Result |"
  echo "|---|---|"
  echo "| Collector compiles | OK |"
  echo "| Service active | $(systemctl is-active "${UNIT}" 2>/dev/null || echo unknown) |"
  echo "| Plug source | ${VERIFY_STATUS} |"
  echo "| Energy Node activity (2 min) | ${STORED} |"
  echo "| Errors (2 min) | ${ERRORS} |"
  echo
  echo "## Health"
  echo
  echo '```'
  smart-plug-health 2>&1 || echo "(health check unavailable)"
  echo '```'
} > "${REPORT}"

say "  ${REPORT}"

say ""
say "Done. node=${NODE_ID} version=${INSTALLED_NOW} enabled=${ENABLE} restarted=${RESTART_REQUIRED}"
say "Report: ${REPORT}"
