#!/usr/bin/env python3
"""Pachamama Valley Farm - YouTube Live watchdog (runs as pvf-watchdog.service, as root).

Every CHECK_SECONDS it makes sure the bee cam is actually live on YouTube:
  * keeps a dedicated YouTube stream ("PVF bee cam") and writes its key into stream.env
  * if no usable broadcast exists, creates one with the right settings
    (public, not made for kids, embeddable, DVR on, normal latency, auto start, never auto stop)
    and binds it to the stream
  * if a broadcast is stuck in "ready"/"testing" while video is arriving, pushes it to live
  * if YouTube sees no video for a while, restarts the relay (pvf-restream)
  * writes /opt/pvf-stream/hls/status.json so the website can show YouTube when it's live
    and fall back to the farm's own feed when it isn't.
Uses only the Python standard library. Token: /opt/pvf-stream/youtube-token.json (from `pvf-watchdog --login`).
"""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

D = "/opt/pvf-stream"
TOKEN = f"{D}/youtube-token.json"
CLIENT = f"{D}/youtube-client.json"
STATE = f"{D}/watchdog-state.json"
STATUS = f"{D}/hls/status.json"
ENV = f"{D}/stream.env"
API = "https://www.googleapis.com/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube"
CHECK_SECONDS = 120
STREAM_TITLE = "PVF bee cam"
TITLE = "Live apiary cam, Pachamama Valley Farm, East Texas"
DESC = ("A live camera on the bee yard at Pachamama Valley Farm in Winnsboro, East Texas. "
        "Mid-morning on warm days is the busiest time at the entrances; on cold days the colonies stay clustered inside.\n\n"
        "More about the farm: pachamamavalleyfarm.com")
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

# ---------- stream.env helpers ----------
def env_get(key):
    m = re.search(rf'^{key}="?([^"\n]*)"?', open(ENV).read(), re.M); return m.group(1) if m else None
def env_set(key, val):
    s = open(ENV).read(); line = f'{key}="{val}"'
    s = re.sub(rf'^{key}=.*$', line, s, flags=re.M) if re.search(rf'^{key}=', s, re.M) else s.rstrip("\n") + "\n" + line + "\n"
    with open(ENV, "w") as f: f.write(s)
def restart_relay(why):
    log("restarting relay:", why); subprocess.run(["systemctl", "restart", "pvf-restream"], check=False)

