#!/bin/bash
# Add a second camera to beehive1.  Usage: sudo bash add-camera.sh <name> <rtsp-url> [title]
# Creates /opt/pvf-stream/cams/<name>.env, the pvf-restream@<name> and pvf-hls@<name> services, and starts them.
# The watchdog creates the YouTube stream + broadcast for it on its next cycle and fills in YT_STREAM_KEY.
set -euo pipefail
NAME="${1:?camera name, e.g. hog}"; URL="${2:?rtsp url}"
D=/opt/pvf-stream
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
install -d -m 700 -o pvf -g pvf "$D/cams"
E="$D/cams/$NAME.env"
if [ ! -f "$E" ]; then
  cat > "$E" <<ENV
# $NAME camera. Values here override stream.env (audio filter, size, bitrate inherit from there).
RTSPS_URL="$URL"
YT_STREAM_KEY="PENDING"
ENV
  chmod 600 "$E"; chown pvf:pvf "$E"
fi
for kind in restream hls; do
  [ -f "/etc/systemd/system/pvf-$kind@.service" ] && continue
  cat > "/etc/systemd/system/pvf-$kind@.service" <<U
[Unit]
Description=Camera %i: $kind
After=network-online.target
Wants=network-online.target
[Service]
User=pvf
Group=pvf
SupplementaryGroups=video render
ExecStart=/bin/bash $D/$kind.sh %i
Restart=always
RestartSec=10
StandardOutput=append:$D/logs/pvf-$kind-%i.log
StandardError=append:$D/logs/pvf-$kind-%i.log
[Install]
WantedBy=multi-user.target
U
done
systemctl daemon-reload
systemctl enable --now "pvf-hls@$NAME" "pvf-restream@$NAME"
echo "camera $NAME added; services pvf-hls@$NAME and pvf-restream@$NAME started"
