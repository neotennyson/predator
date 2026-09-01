# DEPLOY — making PREDATOR autonomous (no Mac dependency)

Target: any Ubuntu 22.04/24.04 VPS (Hetzner CX22 ~€4, DigitalOcean $6, Vultr $6, or Oracle Cloud free tier). 1 vCPU / 1GB RAM is plenty.

## 1. One-command setup (on the VPS, as root)

```bash
git clone https://github.com/neotennyson/predator.git /opt/predator
bash /opt/predator/deploy/setup.sh
```

(Private repo: run `gh auth login` first, or clone with an HTTPS Personal Access Token.)

This installs deps, sets IST timezone, and installs 3 systemd services:
- `predator-scheduler` — autopilot (08:30 Telegram brief → 09:07 auto-arm → 15:25 kill)
- `predator-sentinel` — 24/7 news watcher
- `predator-dashboard` — UI on 127.0.0.1:8787

All three auto-restart on crash and auto-start on reboot. Check anytime: `systemctl status predator-*`.

## 2. Expose the dashboard via Cloudflare Tunnel

```bash
apt install -y cloudflared   # (add cloudflare's apt repo first — see cloudflare docs)
cloudflared tunnel login
cloudflared tunnel create predator
cloudflared tunnel route dns predator predator.<yourdomain>.com
cat > /etc/cloudflared/config.yml <<EOF
tunnel: predator
credentials-file: /root/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: predator.<yourdomain>.com
    service: http://localhost:8787
  - service: http_status:404
EOF
cloudflared service install
systemctl enable --now cloudflared
```

## 3. Bootstrap the keys (once)

Open `https://predator.<yourdomain>.com` → **Comms & keys**:
1. Dhan client ID + that day's access token
2. Telegram bot token + chat ID (from @BotFather + getUpdates)
3. **Set a dashboard key** — POST via curl or add to secrets:
   `curl -X POST https://predator.<yourdomain>.com/api/secrets -H "Content-Type: application/json" -d '{"dashboard_key":"<long-random-string>"}'`
   The UI will then prompt for this key on every START/ABORT/SAVE (stored in browser localStorage).

## 4. Verify the loop

```bash
systemctl status predator-*          # 3 services active
tail -f /opt/predator/results/engine_live.log   # engine thoughts during hunts
curl localhost:8787/api/status       # JSON heartbeat
```
Telegram should have received: autopilot-online + sentinel-online + nightly heartbeat (20:00 IST).

## Notes
- `secrets.json` lives on the VPS only (gitignored) — never committed.
- VPS file writes: all state in `/opt/predator/results/` + `cache/`.
- Backups: `tar czf predator-backup.tar.gz /opt/predator/results /opt/predator/secrets.json` occasionally.
- The Mac can now sleep. The wolf lives in the cloud.