# ---------- one check ----------
def ensure_stream(st):
    if st.get("stream_id"):
        items = yt("GET", "liveStreams", {"part": "id,cdn,status", "id": st["stream_id"]}).get("items", [])
        if items: return items[0]
    for s in yt("GET", "liveStreams", {"part": "id,snippet,cdn,status", "mine": "true", "maxResults": 50}).get("items", []):
        if s["snippet"]["title"] == STREAM_TITLE: break
    else:
        s = yt("POST", "liveStreams", {"part": "snippet,cdn,contentDetails,status"}, {
            "snippet": {"title": STREAM_TITLE},
            "cdn": {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"},
            "contentDetails": {"isReusable": True}})
        log("created YouTube stream", s["id"])
    st["stream_id"] = s["id"]
    key = s["cdn"]["ingestionInfo"]["streamName"]
    if env_get("YT_STREAM_KEY") != key:
        env_set("YT_STREAM_KEY", key); restart_relay("switched to the watchdog's own stream key")
    return s

def find_broadcast(stream_id):
    for status in ("active", "upcoming"):
        for b in yt("GET", "liveBroadcasts", {"part": "id,status,contentDetails", "broadcastStatus": status,
                                              "broadcastType": "all", "maxResults": 25}).get("items", []):
            if b["contentDetails"].get("boundStreamId") == stream_id and b["status"]["lifeCycleStatus"] in OPEN:
                return b
    return None

def create_broadcast(stream_id):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    b = yt("POST", "liveBroadcasts", {"part": "snippet,status,contentDetails"}, {
        "snippet": {"title": TITLE, "description": DESC, "scheduledStartTime": now},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        "contentDetails": {"enableAutoStart": True, "enableAutoStop": False, "enableDvr": True,
                           "latencyPreference": "normal", "recordFromStart": True,
                           "monitorStream": {"enableMonitorStream": False}}})
    yt("POST", "liveBroadcasts/bind", {"part": "id,contentDetails", "id": b["id"], "streamId": stream_id})
    try:  # category People & Blogs, same as before
        yt("PUT", "videos", {"part": "snippet"}, {"id": b["id"], "snippet": {"title": TITLE, "description": DESC, "categoryId": "22"}})
    except Exception as e: log("category update skipped:", e)
    log("created and bound new broadcast", b["id"])
    try:
        v = yt("GET", "videos", {"part": "status", "id": b["id"]})["items"][0]["status"]
        v["embeddable"] = True; yt("PUT", "videos", {"part": "status"}, {"id": b["id"], "status": v})
        log("embedding on for", b["id"])
    except Exception as e: log("embedding update failed (will retry):", e)
    return b

def ensure_embeddable(vid, st):
    if st.get("embed_ok") == vid: return
    v = yt("GET", "videos", {"part": "status", "id": vid}).get("items", [])
    if v and not v[0]["status"].get("embeddable", True):
        s = v[0]["status"]; s["embeddable"] = True
        yt("PUT", "videos", {"part": "status"}, {"id": vid, "status": s}); log("turned embedding back on for", vid)
    st["embed_ok"] = vid

def check(st):
    now = time.time()
    s = ensure_stream(st)
    stream_active = s["status"]["streamStatus"] == "active"
    health = s["status"].get("healthStatus", {}).get("status", "?")
    if stream_active: st["last_video"] = now
    st.setdefault("last_video", now)

    b = find_broadcast(s["id"])
    if not b: b = create_broadcast(s["id"])
    vid, life = b["id"], b["status"]["lifeCycleStatus"]
    ensure_embeddable(vid, st)

    if life in ("created", "ready", "testing") and stream_active:
        st.setdefault("ready_since", now)
        waited = now - st["ready_since"]
        if waited > STUCK_READY_S and not st.get("kicked"):
            # Auto-start fires when video *starts* arriving at a ready broadcast; if the relay was already
            # sending when the broadcast was made, reconnecting it gives YouTube that start.
            restart_relay(f"broadcast {vid} stuck in '{life}' for {int(waited)}s, reconnecting to trigger auto-start")
            st["kicked"] = vid
        elif waited > 2 * STUCK_READY_S:
            try:
                yt("POST", "liveBroadcasts/transition", {"part": "status", "id": vid, "broadcastStatus": "live"})
                log("pushed broadcast", vid, "from", life, "to live")
            except Exception as e:
                log("transition failed, making a fresh broadcast:", e)
                try: yt("DELETE", "liveBroadcasts", {"id": vid})
                except Exception: pass
                b = create_broadcast(s["id"]); vid, life = b["id"], b["status"]["lifeCycleStatus"]
            st.pop("ready_since", None); st.pop("kicked", None)
    else:
        st.pop("ready_since", None); st.pop("kicked", None)

    if not stream_active and now - st["last_video"] > NO_VIDEO_RESTART_S:
        restart_relay(f"YouTube has had no video for {int(now - st['last_video'])}s")
        st["last_video"] = now  # give it another window before the next restart

    live = life == "live" and stream_active
    save(STATUS, {"youtube_live": live, "video_id": vid if live else None,
                  "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, 0o644)
    if st.get("last_line") != (life, stream_active, health):
        log(f"broadcast {vid} {life}; video {'arriving' if stream_active else 'NOT arriving'} ({health})")
        st["last_line"] = (life, stream_active, health)

def main():
    if "--login" in sys.argv: return login()
    st = load(STATE, {}) or {}
    log("watchdog started")
    while True:
        try: check(st)
        except Exception as e:
            log("check failed:", e)
            try: save(STATUS, {"youtube_live": False, "video_id": None,
                               "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, 0o644)
            except Exception: pass
        st["last_line"] = list(st.get("last_line") or [])
        save(STATE, st)
        st["last_line"] = tuple(st["last_line"])
        time.sleep(CHECK_SECONDS)

if __name__ == "__main__": main()
