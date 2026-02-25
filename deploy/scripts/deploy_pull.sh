#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER="${APP_USER:-webapp}"
APP_GROUP="${APP_GROUP:-www-data}"
APP_ROOT="${APP_ROOT:-/srv/onlinedrawinggame}"
APP_DIR="${APP_DIR:-$APP_ROOT/app}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/venv}"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"
BRANCH="${1:-main}"
SYNC_NGINX_TEMPLATE="${SYNC_NGINX_TEMPLATE:-false}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/scripts/deploy_pull.sh <branch>"
  exit 1
fi

run_as_app() {
  runuser -u "$APP_USER" -- bash -lc "$*"
}

for required_path in \
  "$APP_DIR/.git" \
  "$VENV_DIR/bin/python" \
  "/etc/onlinedrawinggame/backend.env" \
  "/etc/onlinedrawinggame/frontend.env"
do
  if [[ ! -e "$required_path" ]]; then
    echo "Missing required path: $required_path"
    exit 1
  fi
done

echo "[1/7] Pulling latest code from GitHub..."
run_as_app "git -C '$APP_DIR' fetch --all --prune"
run_as_app "git -C '$APP_DIR' checkout '$BRANCH'"
run_as_app "git -C '$APP_DIR' pull --ff-only origin '$BRANCH'"

echo "[2/7] Installing/updating backend dependencies..."
run_as_app "'$VENV_DIR/bin/pip' install --upgrade pip wheel"
run_as_app "'$VENV_DIR/bin/pip' install -r '$BACKEND_DIR/requirements.txt'"

echo "[3/7] Applying backend migrations/static build..."
run_as_app "ln -sfn /etc/onlinedrawinggame/backend.env '$BACKEND_DIR/.env'"
run_as_app "cd '$BACKEND_DIR' && '$VENV_DIR/bin/python' manage.py migrate --noinput"
run_as_app "cd '$BACKEND_DIR' && '$VENV_DIR/bin/python' manage.py collectstatic --noinput"

echo "[4/7] Installing/updating frontend dependencies..."
run_as_app "cd '$FRONTEND_DIR' && npm ci"

echo "[5/7] Building frontend production bundle..."
run_as_app "ln -sfn /etc/onlinedrawinggame/frontend.env '$FRONTEND_DIR/.env.production.local'"
run_as_app "cd '$FRONTEND_DIR' && npm run build"

echo "[6/7] Syncing latest service templates..."
install -m 0644 "$APP_DIR/deploy/systemd/onlinedrawinggame-backend.service" /etc/systemd/system/onlinedrawinggame-backend.service
install -m 0644 "$APP_DIR/deploy/systemd/onlinedrawinggame-frontend.service" /etc/systemd/system/onlinedrawinggame-frontend.service

NGINX_SITE="/etc/nginx/sites-available/onlinedrawinggame.online.conf"
if [[ "$SYNC_NGINX_TEMPLATE" == "true" || ! -f "$NGINX_SITE" ]]; then
  install -m 0644 "$APP_DIR/deploy/nginx/onlinedrawinggame.online.conf" "$NGINX_SITE"
  ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/onlinedrawinggame.online.conf
  echo "Nginx template synced from repository."
else
  echo "Skipping nginx template sync to preserve existing server TLS/certbot config."
fi

echo "[7/7] Restarting services..."
systemctl daemon-reload
nginx -t
systemctl restart onlinedrawinggame-backend.service
systemctl restart onlinedrawinggame-frontend.service
systemctl reload nginx
systemctl enable onlinedrawinggame-backend.service onlinedrawinggame-frontend.service nginx redis-server

echo
echo "Deploy complete."
systemctl --no-pager --full status onlinedrawinggame-backend.service | sed -n '1,12p'
systemctl --no-pager --full status onlinedrawinggame-frontend.service | sed -n '1,12p'
