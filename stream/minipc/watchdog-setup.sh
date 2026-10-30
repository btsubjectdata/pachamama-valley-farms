#!/bin/bash
# Installs the YouTube watchdog on the mini PC.  Usage:  sudo bash watchdog-setup.sh
# Needs /opt/pvf-stream/youtube-client.json (Google OAuth client: client_id + client_secret).
set -euo pipefail
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/btsubjectdata/pachamama-valley-farms/main/stream/minipc}"
D=/opt/pvf-stream
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
[ -f "$D/youtube-client.json" ] || { echo "Missing $D/youtube-client.json"; exit 1; }
chmod 600 "$D/youtube-client.json"
curl -fsSL "$REPO_RAW/watchdog.py" -o "$D/watchdog.py"
curl -fsSL "$REPO_RAW/serve.py" -o "$D/serve.py"
chmod 755 "$D/watchdog.py" "$D/serve.py"
cat > /usr/local/sbin/pvf-watchdog <<'W'
#!/bin/bash
exec /usr/bin/python3 /opt/pvf-stream/watchdog.py "$@"
W
chmod 755 /usr/local/sbin/pvf-watchdog
cat > /etc/systemd/system/pvf-watchdog.service <<U
[Unit]
Description=Bee cam YouTube Live watchdog
After=network-online.target pvf-restream.service
Wants=network-online.target
[Service]
ExecStart=/usr/bin/python3 $D/watchdog.py
Restart=always
RestartSec=30
StandardOutput=append:$D/logs/pvf-watchdog.log
StandardError=append:$D/logs/pvf-watchdog.log
[Install]
WantedBy=multi-user.target
U
systemctl daemon-reload
systemctl restart pvf-hlsserve
if [ ! -f "$D/youtube-token.json" ]; then
  echo; echo "== Sign in to YouTube (one time)"
  /usr/bin/python3 "$D/watchdog.py" --login
fi
systemctl enable --now pvf-watchdog
sleep 20
echo; tail -5 "$D/logs/pvf-watchdog.log"
echo "status.json: $(curl -s http://127.0.0.1:8088/status.json)"
grep -q pvf-watchdog /usr/local/sbin/pvf-status || sed -i 's/for s in pvf-restream pvf-hls pvf-hlsserve pvf-tunnel/for s in pvf-restream pvf-hls pvf-hlsserve pvf-tunnel pvf-watchdog/' /usr/local/sbin/pvf-status
echo "== watchdog installed"
