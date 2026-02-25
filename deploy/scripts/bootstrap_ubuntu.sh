#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER="${APP_USER:-webapp}"
APP_GROUP="${APP_GROUP:-www-data}"
APP_ROOT="${APP_ROOT:-/srv/onlinedrawinggame}"
APP_DIR="${APP_DIR:-$APP_ROOT/app}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/venv}"
BRANCH="${1:-main}"
REPO_URL="${2:-}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/scripts/bootstrap_ubuntu.sh <branch> <repo_url>"
  exit 1
fi

if [[ -z "$REPO_URL" ]]; then
  echo "Missing repo URL."
  echo "Example:"
  echo "sudo bash deploy/scripts/bootstrap_ubuntu.sh main git@github.com:YOUR_USER/YOUR_REPO.git"
  exit 1
fi

run_as_app() {
  runuser -u "$APP_USER" -- bash -lc "$*"
}

echo "[1/8] Installing OS packages..."
apt-get update
apt-get install -y \
  git curl ca-certificates gnupg lsb-release build-essential \
  python3 python3-venv python3-pip \
  nginx redis-server postgresql postgresql-contrib \
  certbot python3-certbot-nginx

if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | sed 's/^v//' | cut -d. -f1)" -lt 20 ]]; then
  echo "[2/8] Installing Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "[3/8] Creating app user/directories..."
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /bin/bash "$APP_USER"
fi
usermod -a -G "$APP_GROUP" "$APP_USER" || true

mkdir -p "$APP_ROOT" /etc/onlinedrawinggame /var/www/certbot
chown -R "$APP_USER:$APP_GROUP" "$APP_ROOT"
chmod 755 /var/www/certbot

echo "[4/8] Cloning/updating repository..."
if [[ ! -d "$APP_DIR/.git" ]]; then
  run_as_app "git clone --branch '$BRANCH' '$REPO_URL' '$APP_DIR'"
else
  run_as_app "git -C '$APP_DIR' fetch --all --prune"
  run_as_app "git -C '$APP_DIR' checkout '$BRANCH'"
  run_as_app "git -C '$APP_DIR' pull --ff-only origin '$BRANCH'"
fi

echo "[5/8] Preparing Python environment..."
run_as_app "python3 -m venv '$VENV_DIR'"
run_as_app "'$VENV_DIR/bin/pip' install --upgrade pip wheel"
run_as_app "'$VENV_DIR/bin/pip' install -r '$APP_DIR/backend/requirements.txt'"

echo "[6/8] Installing frontend dependencies..."
run_as_app "cd '$APP_DIR/frontend' && npm ci"

echo "[7/8] Installing systemd/nginx templates..."
install -m 0644 "$APP_DIR/deploy/systemd/onlinedrawinggame-backend.service" /etc/systemd/system/onlinedrawinggame-backend.service
install -m 0644 "$APP_DIR/deploy/systemd/onlinedrawinggame-frontend.service" /etc/systemd/system/onlinedrawinggame-frontend.service
install -m 0644 "$APP_DIR/deploy/nginx/onlinedrawinggame.online.conf" /etc/nginx/sites-available/onlinedrawinggame.online.conf
ln -sf /etc/nginx/sites-available/onlinedrawinggame.online.conf /etc/nginx/sites-enabled/onlinedrawinggame.online.conf
rm -f /etc/nginx/sites-enabled/default

if [[ ! -f /etc/onlinedrawinggame/backend.env ]]; then
  cp "$APP_DIR/deploy/env/backend.env.production.example" /etc/onlinedrawinggame/backend.env
fi
if [[ ! -f /etc/onlinedrawinggame/frontend.env ]]; then
  cp "$APP_DIR/deploy/env/frontend.env.production.example" /etc/onlinedrawinggame/frontend.env
fi
chown root:"$APP_GROUP" /etc/onlinedrawinggame/backend.env /etc/onlinedrawinggame/frontend.env
chmod 640 /etc/onlinedrawinggame/backend.env /etc/onlinedrawinggame/frontend.env

echo "[8/8] Enabling base services..."
systemctl daemon-reload
systemctl enable redis-server nginx
nginx -t
systemctl restart nginx

echo
echo "Bootstrap complete."
echo "Next steps:"
echo "1) Edit /etc/onlinedrawinggame/backend.env and /etc/onlinedrawinggame/frontend.env"
echo "2) Create PostgreSQL DB/user (if not already done)"
echo "3) Run: sudo bash $APP_DIR/deploy/scripts/deploy_pull.sh $BRANCH"
echo "4) Run TLS: sudo bash $APP_DIR/deploy/scripts/setup_certbot.sh your-email@example.com"
