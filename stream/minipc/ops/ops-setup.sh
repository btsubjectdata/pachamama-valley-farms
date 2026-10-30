#!/bin/bash
# One-time setup so Claude can look after the mini PC without you at the keyboard.
#   1) a private GitHub "ops" channel (status + logs out, approved fix scripts in)
#   2) Claude Code Remote Control running as a service, so you can talk to the Claude on this box from your phone
# Usage:  sudo bash ops-setup.sh
set -u
REPO_RAW="https://raw.githubusercontent.com/btsubjectdata/pachamama-valley-farms/main/stream/minipc"
OPS_REPO="git@github.com:btsubjectdata/pvf-ops.git"
ADMIN="${SUDO_USER:-hiveadmin}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
apt-get install -y -qq git tmux >/dev/null

echo "== 1. Ops channel key"
mkdir -p /root/.ssh; chmod 700 /root/.ssh
[ -f /root/.ssh/pvf_ops ] || ssh-keygen -q -t ed25519 -N "" -C "beehive1-pvf-ops" -f /root/.ssh/pvf_ops
echo; echo "---- copy this whole line and send it to Claude ----"; cat /root/.ssh/pvf_ops.pub; echo "----------------------------------------------------"; echo
export GIT_SSH_COMMAND="ssh -i /root/.ssh/pvf_ops -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
echo "Waiting for the key to be added to the pvf-ops repo (checks every 15 s; Ctrl+C to stop)..."
until git ls-remote "$OPS_REPO" >/dev/null 2>&1; do sleep 15; done
echo "Key accepted."
[ -d /opt/pvf-ops/.git ] || git clone -q "$OPS_REPO" /opt/pvf-ops
cd /opt/pvf-ops; git config user.name beehive1; git config user.email beehive1@pachamamavalleyfarm.com
if [ -z "$(git rev-parse --verify -q HEAD)" ]; then
  mkdir -p tasks results status; echo "# beehive1 ops channel" > README.md
  git add -A; git commit -qm "init"; git branch -M main; git push -q -u origin main
fi
curl -fsSL "$REPO_RAW/ops/ops-sync.sh" -o /opt/pvf-stream/ops-sync.sh; chmod 700 /opt/pvf-stream/ops-sync.sh
cat > /etc/systemd/system/pvf-ops-sync.service <<U
[Unit]
Description=Sync status/logs and run approved tasks via the private pvf-ops repo
After=network-online.target
[Service]
Type=oneshot
ExecStart=/bin/bash /opt/pvf-stream/ops-sync.sh
U
cat > /etc/systemd/system/pvf-ops-sync.timer <<U
[Unit]
Description=Run pvf-ops-sync every 2 minutes
[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
U
systemctl daemon-reload; systemctl enable --now pvf-ops-sync.timer
systemctl start pvf-ops-sync.service && echo "First sync done."

echo; echo "== 2. Claude Remote Control service"
CLAUDE="$(sudo -u "$ADMIN" bash -lc 'command -v claude' 2>/dev/null || echo /home/$ADMIN/.local/bin/claude)"
W="/home/$ADMIN/beehive1"
sudo -u "$ADMIN" mkdir -p "$W"
sudo -u "$ADMIN" bash -c "cat > '$W/CLAUDE.md'" <<'MD'
# beehive1 - Pachamama Valley Farm bee cam relay
This mini PC streams the bee yard camera to YouTube (4K) and the website (1080p HLS via Cloudflare Tunnel).
- Everything lives in /opt/pvf-stream (run as system user `pvf`). Services: pvf-restream, pvf-hls, pvf-hlsserve, pvf-tunnel, pvf-watchdog.
- Status: `sudo pvf-status`; logs in /opt/pvf-stream/logs/; YouTube state in /opt/pvf-stream/hls/status.json.
- Settings: /opt/pvf-stream/stream.env and linux.env. NEVER print, log or commit the YouTube stream key, the Google token/client files, or the Cloudflare tunnel credentials.
- Source code: github.com/btsubjectdata/pachamama-valley-farms, folder stream/minipc. Update with `sudo bash ~/update.sh`.
- Ops channel: /opt/pvf-ops syncs to the private repo btsubjectdata/pvf-ops every 2 minutes (status out, tasks in).
MD
cat > /etc/systemd/system/pvf-claude-rc.service <<U
[Unit]
Description=Claude Code Remote Control for beehive1
After=network-online.target
Wants=network-online.target
[Service]
Type=forking
User=$ADMIN
WorkingDirectory=$W
Environment=PATH=/home/$ADMIN/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/tmux new-session -d -s claude-rc "$CLAUDE remote-control --name beehive1 --spawn same-dir"
ExecStop=/usr/bin/tmux kill-session -t claude-rc
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
U
systemctl daemon-reload
echo
echo "Next (one time, as yourself, not sudo):"
echo "   cd ~/beehive1 && claude remote-control --name beehive1"
echo "Answer y to 'Trust this folder' and y to 'Enable Remote Control', check it shows a session URL, then press Ctrl+C."
echo "Then run:   sudo systemctl enable --now pvf-claude-rc"
