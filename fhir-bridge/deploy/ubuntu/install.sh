#!/usr/bin/env bash
# Install or update the FHIR EHR Bridge as a systemd service on Ubuntu.
# Run from the repository root as root:  sudo deploy/ubuntu/install.sh
# Idempotent: re-run after pulling a new version. Does not touch /etc/fhir-bridge/.env if it exists.
set -euo pipefail

APP_DIR=/opt/fhir-bridge
CONF_DIR=/etc/fhir-bridge
LOG_DIR=/var/log/fhir-bridge
SVC_USER=fhir-bridge
SRC_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

command -v python3 >/dev/null || { echo "python3 is required (apt install python3 python3-venv)"; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'

id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"

mkdir -p "$APP_DIR" "$CONF_DIR" "$LOG_DIR"
# Copy the application (not .env, keys, venv, logs or tests).
rsync -a --delete \
  --exclude '.env' --exclude '.venv' --exclude 'logs' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.ruff_cache' --exclude 'backend/keys' --exclude '.git' \
  "$SRC_DIR/backend" "$SRC_DIR/frontend" "$APP_DIR/"

cd "$APP_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

if [ ! -f "$CONF_DIR/.env" ]; then
  cp "$SRC_DIR/backend/.env.example" "$CONF_DIR/.env"
  echo "Created $CONF_DIR/.env from the template. EDIT IT before starting the service."
fi
chown root:"$SVC_USER" "$CONF_DIR/.env"; chmod 640 "$CONF_DIR/.env"
# EnvironmentFile overrides the unit's Environment= lines, so these must not be set in .env.
if grep -Eq '^(APP_ENV|LOG_DIR|LOG_TO_CONSOLE)=' "$CONF_DIR/.env"; then
  echo "Remove APP_ENV, LOG_DIR and LOG_TO_CONSOLE from $CONF_DIR/.env; the service unit sets them."; exit 1
fi
chown -R root:"$SVC_USER" "$APP_DIR"; chmod -R o-rwx "$APP_DIR"
chown "$SVC_USER":"$SVC_USER" "$LOG_DIR"; chmod 750 "$LOG_DIR"
# Private signing key(s) live here, readable only by the service user.
mkdir -p "$CONF_DIR/keys"; chown root:"$SVC_USER" "$CONF_DIR/keys"; chmod 750 "$CONF_DIR/keys"
find "$CONF_DIR/keys" -type f -exec chown root:"$SVC_USER" {} \; -exec chmod 640 {} \;

cp "$SRC_DIR/deploy/ubuntu/fhir-bridge.service" /etc/systemd/system/fhir-bridge.service
systemctl daemon-reload
systemctl enable fhir-bridge >/dev/null

echo "Validating configuration..."
if sudo -u "$SVC_USER" env APP_ENV=production \
     .venv/bin/python tools/live_check.py --stage config --env-file "$CONF_DIR/.env"; then
  systemctl restart fhir-bridge
  sleep 2
  systemctl --no-pager --lines=5 status fhir-bridge || true
  curl -fsS http://127.0.0.1:8000/api/health && echo
else
  echo "Configuration invalid; service not (re)started. Fix $CONF_DIR/.env and re-run."
  exit 1
fi
