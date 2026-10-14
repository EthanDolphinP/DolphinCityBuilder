#!/usr/bin/env bash
# Sets up Dolphin City Builder on a fresh Ubuntu server (22.04 or 24.04), as root:
#
#     curl -fsSL https://raw.githubusercontent.com/EthanDolphinP/DolphinCityBuilder/main/deploy/setup.sh -o setup.sh
#     sudo bash setup.sh play.example.com
#
# where play.example.com is a domain (or subdomain) already pointing at this
# server. It installs Python and Caddy (which gets and renews the HTTPS
# certificate by itself), runs the game as a service that restarts if it ever
# stops, keeps the game's data in /var/lib/dolphincity, backs it up every
# night, and adds the "dolphincity" command for looking after it.
# Running it again is safe: it updates what is there.
set -euo pipefail

DOMAIN="${1:-}"
REPO="${REPO:-https://github.com/EthanDolphinP/DolphinCityBuilder.git}"
CODE=/opt/dolphincity
DATA=/var/lib/dolphincity
BACKUPS=/var/backups/dolphincity

if [[ $EUID -ne 0 ]]; then echo "Run this as root: sudo bash setup.sh your.domain"; exit 1; fi
if [[ -z "$DOMAIN" ]]; then echo "Usage: sudo bash setup.sh your.domain"; exit 1; fi

echo "== Installing Python, git and Caddy"
apt-get update -q
apt-get install -y -q python3 git curl debian-keyring debian-archive-keyring apt-transport-https ufw
if ! command -v caddy >/dev/null; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

echo "== The game's own user, code and data"
id dolphin >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin dolphin
if [[ -d "$CODE/.git" ]]; then git -C "$CODE" pull --ff-only; else git clone "$REPO" "$CODE"; fi
mkdir -p "$DATA/saves" "$BACKUPS"
chown -R dolphin:dolphin "$DATA"
chmod 750 "$DATA" "$BACKUPS"

echo "== The game as a service"
install -m 644 "$CODE/deploy/dolphincity.service" /etc/systemd/system/dolphincity.service
systemctl daemon-reload
systemctl enable --now dolphincity
systemctl restart dolphincity

echo "== HTTPS with Caddy"
sed "s/{\$DOMAIN}/$DOMAIN/" "$CODE/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "== Firewall: SSH and the web only"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== Nightly backups and the dolphincity command"
install -m 755 "$CODE/deploy/dolphincity" /usr/local/bin/dolphincity
echo "17 4 * * * root /usr/local/bin/dolphincity backup >/dev/null" > /etc/cron.d/dolphincity
chmod 644 /etc/cron.d/dolphincity

echo
echo "Done. The game should be at https://$DOMAIN in a minute or two (Caddy is getting its certificate)."
echo "Type 'dolphincity' to see what you can do from here."
