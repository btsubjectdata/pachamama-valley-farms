#!/bin/bash
# Two-way sync with the PRIVATE ops repo (btsubjectdata/pvf-ops), run every 2 minutes by pvf-ops-sync.timer.
#  out: status/  - service states, versions, recent logs (secrets redacted)
#  in:  tasks/   - scripts committed there run once, as root; output goes to results/<name>.out
set -u
R=/opt/pvf-ops; D=/opt/pvf-stream
export GIT_SSH_COMMAND="ssh -i /root/.ssh/pvf_ops -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
OPS_URL="git@github.com:btsubjectdata/pvf-ops.git"
# Self-repair: a power cut mid-write can corrupt the local clone. If git can't read it, re-clone.
if ! git -C "$R" rev-parse --verify -q HEAD >/dev/null 2>&1 || ! git -C "$R" fsck --no-dangling >/dev/null 2>&1; then
  logger -t pvf-ops-sync "local ops repo unreadable; re-cloning"
  rm -rf "$R" && git clone -q "$OPS_URL" "$R" || { logger -t pvf-ops-sync "re-clone failed"; exit 1; }
  git -C "$R" config user.name beehive1; git -C "$R" config user.email beehive1@pachamamavalleyfarm.com
fi
cd "$R" || exit 1
# Some networks block SSH on port 22; GitHub also answers on ssh.github.com:443.
if timeout 8 bash -c 'exec 3<>/dev/tcp/github.com/22' 2>/dev/null; then
  git remote set-url origin git@github.com:btsubjectdata/pvf-ops.git
else
  git remote set-url origin ssh://git@ssh.github.com:443/btsubjectdata/pvf-ops.git
fi
git pull -q --rebase origin main 2>/dev/null || { git rebase --abort 2>/dev/null; git reset -q --hard origin/main; }

redact() { sed -E \
  -e 's/[A-Za-z0-9]{4}(-[A-Za-z0-9]{4}){4}/[stream-key]/g' \
  -e 's/GOCSPX-[A-Za-z0-9_-]+/[client-secret]/g' \
  -e 's/ya29\.[A-Za-z0-9._-]+/[access-token]/g' \
  -e 's#1//[A-Za-z0-9._-]{20,}#[refresh-token]#g' \
  -e 's#(rtsps?://[^/ ]+/)[A-Za-z0-9]{12,}#\1[camera-token]#g' \
  -e 's/("(client_secret|refresh_token|access_token|TunnelSecret)"[[:space:]]*:[[:space:]]*")[^"]*/\1[redacted]/g' \
  -e 's/tskey-[A-Za-z0-9_-]+/[tailscale-key]/g' \
  -e 's/[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net/[tailnet-name]/g' \
  -e 's/\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}\b/[tailscale-ip]/g' \
  -e 's/\b192\.168\.12\.[0-9]{1,3}\b/[home-lan-ip]/g'; }

# ---- run new tasks ----
mkdir -p tasks results status
for t in tasks/*.sh; do
  [ -f "$t" ] || continue
  n=$(basename "$t" .sh); out="results/$n.out"
  [ -f "$out" ] && continue
  { echo "# task $n started $(date '+%F %T %Z')"; timeout 900 bash "$t" 2>&1; echo "# exit $? at $(date '+%F %T %Z')"; } | redact > "$out"
done

# ---- status snapshot ----
{
  echo "updated: $(date '+%F %T %Z')"; echo "host: $(hostname)  uptime:$(uptime -p)"
  echo; echo "== services"; for s in pvf-restream pvf-hlsserve pvf-tunnel pvf-watchdog pvf-hogalert pvf-claude-rc pvf-ops-sync.timer $(systemctl list-units --plain --no-legend "pvf-*@*" 2>/dev/null | awk "{print \$1}"); do printf "%-20s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"; done
  echo; echo "== load"; top -bn1 | head -5
  echo; echo "== restarts"; for u in pvf-restream $(systemctl list-units --plain --no-legend "pvf-restream@*" | awk "{print \$1}"); do printf "%-20s NRestarts=%s active since %s\n" "$u" "$(systemctl show -p NRestarts --value $u)" "$(systemctl show -p ActiveEnterTimestamp --value $u)"; done
  echo; echo "== gpu"; cat /sys/class/drm/card*/gt_cur_freq_mhz 2>/dev/null | head -1 | sed 's/^/gt MHz: /'; timeout 3 intel_gpu_top -J -s 1000 2>/dev/null | head -60 | grep -E '"busy"|"Video"|"Render' | head -6
  echo; echo "== disk"; df -h / | tail -1
  echo; echo "== youtube status.json"; cat $D/hls/status.json 2>/dev/null
  echo; echo "== versions"; ffmpeg -version 2>/dev/null | head -1; cloudflared --version 2>/dev/null; . /etc/os-release; echo "$PRETTY_NAME"
} 2>&1 | redact > status/summary.txt
for l in pvf-restream pvf-watchdog pvf-tunnel pvf-restream-hog pvf-hogalert pvf-trial-4k; do [ -f "$D/logs/$l.log" ] || continue; tail -200 "$D/logs/$l.log" 2>/dev/null | redact > "status/$l.log"; done
grep -vE '^(YT_STREAM_KEY|RTSPS_URL)=' $D/stream.env 2>/dev/null | redact > status/stream.env.public
cat $D/linux.env 2>/dev/null | redact > status/linux.env
for c in $D/cams/*.env; do [ -f "$c" ] || continue; grep -vE '^(YT_STREAM_KEY|RTSPS_URL)=' "$c" | redact > "status/cam-$(basename "$c").public"; done

git add -A
if ! git diff --cached --quiet; then
  git -c user.name=beehive1 -c user.email=beehive1@pachamamavalleyfarm.com commit -qm "beehive1 sync $(date '+%F %T')"
  git push -q origin HEAD:main 2>/dev/null || { git pull -q --rebase origin main && git push -q origin HEAD:main; }
fi
