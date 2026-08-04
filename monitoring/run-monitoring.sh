#!/usr/bin/env bash
#
# Start the monitoring scheduler, guaranteeing a single instance.
#
# The supported way to run this is the systemd unit beside this script
# (energy-platform-monitoring.service), which needs root to install. This
# wrapper exists so monitoring can run *now*, and survive reboots via the
# user's own crontab, without waiting for a root shell.
#
# flock holds an exclusive lock for the lifetime of the process, so a second
# invocation — from cron @reboot, from a manual run, or from an overlapping
# retry — exits immediately instead of producing two schedulers that would each
# evaluate every rule and send duplicate alerts.
#
# Usage:
#   ./run-monitoring.sh            # run in the foreground
#   nohup ./run-monitoring.sh &    # run detached
#   crontab: @reboot /home/manager/energy-platform/monitoring/run-monitoring.sh
set -euo pipefail

BACKEND_DIR=/home/manager/energy-platform/backend
LOCK_FILE=/tmp/energy-platform-monitoring.lock
LOG_FILE=/home/manager/energy-platform/monitoring/monitoring.log

cd "$BACKEND_DIR"

exec /usr/bin/flock -n "$LOCK_FILE" \
    "$BACKEND_DIR/venv/bin/python3" -m app.monitoring.scheduler \
    >> "$LOG_FILE" 2>&1
