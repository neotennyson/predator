#!/usr/bin/env bash
set -euo pipefail

# PREDATOR one-command server setup — run on a fresh Ubuntu 22.04/24.04 box as root:
#   bash <(curl -s <raw-url-of-this-file>)   OR:  git clone repo && bash deploy/setup.sh

REPO="https://github.com/neotennyson/predator.git"
DEST="/opt/predator"

if [ ! -d "$DEST" ]; then
  echo "== clone the repo (private: paste a GitHub Personal Access Token when asked, or use gh auth) =="
  git clone "$REPO" "$DEST"
fi

cd "$DEST"

echo "== python venv + deps =="
apt-get update -qq && apt-get install -y -qq python3-venv python3-pip git >/dev/null
python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt fastapi "uvicorn[standard]" pydantic requests

echo "== timezone =="
timedatectl set-timezone Asia/Kolkata || true

echo "== systemd services =="
cp deploy/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now predator-scheduler predator-sentinel predator-dashboard

echo
echo "== STATUS =="
systemctl --no-pager --lines=0 status predator-scheduler predator-sentinel predator-dashboard | grep -E "●|Active"
echo
echo "PREDATOR is live on this machine."
echo "Next: expose the dashboard via Cloudflare Tunnel and paste your keys at the dashboard (Comms & keys)."
echo "  cloudflared tunnel create predator && cloudflared tunnel route dns predator predator.<yourdomain>"
echo "See DEPLOY.md for the tunnel config + key-lock checklist."
