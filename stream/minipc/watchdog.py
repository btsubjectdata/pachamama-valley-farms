#!/usr/bin/env python3
"""Pachamama Valley Farm - YouTube Live watchdog (runs as pvf-watchdog.service, as root).

Every CHECK_SECONDS it makes sure each camera in CAMS is actually live on YouTube:
  * keeps a dedicated YouTube stream per camera and writes its key into that camera's env file
  * if no usable broadcast exists, creates one with the right settings
    (public, not made for kids, embeddable, DVR on, normal latency, auto start, never auto stop)
    and binds it to the stream
  * if a broadcast is stuck in "ready"/"testing" while video is arriving, pushes it to live
  * if YouTube sees no video for a while, restarts the relay (pvf-restream)
  * writes /opt/pvf-stream/hls/status.json (top level = bees, plus "cams": {bees, hog}) so the website
    can show YouTube when it's live and fall back to the farm's own feed when it isn't.
Uses only the Python standard library. Token: /opt/pvf-stream/youtube-token.json (from `pvf-watchdog --login`).
"""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

D = "/opt/pvf-stream"
TOKEN = f"{D}/youtube-token.json"
CLIENT = f"{D}/youtube-client.json"
STATE = f"{D}/watchdog-state.json"
STATUS = f"{D}/hls/status.json"
API = "https://www.googleapis.com/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube"
CHECK_SECONDS = 120
FARM = "\n\nMore about the farm: pachamamavalleyfarm.com"
CAMS = [
    {"key": "bees", "env": f"{D}/stream.env", "service": "pvf-restream", "stream_title": "PVF bee cam",
     "title": "Live apiary cam, Pachamama Valley Farm, East Texas",
     "desc": "A live camera on the bee yard at Pachamama Valley Farm in Winnsboro, East Texas. "
             "Mid-morning on warm days is the busiest time at the entrances; on cold days the colonies stay clustered inside." + FARM},
    {"key": "hog", "env": f"{D}/cams/hog.env", "service": "pvf-restream@hog", "stream_title": "PVF hog trap",
     "title": "Live hog trap cam, Pachamama Valley Farm, East Texas",
     "desc": "A live camera on the feral hog corral trap at Pachamama Valley Farm in Winnsboro, East Texas. "
             "Hogs usually come in after dark; the gate drops only when the whole sounder is inside." + FARM},
]
STUCK_READY_S = 180      # broadcast ready + video arriving this long -> transition to live
NO_VIDEO_RESTART_S = 300 # YouTube sees no video this long -> restart relay
OPEN = ("created", "ready", "testStarting", "testing", "liveStarting", "live")

def log(*a): print(datetime.now().strftime("%F %T"), *a, flush=True)
def load(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d
def save(p, obj, mode=0o600):
    tmp = p + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=1)
    os.chmod(tmp, mode); os.replace(tmp, p)

def client():
    c = load(CLIENT)
    if c and len(c) == 1 and isinstance(next(iter(c.values())), dict):  # Google's download: {"installed": {...}}
        c = next(iter(c.values()))
    return c

