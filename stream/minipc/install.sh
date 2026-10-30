#!/bin/bash
# Pachamama Valley Farm bee cam relay - installer for the Ubuntu Server mini PC.
# Usage:  sudo bash install.sh ~/pvf-migrate.tgz
# Installs everything and tests it, but does NOT start streaming. Run `sudo pvf-go-live` for the cutover.
set -euo pipefail
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/btsubjectdata/pachamama-valley-farms/main/stream/minipc}"
BUNDLE="${1:-}"
D=/opt/pvf-stream
say() { echo; echo "== $*"; }
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
[ -f "$BUNDLE" ] || { echo "Usage: sudo bash install.sh /path/to/pvf-migrate.tgz"; exit 1; }
. /etc/os-release; echo "OS: $PRETTY_NAME"

say "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq software-properties-common curl ca-certificates gnupg >/dev/null
add-apt-repository -y multiverse >/dev/null
if [ ! -f /etc/apt/sources.list.d/cloudflared.list ]; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
fi
apt-get update -qq
apt-get install -y -qq ffmpeg intel-media-va-driver-non-free vainfo python3 cloudflared >/dev/null
ffmpeg -version | head -1; cloudflared --version

say "Service user and files"
id pvf >/dev/null 2>&1 || useradd --system --home-dir "$D" --shell /usr/sbin/nologin pvf
for g in video render; do getent group $g >/dev/null && usermod -aG $g pvf; done
mkdir -p "$D"/{logs,hls,cloudflared}
for f in restream.sh hls.sh serve.py; do curl -fsSL "$REPO_RAW/$f" -o "$D/$f"; done
chmod 755 "$D/restream.sh" "$D/hls.sh" "$D/serve.py"

T=$(mktemp -d); tar -xzf "$BUNDLE" -C "$T"
install -m 600 "$T/stream.env" "$D/stream.env"
TID=$(sed -n 's/^tunnel: *//p' "$T/pvf-cam.yml")
install -m 600 "$T/$TID.json" "$D/cloudflared/$TID.json"
cat > "$D/cloudflared/pvf-cam.yml" <<CFG
tunnel: $TID
credentials-file: $D/cloudflared/$TID.json
no-autoupdate: true
ingress:
  - hostname: cam.pachamamavalleyfarms.com
    service: http://127.0.0.1:8088
  - service: http_status:404
CFG
rm -rf "$T"
echo "tunnel $TID"

say "Hardware video encoder (Intel Quick Sync via VA-API)"
ENC=software
if [ -e /dev/dri/renderD128 ] && vainfo --display drm --device /dev/dri/renderD128 2>/dev/null | grep -q "VAProfileH264High.*VAEntrypointEncSlice"; then
  ENC=vaapi; echo "H.264 hardware encode: yes"
  LP=0; vainfo --display drm --device /dev/dri/renderD128 2>/dev/null | grep "VAProfileH264High" | grep -q "VAEntrypointEncSlice\s*$" || LP=1
  vainfo --display drm --device /dev/dri/renderD128 2>/dev/null | grep -E "Driver version|HEVCMain .*VLD" | head -2
else
  echo "H.264 hardware encode: NOT available - falling back to software at 1080p"
fi
{
  echo "# Linux overrides for the mini PC (stream.env came from the Mac)."
  echo "LINUX_ENCODER=\"$ENC\""
  echo "VAAPI_LOW_POWER=\"${LP:-0}\""
  if [ "$ENC" = software ]; then echo 'SCALE="1920:1080"'; echo 'VIDEO_BITRATE="6000k"'; fi
} > "$D/linux.env"
chown -R pvf:pvf "$D"; chmod 700 "$D"

say "Camera reachability (farm network over the site-to-site link)"
set +e
source "$D/stream.env"
if timeout 20 ffprobe -v error -rtsp_transport tcp -timeout 10000000 -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "$RTSPS_URL"; then echo "camera: OK"; else echo "camera: NOT REACHABLE from this PC"; fi

say "20-second test of the full YouTube pipeline (encodes, but sends nowhere)"
sed 's#-f flv "\$YT_INGEST/\$YT_STREAM_KEY"#-t 20 -f null -#' "$D/restream.sh" > /tmp/pvf-test.sh
sudo -u pvf bash /tmp/pvf-test.sh 2>&1 | tail -5
echo "test exit: ${PIPESTATUS[0]}"
rm -f /tmp/pvf-test.sh
set -e

say "systemd services (installed, not started)"
unit() { # name description command
  cat > "/etc/systemd/system/$1.service" <<U
[Unit]
Description=$2
After=network-online.target
Wants=network-online.target
[Service]
User=pvf
Group=pvf
SupplementaryGroups=video render
ExecStart=$3
Restart=always
RestartSec=10
StandardOutput=append:$D/logs/$1.log
StandardError=append:$D/logs/$1.log
[Install]
WantedBy=multi-user.target
U
}
unit pvf-restream "Bee cam to YouTube Live" "/bin/bash $D/restream.sh"
unit pvf-hls "Bee cam HLS backup feed" "/bin/bash $D/hls.sh"
unit pvf-hlsserve "Bee cam HLS file server (localhost only)" "/usr/bin/python3 $D/serve.py"
unit pvf-tunnel "Cloudflare Tunnel for cam.pachamamavalleyfarms.com" "/usr/bin/cloudflared --no-autoupdate tunnel --config $D/cloudflared/pvf-cam.yml run"
cat > /etc/logrotate.d/pvf-stream <<LR
$D/logs/*.log {
  weekly
  rotate 4
  compress
  missingok
  copytruncate
}
LR
systemctl daemon-reload

cat > /usr/local/sbin/pvf-go-live <<'GL'
#!/bin/bash
# Start the bee cam relay on this PC. Stop the Mac relay FIRST (Run-PVF-StopMac on the Mac).
set -u
S="pvf-hlsserve pvf-hls pvf-tunnel pvf-restream"
systemctl enable --now $S
sleep 25
for s in $S; do printf "%-14s %s\n" "$s" "$(systemctl is-active $s)"; done
echo "local backup feed: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/bees.m3u8)"
echo "public backup feed: $(curl -s -o /dev/null -w '%{http_code}' https://cam.pachamamavalleyfarms.com/bees.m3u8)"
tail -3 /opt/pvf-stream/logs/pvf-restream.log
GL
cat > /usr/local/sbin/pvf-status <<'ST'
#!/bin/bash
for s in pvf-restream pvf-hls pvf-hlsserve pvf-tunnel; do printf "%-14s %s\n" "$s" "$(systemctl is-active $s)"; done
echo; echo "CPU/GPU load:"; top -bn1 | head -5 | tail -3
echo; tail -5 /opt/pvf-stream/logs/pvf-restream.log | sed -E 's/[A-Za-z0-9]{4}(-[A-Za-z0-9]{4}){4}/****/g'
ST
cat > /usr/local/sbin/pvf-stop <<'SP'
#!/bin/bash
systemctl disable --now pvf-restream pvf-hls pvf-tunnel pvf-hlsserve && echo "relay stopped on this PC"
SP
chmod 755 /usr/local/sbin/pvf-go-live /usr/local/sbin/pvf-status /usr/local/sbin/pvf-stop
shred -u "$BUNDLE" 2>/dev/null || rm -f "$BUNDLE"

say "Installed. Nothing is streaming from this PC yet."
echo "Next: on the Mac run Run-PVF-StopMac, then here run:  sudo pvf-go-live"
