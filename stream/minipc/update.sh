#!/bin/bash
# Pull the latest relay scripts from GitHub and restart what changed.  Usage:  sudo bash update.sh
set -u
REPO_RAW="https://raw.githubusercontent.com/btsubjectdata/pachamama-valley-farms/main/stream/minipc"
D=/opt/pvf-stream
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
for f in restream.sh hls.sh serve.py watchdog.py; do
  curl -fsSL "$REPO_RAW/$f?$(date +%s)" -o "/tmp/$f" || { echo "download failed: $f"; continue; }
  if ! cmp -s "/tmp/$f" "$D/$f"; then install -m 755 -o pvf -g pvf "/tmp/$f" "$D/$f"; echo "updated $f"; CHANGED="${CHANGED:-} $f"; fi
  rm -f "/tmp/$f"
done
case "${CHANGED:-}" in *hls.sh*) systemctl restart pvf-hls;; esac
case "${CHANGED:-}" in *serve.py*) systemctl restart pvf-hlsserve;; esac
case "${CHANGED:-}" in *restream.sh*) systemctl restart pvf-restream;; esac
case "${CHANGED:-}" in *watchdog.py*) systemctl restart pvf-watchdog;; esac
sleep 15
for s in pvf-restream pvf-hls pvf-hlsserve pvf-tunnel pvf-watchdog; do printf "%-14s %s\n" "$s" "$(systemctl is-active $s)"; done
echo; echo "== website feed"; curl -s http://127.0.0.1:8088/bees.m3u8 | grep -E "RESOLUTION|m3u8" || echo "(no master playlist yet)"
echo; echo "== hls log";      tail -4 $D/logs/pvf-hls.log
echo; echo "== watchdog log"; tail -12 $D/logs/pvf-watchdog.log
echo; echo "== status"; curl -s http://127.0.0.1:8088/status.json; echo
