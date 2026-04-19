#!/usr/bin/env bash
# SSL/HTTPS setup for Omni Outreach VPS
# Usage: DOMAIN=your.domain.com EMAIL=you@email.com bash scripts/ssl-setup.sh
set -euo pipefail

DOMAIN="${DOMAIN:?Set DOMAIN env var (e.g. outreach.example.com)}"
EMAIL="${EMAIL:?Set EMAIL env var for Let's Encrypt notifications}"
COMPOSE_DIR="/home/omni-outreach"

echo "==> Installing certbot..."
apt-get update -qq && apt-get install -y -qq certbot

echo "==> Stopping frontend to free port 80..."
cd "$COMPOSE_DIR"
docker compose stop frontend

echo "==> Obtaining certificate for $DOMAIN..."
certbot certonly --standalone -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive

echo "==> Copying certs into place..."
mkdir -p "$COMPOSE_DIR/certs"
cp /etc/letsencrypt/live/"$DOMAIN"/fullchain.pem "$COMPOSE_DIR/certs/"
cp /etc/letsencrypt/live/"$DOMAIN"/privkey.pem "$COMPOSE_DIR/certs/"

echo "==> Setting DOMAIN=$DOMAIN in .env..."
grep -q '^DOMAIN=' "$COMPOSE_DIR/.env" && \
    sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" "$COMPOSE_DIR/.env" || \
    echo "DOMAIN=$DOMAIN" >> "$COMPOSE_DIR/.env"

echo "==> Starting services with SSL..."
docker compose up -d

echo "==> Setting up auto-renewal cron..."
cat > /etc/cron.d/certbot-renew << EOF
0 3 * * * root certbot renew --pre-hook "cd $COMPOSE_DIR && docker compose stop frontend" --post-hook "cd $COMPOSE_DIR && cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem $COMPOSE_DIR/certs/ && cp /etc/letsencrypt/live/$DOMAIN/privkey.pem $COMPOSE_DIR/certs/ && cd $COMPOSE_DIR && docker compose up -d frontend" >> /var/log/certbot-renew.log 2>&1
EOF

echo "==> Done! HTTPS active at https://$DOMAIN"
