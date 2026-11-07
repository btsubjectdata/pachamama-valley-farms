#!/bin/bash
# Switch the hog cam to 4K on YouTube with a safety net.   sudo bash trial-4k.sh start|status|keep|rollback
#   start    back up cams/hog.env, set 4K (3840x2160, 16 Mbps), restart the hog relay, and arm a 90-minute guard:
#            if the two relays restart 4+ times or a relay fails, it rolls hog back to 1440p by itself.
#   status   what the guard has seen so far
#   keep     4K is good: disarm the guard, delete the backup
#   rollback put hog back to the pre-trial settings now
set -u
D=/opt/pvf-stream; E=$D/cams/hog.env; B=$E.pre4k; LOG=$D/logs/pvf-trial-4k.log; ST=$D/trial-4k.state
GUARD_MIN=90; MAX_RESTARTS=4
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
units() { echo pvf-restream $(systemctl list-units --plain --no-legend "pvf-restream@*" | awk '{print $1}'); }
restarts() { local n=0; for u in $(units); do n=$((n + $(systemctl show -p NRestarts --value "$u"))); done; echo $n; }
failed() { for u in $(units); do [ "$(systemctl is-active "$u")" = active ] || { echo "$u"; return; }; done; }
rollback() {
  [ -f "$B" ] || { log "no backup at $B; nothing to roll back"; return 1; }
  install -m 600 -o pvf -g pvf "$B" "$E"; rm -f "$B"
  systemctl restart pvf-restream@hog
  log "ROLLED BACK hog cam to pre-trial settings ($1)"; rm -f "$ST"
  systemctl stop pvf-trial-4k 2>/dev/null
}
case "${1:-status}" in
  start)
    [ -f "$E" ] || { echo "no $E"; exit 1; }
    [ -f "$B" ] || cp -p "$E" "$B"
    sed -i -E 's/^SCALE=.*/SCALE="3840:2160"/; s/^VIDEO_BITRATE=.*/VIDEO_BITRATE="16000k"/' "$E"
    grep -q '^SCALE=' "$E" || echo 'SCALE="3840:2160"' >> "$E"
    grep -q '^VIDEO_BITRATE=' "$E" || echo 'VIDEO_BITRATE="16000k"' >> "$E"
    systemctl restart pvf-restream@hog; sleep 20
    echo "$(restarts)" > "$ST"
    log "hog cam switched to 4K; guard armed for $GUARD_MIN min (rollback after $MAX_RESTARTS relay restarts or a failed relay)"
    systemctl stop pvf-trial-4k 2>/dev/null
    systemd-run --unit pvf-trial-4k --description "4K trial guard" /bin/bash "$D/trial-4k.sh" guard >/dev/null
    ;;
  guard)
    base=$(cat "$ST" 2>/dev/null || echo 0); end=$(( $(date +%s) + GUARD_MIN * 60 ))
    while [ "$(date +%s)" -lt "$end" ]; do
      sleep 30; [ -f "$B" ] || exit 0
      n=$(( $(restarts) - base )); f=$(failed)
      [ -n "$f" ] && { rollback "unit $f not active"; exit 0; }
      [ "$n" -ge "$MAX_RESTARTS" ] && { rollback "$n relay restarts in the trial window"; exit 0; }
    done
    log "guard window over: $(( $(restarts) - base )) relay restarts, both relays up. 4K looks stable; run 'trial-4k.sh keep' to drop the backup (or leave it; nothing changes)."
    ;;
  keep)   systemctl stop pvf-trial-4k 2>/dev/null; rm -f "$B" "$ST"; log "kept 4K; backup removed" ;;
  rollback) rollback "manual" ;;
  *)
    base=$(cat "$ST" 2>/dev/null); echo "guard: $(systemctl is-active pvf-trial-4k 2>/dev/null)  backup: $([ -f "$B" ] && echo present || echo none)"
    [ -n "${base:-}" ] && echo "relay restarts since trial start: $(( $(restarts) - base ))"
    grep -E '^(SCALE|VIDEO_BITRATE|HLS_RENDITIONS)=' "$E"; tail -5 "$LOG" 2>/dev/null ;;
esac
