#!/bin/bash
# Add a second camera to beehive1.  Usage: sudo bash add-camera.sh <name> <rtsp-url> [title]
# Creates /opt/pvf-stream/cams/<name>.env and the pvf-restream@<name> service (YouTube + website feed) and starts it.
# The watchdog creates the YouTube stream + broadcast for it on its next cycle and fills in YT_STREAM_KEY.
set -euo pipefail
NAME="${1:?camera name, e.g. hog}"; URL="${2:?rtsp url}"
D=/opt/pvf-stream
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
install -d -m 700 -o pvf -g pvf "$D/cams"
E="$D/cams/$NAME.env"
if [ ! -f "$E" ]; then
  cat > "$E" <<ENV
# $NAME camera. Values here override stream.env (audio filter settings inherit from there).
RTSPS_URL="$URL"
YT_STREAM_KEY="PENDING"
# Since restream.sh decodes once per camera (Nov 7, 2026) two cameras at 4K fit on the Intel GPU.
# If a camera keeps restarting, drop it to SCALE="2560:1440" VIDEO_BITRATE="10000k" or HLS_RENDITIONS="720".
SCALE="3840:2160"
VIDEO_BITRATE="16000k"
HLS_RENDITIONS="1080,720"
ENV
  chmod 600 "$E"; chown pvf:pvf "$E"
fi
for kind in restream; do
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
systemctl enable --now "pvf-restream@$NAME"
echo "camera $NAME added; service pvf-restream@$NAME started (YouTube + website feed)"
