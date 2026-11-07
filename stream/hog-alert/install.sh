#!/bin/bash
# Pachamama Valley Farm hog alert - installer for beehive1 (Ubuntu, alongside the pvf-stream relay).
# Usage:  sudo bash install.sh
# Installs the detector in its own Python venv, writes the systemd service, and starts it in DRY RUN
# (nothing sent to the phone) until hog-alert.env has the keys and DRY_RUN is set to 0.
set -euo pipefail
REPO="${REPO:-https://github.com/btsubjectdata/pachamama-valley-farms.git}"
D=/opt/pvf-stream; W=$D/hog-alert; CLONE=$W/repo; SRC=$CLONE/stream/hog-alert
say() { echo; echo "== $*"; }
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
id pvf >/dev/null 2>&1 || { echo "The pvf-stream relay must be installed first (user pvf missing)."; exit 1; }

say "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq git python3-venv python3-pip ffmpeg libgl1 libglib2.0-0 >/dev/null   # libgl1+glib: OpenCV (pulled in by ultralytics) needs them even headless

say "Source -> $SRC"
install -d -m 755 -o pvf -g pvf "$W" "$W/hits"
if [ -d "$CLONE/.git" ]; then sudo -u pvf git -C "$CLONE" pull -q --ff-only; else git clone -q --depth 1 "$REPO" "$CLONE"; chown -R pvf:pvf "$CLONE"; fi

say "Python venv (CPU-only torch; ~1 GB, a few minutes the first time)"
[ -x "$W/venv/bin/python" ] || sudo -u pvf python3 -m venv "$W/venv"
sudo -u pvf "$W/venv/bin/pip" install -q --upgrade pip
sudo -u pvf "$W/venv/bin/pip" install -q --extra-index-url https://download.pytorch.org/whl/cpu -r "$SRC/requirements.txt"

say "Settings"
if [ ! -f "$D/hog-alert.env" ]; then
  install -m 600 -o pvf -g pvf "$SRC/hog-alert.env.example" "$D/hog-alert.env"
  echo "Created $D/hog-alert.env - add PUSHOVER_TOKEN, PUSHOVER_USER and ANTHROPIC_API_KEY, then set DRY_RUN=\"0\"."
else
  echo "$D/hog-alert.env already exists; left alone."
fi

say "Model download + self-test (one time, cached in $W/models)"
sudo -u pvf env HOME="$W" "$W/venv/bin/python" - <<'PY' || echo "Model self-test failed; the service will retry when it starts."
import sys, numpy as np
sys.path.insert(0, "/opt/pvf-stream/hog-alert/repo/stream/hog-alert")
import hog_alert as h
h.load_cfg(); d = h.Detector(h.CFG["DET_MODEL"], h.i("DET_IMGSZ")); d.load()
boxes = d.animals(np.zeros((720, 1280, 3), dtype=np.uint8))
print(f"MegaDetector ready (blank frame -> {len(boxes)} animals)")
PY

say "systemd service pvf-hogalert"
sed "s#@W@#$W#g; s#@SRC@#$SRC#g" "$SRC/pvf-hogalert.service" > /etc/systemd/system/pvf-hogalert.service
systemctl daemon-reload
systemctl enable --now pvf-hogalert
install -m 755 "$SRC/pvf-hog" /usr/local/sbin/pvf-hog
sleep 8; systemctl is-active pvf-hogalert && tail -5 "$D/logs/pvf-hogalert.log"

cat <<EOF

Installed. Next:
  1. sudo nano $D/hog-alert.env   (Pushover token + user key, Anthropic API key, DRY_RUN="0")
  2. sudo systemctl restart pvf-hogalert
  3. sudo pvf-hog test            (rings the phone once at normal priority; 'sudo pvf-hog test 2' = emergency)
  4. sudo pvf-hog                 (status)
EOF
