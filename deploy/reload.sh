#!/usr/bin/env bash
# Reload PREDATOR services after code changes — run this after every commit.
# macOS (launchd):
set -e
OS="$(uname)"
if [ "$OS" = "Darwin" ]; then
  for svc in scheduler sentinel dashboard; do
    launchctl kickstart -k "gui/$(id -u)/com.predator.$svc" && echo "restarted $svc"
  done
else
  # Linux (systemd) VPS:
  for svc in predator-scheduler predator-sentinel predator-dashboard; do
    sudo systemctl restart "$svc" && echo "restarted $svc"
  done
fi
echo "all services running fresh code."
