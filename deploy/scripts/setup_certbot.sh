#!/usr/bin/env bash
set -Eeuo pipefail

PRIMARY_DOMAIN="${PRIMARY_DOMAIN:-onlinedrawinggame.online}"
SECONDARY_DOMAIN="${SECONDARY_DOMAIN:-www.onlinedrawinggame.online}"
EMAIL="${1:-}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/scripts/setup_certbot.sh your-email@example.com"
  exit 1
fi

if [[ -z "$EMAIL" ]]; then
  echo "Email is required."
  echo "Usage: sudo bash deploy/scripts/setup_certbot.sh your-email@example.com"
  exit 1
fi

mkdir -p /var/www/certbot
chown -R root:root /var/www/certbot

certbot --nginx \
  -d "$PRIMARY_DOMAIN" \
  -d "$SECONDARY_DOMAIN" \
  --redirect \
  --agree-tos \
  --email "$EMAIL" \
  --non-interactive

nginx -t
systemctl reload nginx

echo "TLS certificate issued and nginx reloaded."