def post_form(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
    except urllib.error.HTTPError as e: return json.load(e)

# ---------- OAuth (device flow; works on a headless box) ----------
def login():
    c = client()
    if not c: sys.exit(f"Missing {CLIENT}")
    r = post_form("https://oauth2.googleapis.com/device/code", {"client_id": c["client_id"], "scope": SCOPE})
    if "device_code" not in r: sys.exit(f"Google refused: {r}")
    print(f"\nOn any phone or computer, open  {r['verification_url']}\nand enter the code:  {r['user_code']}\n"
          "Sign in with the Google account that owns the Pachamama Valley Farm YouTube channel,\n"
          "choose the channel if asked, and allow access.\n", flush=True)
    while True:
        time.sleep(r.get("interval", 5))
        t = post_form("https://oauth2.googleapis.com/token", {
            "client_id": c["client_id"], "client_secret": c["client_secret"],
            "device_code": r["device_code"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if "refresh_token" in t:
            t["expires_at"] = time.time() + t.get("expires_in", 3000) - 60
            save(TOKEN, t); print("Signed in. Token saved."); return
        if t.get("error") not in ("authorization_pending", "slow_down"): sys.exit(f"Sign-in failed: {t}")

def access_token():
    t, c = load(TOKEN), client()
    if not t: raise RuntimeError("not signed in (run: sudo pvf-watchdog --login)")
    if time.time() < t.get("expires_at", 0): return t["access_token"]
    r = post_form("https://oauth2.googleapis.com/token", {
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    if "access_token" not in r: raise RuntimeError(f"token refresh failed: {r.get('error')}")
    t.update(access_token=r["access_token"], expires_at=time.time() + r.get("expires_in", 3000) - 60)
    save(TOKEN, t); return t["access_token"]

def yt(method, path, params=None, body=None):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + access_token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"{method} {path} -> {e.code}: {msg}")

# ---------- env helpers ----------
def env_get(path, key):
    m = re.search(rf'^{key}="?([^"\n]*)"?', open(path).read(), re.M); return m.group(1) if m else None
def env_set(path, key, val):
    s = open(path).read() if os.path.exists(path) else ""; line = f'{key}="{val}"'
    s = re.sub(rf'^{key}=.*$', line, s, flags=re.M) if re.search(rf'^{key}=', s, re.M) else s.rstrip("\n") + "\n" + line + "\n"
    with open(path, "w") as f: f.write(s)
def restart_relay(cam, why):
    log(f"[{cam['key']}] restarting relay:", why); subprocess.run(["systemctl", "restart", cam["service"]], check=False)

# ---------- one check ----------
def ensure_stream(cam, st, mine):
    """mine: the account's liveStreams listing for this cycle (shared by all cameras)."""
    s = None
    if st.get("stream_id"):
        s = next((x for x in mine if x["id"] == st["stream_id"]), None)
    if s is None:
        s = next((x for x in mine if x["snippet"]["title"] == cam["stream_title"]), None)
    if s is None:
        s = yt("POST", "liveStreams", {"part": "snippet,cdn,contentDetails,status"}, {
            "snippet": {"title": cam["stream_title"]},
            "cdn": {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"},
            "contentDetails": {"isReusable": True}})
        log(f"[{cam['key']}] created YouTube stream", s["id"])
    st["stream_id"] = s["id"]
    key = s["cdn"]["ingestionInfo"]["streamName"]
    if env_get(cam["env"], "YT_STREAM_KEY") != key:
        env_set(cam["env"], "YT_STREAM_KEY", key); restart_relay(cam, "switched to the watchdog's own stream key")
    return s

def list_broadcasts():
    out = []
    for status in ("active", "upcoming"):
        out += yt("GET", "liveBroadcasts", {"part": "id,status,contentDetails", "broadcastStatus": status,
                                           "broadcastType": "all", "maxResults": 25}).get("items", [])
    return out

def find_broadcast(stream_id, broadcasts):
    for b in broadcasts:
        if b["contentDetails"].get("boundStreamId") == stream_id and b["status"]["lifeCycleStatus"] in OPEN:
            return b
    return None

def create_broadcast(cam, stream_id):
    TITLE, DESC = cam["title"], cam["desc"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    b = yt("POST", "liveBroadcasts", {"part": "snippet,status,contentDetails"}, {
        "snippet": {"title": TITLE, "description": DESC, "scheduledStartTime": now},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        "contentDetails": {"enableAutoStart": True, "enableAutoStop": False, "enableDvr": True,
                           "latencyPreference": "normal", "recordFromStart": False,  # no replay saved unless Bradley asks
                           "monitorStream": {"enableMonitorStream": False}}})
    yt("POST", "liveBroadcasts/bind", {"part": "id,contentDetails", "id": b["id"], "streamId": stream_id})
    try:  # category People & Blogs, same as before
        yt("PUT", "videos", {"part": "snippet"}, {"id": b["id"], "snippet": {"title": TITLE, "description": DESC, "categoryId": "22"}})
    except Exception as e: log("category update skipped:", e)
    log(f"[{cam['key']}] created and bound new broadcast", b["id"])
    try:
        v = yt("GET", "videos", {"part": "status", "id": b["id"]})["items"][0]["status"]
        v["embeddable"] = True; yt("PUT", "videos", {"part": "status"}, {"id": b["id"], "status": v})
        log("embedding on for", b["id"])
    except Exception as e: log("embedding update failed (will retry):", e)
    return b

def ensure_embeddable(vid, st):
    """Checked every cycle (1 quota unit): YouTube can flip embedding off when a broadcast goes live.
    Returns True only when the video is confirmed embeddable."""
    v = yt("GET", "videos", {"part": "status", "id": vid}).get("items", [])
    if not v: return False
    s = v[0]["status"]
    if s.get("embeddable", False): return True
    s["embeddable"] = True
    try:
        yt("PUT", "videos", {"part": "status"}, {"id": vid, "status": s}); log("turned embedding back on for", vid)
    except Exception as e:
        log("embedding update failed:", str(e).splitlines()[0][:160])
    return False

def check_cam(cam, st, now, mine, broadcasts):
    s = ensure_stream(cam, st, mine)
    stream_active = s["status"]["streamStatus"] == "active"
    health = s["status"].get("healthStatus", {}).get("status", "?")
    if stream_active: st["last_video"] = now
    st.setdefault("last_video", now)

    b = find_broadcast(s["id"], broadcasts)
    if not b: b = create_broadcast(cam, s["id"])
    vid, life = b["id"], b["status"]["lifeCycleStatus"]
    embeddable = ensure_embeddable(vid, st)

    if life in ("created", "ready", "testing") and stream_active:
        st.setdefault("ready_since", now)
        waited = now - st["ready_since"]
        if waited > STUCK_READY_S and not st.get("kicked"):
            # Auto-start fires when video *starts* arriving at a ready broadcast; if the relay was already
            # sending when the broadcast was made, reconnecting it gives YouTube that start.
            restart_relay(cam, f"broadcast {vid} stuck in '{life}' for {int(waited)}s, reconnecting to trigger auto-start")
            st["kicked"] = vid
        elif waited > 2 * STUCK_READY_S:
            try:
                yt("POST", "liveBroadcasts/transition", {"part": "status", "id": vid, "broadcastStatus": "live"})
                log(f"[{cam['key']}] pushed broadcast", vid, "from", life, "to live")
            except Exception as e:
                log(f"[{cam['key']}] transition failed:", str(e).splitlines()[0][:160])
                # Only replace a stuck broadcast at most once an hour, so YouTube isn't flooded with new ones.
                if now - st.get("last_recreate", 0) > 3600:
                    st["last_recreate"] = now
                    try: yt("DELETE", "liveBroadcasts", {"id": vid})
                    except Exception: pass
                    b = create_broadcast(cam, s["id"]); vid, life = b["id"], b["status"]["lifeCycleStatus"]
                else:
                    log(f"[{cam['key']}] keeping", vid, "- already replaced one in the last hour")
            st.pop("ready_since", None); st.pop("kicked", None)
    else:
        st.pop("ready_since", None); st.pop("kicked", None)

    if not stream_active and now - st["last_video"] > NO_VIDEO_RESTART_S:
        restart_relay(cam, f"YouTube has had no video for {int(now - st['last_video'])}s")
        st["last_video"] = now  # give it another window before the next restart

    # Only point the website at YouTube when it is live AND embeddable; otherwise it keeps the farm feed.
    live = life == "live" and stream_active and embeddable
    if st.get("last_line") != [life, stream_active, health]:
        log(f"[{cam['key']}] broadcast {vid} {life}; video {'arriving' if stream_active else 'NOT arriving'} ({health})")
        st["last_line"] = [life, stream_active, health]
    return {"youtube_live": live, "video_id": vid if live else None}

def write_status(results):
    bees = results.get("bees", {"youtube_live": False, "video_id": None})
    save(STATUS, {"youtube_live": bees["youtube_live"], "video_id": bees["video_id"], "cams": results,
                  "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, 0o644)

def check(state):
    now = time.time()
    mine = yt("GET", "liveStreams", {"part": "id,snippet,cdn,status", "mine": "true", "maxResults": 50}).get("items", [])
    broadcasts = list_broadcasts()
    results = {}
    for cam in CAMS:
        if cam["key"] != "bees" and not os.path.exists(cam["env"]): continue   # camera not set up yet
        st = state.setdefault(cam["key"], {})
        try:
            results[cam["key"]] = check_cam(cam, st, now, mine, broadcasts)
        except Exception as e:
            log(f"[{cam['key']}] check failed:", str(e).splitlines()[0][:300])
            results[cam["key"]] = {"youtube_live": False, "video_id": None}
    write_status(results)

def main():
    if "--login" in sys.argv: return login()
    state = load(STATE, {}) or {}
    if "stream_id" in state: state = {"bees": state}   # migrate the single-camera state file
    log("watchdog started")
    while True:
        try: check(state)
        except Exception as e:
            log("check failed:", str(e).splitlines()[0][:300])
            try: write_status({})
            except Exception: pass
        save(STATE, state)
        time.sleep(CHECK_SECONDS)

if __name__ == "__main__": main()
