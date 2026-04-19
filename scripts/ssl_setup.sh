#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-srv1575227.hstgr.cloud}"
EMAIL="${2:-admin@${DOMAIN}}"
APP_DIR="/home/omni-outreach"
CERT_DIR="${APP_DIR}/certs"
WEBROOT_DIR="${APP_DIR}/certbot/www"

mkdir -p "${CERT_DIR}" "${WEBROOT_DIR}"

apt-get update -qq
apt-get install -y -qq certbot

# Ensure frontend serves ACME challenge path.
cd "${APP_DIR}"
docker compose up -d frontend

certbot certonly \
  --webroot \
  -w "${WEBROOT_DIR}" \
  -d "${DOMAIN}" \
  --email "${EMAIL}" \
  --agree-tos \
  --no-eff-email \
  --non-interactive

cp "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" "${CERT_DIR}/fullchain.pem"
cp "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" "${CERT_DIR}/privkey.pem"
chmod 600 "${CERT_DIR}/privkey.pem"

# Recreate frontend to load certs and HTTPS listener.
docker compose up -d --build frontend

# Auto-renew and copy certificates into compose-mounted cert directory.
cat >/usr/local/bin/omni-cert-renew.sh <<'RENEW'
#!/usr/bin/env bash
set -euo pipefail
DOMAIN="srv1575227.hstgr.cloud"
APP_DIR="/home/omni-outreach"
CERT_DIR="${APP_DIR}/certs"
certbot renew --quiet
cp "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" "${CERT_DIR}/fullchain.pem"
cp "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" "${CERT_DIR}/privkey.pem"
chmod 600 "${CERT_DIR}/privkey.pem"
cd "${APP_DIR}"
docker compose restart frontend
RENEW
chmod +x /usr/local/bin/omni-cert-renew.sh

( crontab -l 2>/dev/null | grep -v omni-cert-renew.sh; echo "0 4 * * * /usr/local/bin/omni-cert-renew.sh" ) | crontab -

echo "TLS setup complete for ${DOMAIN}"