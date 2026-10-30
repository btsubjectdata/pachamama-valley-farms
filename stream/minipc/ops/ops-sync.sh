#!/bin/bash
# Two-way sync with the PRIVATE ops repo (btsubjectdata/pvf-ops), run every 2 minutes by pvf-ops-sync.timer.
#  out: status/  - service states, versions, recent logs (secrets redacted)
#  in:  tasks/   - scripts committed there run once, as root; output goes to results/<name>.out
set -u
R=/opt/pvf-ops; D=/opt/pvf-stream
export GIT_SSH_COMMAND="ssh -i /root/.ssh/pvf_ops -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
cd "$R" || exit 1
git pull -q --rebase origin main 2>/dev/null || { git rebase --abort 2>/dev/null; git reset -q --hard origin/main; }

redact() { sed -E \
  -e 's/[A-Za-z0-9]{4}(-[A-Za-z0-9]{4}){4}/[stream-key]/g' \
  -e 's/GOCSPX-[A-Za-z0-9_-]+/[client-secret]/g' \
  -e 's/ya29\.[A-Za-z0-9._-]+/[access-token]/g' \
  -e 's#1//[A-Za-z0-9._-]{20,}#[refresh-token]#g' \
  -e 's#(rtsps?://[^/ ]+/)[A-Za-z0-9]{12,}#\1[camera-token]#g' \
  -e 's/("(client_secret|refresh_token|access_token|TunnelSecret)"[[:space:]]*:[[:space:]]*")[^"]*/\1[redacted]/g'; }

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
  echo; echo "== services"; for s in pvf-restream pvf-hls pvf-hlsserve pvf-tunnel pvf-watchdog pvf-claude-rc pvf-ops-sync.timer; do printf "%-20s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"; done
  echo; echo "== load"; top -bn1 | head -5
  echo; echo "== disk"; df -h / | tail -1
  echo; echo "== youtube status.json"; cat $D/hls/status.json 2>/dev/null
  echo; echo "== versions"; ffmpeg -version 2>/dev/null | head -1; cloudflared --version 2>/dev/null; . /etc/os-release; echo "$PRETTY_NAME"
} 2>&1 | redact > status/summary.txt
for l in pvf-restream pvf-hls pvf-watchdog pvf-tunnel; do tail -200 "$D/logs/$l.log" 2>/dev/null | redact > "status/$l.log"; done
grep -vE '^(YT_STREAM_KEY|RTSPS_URL)=' $D/stream.env 2>/dev/null | redact > status/stream.env.public
cat $D/linux.env 2>/dev/null | redact > status/linux.env

git add -A
if ! git diff --cached --quiet; then
  git -c user.name=beehive1 -c user.email=beehive1@pachamamavalleyfarm.com commit -qm "beehive1 sync $(date '+%F %T')"
  git push -q origin HEAD:main 2>/dev/null || { git pull -q --rebase origin main && git push -q origin HEAD:main; }
fi
