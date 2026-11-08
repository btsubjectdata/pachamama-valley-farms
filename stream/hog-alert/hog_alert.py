#!/usr/bin/env python3
"""Pachamama Valley Farm - feral hog alert (runs as pvf-hogalert.service on beehive1).

Watches the hog trap camera and rings Bradley's phone (Pushover, emergency priority) ONLY when a feral hog
is in the frame - not deer, raccoons, dogs, coyotes or anything else.

Two stages, so it is cheap and quiet:
  1. MegaDetector (a trail-camera animal detector, good on IR night video) looks at a few frames a second
     and answers "is there an animal?". Runs on the CPU; the Intel GPU keeps doing the YouTube encodes.
  2. Only when an animal is there, the animal is cropped out of the frame and sent to Claude (vision) to answer
     "is this a feral hog?". That is a few API calls per animal visit, pennies a month.
Two hog verdicts inside a short window = alert. Then a cooldown, so a sounder rooting around for an hour is one
alert, not forty. Every classified crop and verdict is kept in hits/ so thresholds can be tuned from real footage.

Video comes from the relay's own 720p HLS feed on localhost (no extra RTSP session against UniFi).
Settings: /opt/pvf-stream/hog-alert.env   State: /opt/pvf-stream/hog-alert/state.json
Secrets (Pushover, Anthropic key) are never printed or logged.

CLI:  hog_alert.py                 run the service
      hog_alert.py --test-push     send a test notification to the phone and exit
      hog_alert.py --image FILE    run both stages on one image (jpg/png) and print the verdict
      hog_alert.py --status        print state.json
"""
import base64, io, json, os, re, subprocess, sys, time, uuid, urllib.request, urllib.error
from collections import deque
from datetime import datetime, timezone

D = os.environ.get("PVF_DIR", "/opt/pvf-stream")
ENV_FILE = os.environ.get("HOG_ALERT_ENV", f"{D}/hog-alert.env")
WORK = f"{D}/hog-alert"
HITS = f"{WORK}/hits"
STATE = f"{WORK}/state.json"

DEFAULTS = {
    "SOURCE_URL": "http://127.0.0.1:8088/hog_720.m3u8",   # relay's own 720p feed; any ffmpeg input works
    "FPS": "2",                      # frames per second to look at
    "DET_MODEL": "MDV6-yolov10-c",   # MegaDetector v6 compact; "MDV6-yolov9-c" is a touch more accurate, slower
    "DET_IMGSZ": "960",              # inference size; 640 is ~2x faster, 1280 is what MD was trained at
    "DET_MIN_CONF": "0.25",          # MegaDetector animal confidence to bother classifying
    "DET_MIN_AREA": "0.004",         # ignore animals smaller than this fraction of the frame (bugs, far birds)
    "CLASSIFY_EVERY": "4",           # seconds between Claude calls while an animal stays in frame
    "CLASSIFY_EVERY_CALM": "20",     # ... after a confident "not a hog" (regular deer visits cost less)
    "ALERT_TZ": "America/Chicago",   # time zone for messages, logs and hit file names
    "CLAUDE_MODEL": "claude-haiku-5-5",
    "HOG_MIN_CONF": "0.7",           # Claude's confidence that it is a hog
    "EDGE_MIN_CONF": "0.9",          # ... when the animal is cut off by the frame edge (head often out of view)
    "CLEAR_ON_OTHER_CONF": "0.8",    # a non-hog verdict this confident resets the confirmation count
    "CONFIRMATIONS": "3",            # hog verdicts needed ...
    "CONFIRM_WINDOW": "45",          # ... inside this many seconds
    "COOLDOWN": "900",               # seconds between alerts (15 min)
    "PUSHOVER_PRIORITY": "2",        # 2 = emergency: repeats until acknowledged, bypasses Do Not Disturb
    "PUSHOVER_RETRY": "60",          # emergency: re-ring every N seconds ...
    "PUSHOVER_EXPIRE": "1800",       # ... for up to this long
    "PUSHOVER_SOUND": "siren",
    "ALERT_URL": "https://pachamamavalleyfarm.com/#hogcam",
    "KEEP_HITS_DAYS": "30",
    "DRY_RUN": "0",                  # 1 = everything except sending the push
}
CFG = {}

def log(*a): print(datetime.now().strftime("%F %T"), *a, flush=True)

def load_cfg():
    cfg = dict(DEFAULTS)
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as fh: lines = fh.readlines()
        for line in lines:
            m = re.match(r'^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$', line)
            if m:
                v = m.group(2)
                q = re.match(r'^(["\'])(.*?)\1', v)          # quoted value: take what's inside the quotes
                v = q.group(2) if q else v.split(" #", 1)[0].split("\t#", 1)[0].strip()   # bare value: drop trailing comment
                cfg[m.group(1)] = v
    for k in DEFAULTS:  # real environment wins (handy for tests and one-off runs)
        if k in os.environ: cfg[k] = os.environ[k]
    for k in ("PUSHOVER_TOKEN", "PUSHOVER_USER", "ANTHROPIC_API_KEY"):
        if k in os.environ: cfg[k] = os.environ[k]
    CFG.clear(); CFG.update(cfg)
    os.environ["TZ"] = cfg["ALERT_TZ"]; time.tzset()
    return cfg

def f(k): return float(CFG[k])
def i(k): return int(float(CFG[k]))

def save_json(p, obj, mode=0o644):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh: json.dump(obj, fh, indent=1, default=str)
    os.chmod(tmp, mode); os.replace(tmp, p)

def load_json(p, d=None):
    try:
        with open(p) as fh: return json.load(fh)
    except Exception: return d

# ---------- frames ----------
class FrameSource:
    """ffmpeg -> raw RGB frames at FPS from any URL (HLS, RTSP, file). Restarts itself if the feed stalls."""
    def __init__(self, url, fps, width=1280, height=720):
        self.url, self.fps, self.w, self.h = url, fps, width, height
        self.p = None; self.last = 0

    def start(self):
        self.stop()
        inp = []
        if self.url.startswith("rtsp"): inp = ["-rtsp_transport", "tcp", "-timeout", "10000000"]
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *inp, "-i", self.url,
               "-vf", f"fps={self.fps},scale={self.w}:{self.h}", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.last = time.time()
        log(f"frame source started: {re.sub(r'/[A-Za-z0-9]{12,}', '/[token]', self.url)} at {self.fps} fps")

    def stop(self):
        if self.p:
            try: self.p.kill(); self.p.wait(timeout=5)
            except Exception: pass
        self.p = None

    def read(self):
        import numpy as np
        if not self.p or self.p.poll() is not None: self.start(); time.sleep(2)
        n = self.w * self.h * 3; buf = b""
        while len(buf) < n:
            chunk = self.p.stdout.read(n - len(buf))
            if not chunk:
                log("frame source ended; restarting in 5 s"); time.sleep(5); self.start(); return None
            buf += chunk
        self.last = time.time()
        return np.frombuffer(buf, dtype=np.uint8).reshape(self.h, self.w, 3)

# ---------- stage 1: animal detector ----------
MD_WEIGHTS = {  # MegaDetector v6 (Microsoft, MIT licence) - plain Ultralytics YOLO checkpoints
    "MDV6-yolov10-c": "https://zenodo.org/records/15398270/files/MDV6-yolov10-c.pt?download=1",
    "MDV6-yolov9-c": "https://zenodo.org/records/15398270/files/MDV6-yolov9-c.pt?download=1",
    "MDV6-yolov9-e": "https://zenodo.org/records/15398270/files/MDV6-yolov9-e-1280.pt?download=1",
}

def weights_path(version):
    d = os.environ.get("MODELS_DIR", f"{WORK}/models"); os.makedirs(d, exist_ok=True)
    p = f"{d}/{version}.pt"
    if not os.path.exists(p):
        url = MD_WEIGHTS[version]; log(f"downloading {version} weights")
        tmp = p + ".part"
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk: break
                fh.write(chunk)
        os.replace(tmp, p)
    return p

class Detector:
    """MegaDetector v6 via Ultralytics. Returns [(x1,y1,x2,y2,conf), ...] for animals only (class 0)."""
    def __init__(self, version, imgsz=960):
        self.version, self.imgsz, self.m = version, imgsz, None

    def load(self):
        import torch
        torch.set_num_threads(max(1, min(4, (os.cpu_count() or 4) - 2)))  # leave cores for the encoders
        from ultralytics import YOLO
        self.m = YOLO(weights_path(self.version))
        log(f"MegaDetector loaded ({self.version}, cpu, imgsz {self.imgsz}, {torch.get_num_threads()} threads)")

    def animals(self, frame):
        if self.m is None: self.load()
        # Ultralytics treats numpy input as BGR (OpenCV convention); our frames are RGB.
        r = self.m.predict(frame[:, :, ::-1], imgsz=self.imgsz, conf=0.15, device="cpu", verbose=False)[0]
        out = []
        if r.boxes is None or len(r.boxes) == 0: return out
        xyxy, conf, cls = r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()
        for k in range(len(xyxy)):
            if int(cls[k]) != 0: continue   # MegaDetector classes: 0 animal, 1 person, 2 vehicle
            out.append((*[float(v) for v in xyxy[k]], float(conf[k])))
        return out

def crop_jpeg(frame, box, pad=0.25, max_side=768, quality=85):
    """JPEG bytes of the animal with some context around it (Claude does better with the surroundings)."""
    from PIL import Image
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box[:4]; bw, bh = x2 - x1, y2 - y1
    x1 = max(0, int(x1 - bw * pad)); y1 = max(0, int(y1 - bh * pad))
    x2 = min(w, int(x2 + bw * pad)); y2 = min(h, int(y2 + bh * pad))
    im = Image.fromarray(frame[y1:y2, x1:x2])
    im.thumbnail((max_side, max_side))
    b = io.BytesIO(); im.save(b, "JPEG", quality=quality); return b.getvalue()

def alert_jpeg(frame, box, quality=82):
    """The push picture: whole frame with a yellow box around the animal and an enlarged inset of it."""
    from PIL import Image, ImageDraw
    im = Image.fromarray(frame).convert("RGB"); d = ImageDraw.Draw(im); w, h = im.size
    x1, y1, x2, y2 = [int(v) for v in box[:4]]
    for k in range(4): d.rectangle([x1 - k, y1 - k, x2 + k, y2 + k], outline=(255, 210, 0))
    bw, bh = x2 - x1, y2 - y1
    if bw > 0 and bh > 0:
        pad = int(max(bw, bh) * 0.2)
        crop = im.crop((max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)))
        side = int(min(w, h) * 0.45); crop.thumbnail((side, side))
        # put the inset in whichever top corner is further from the animal
        ix = 12 if (x1 + x2) / 2 > w / 2 else w - crop.width - 12
        d.rectangle([ix - 4, 8, ix + crop.width + 4, 12 + crop.height + 4], fill=(0, 0, 0), outline=(255, 210, 0), width=3)
        im.paste(crop, (ix, 12))
    b = io.BytesIO(); im.save(b, "JPEG", quality=quality); return b.getvalue()

def frame_jpeg(frame, max_side=1280, quality=80):
    from PIL import Image
    im = Image.fromarray(frame); im.thumbnail((max_side, max_side))
    b = io.BytesIO(); im.save(b, "JPEG", quality=quality); return b.getvalue()

# ---------- stage 2: hog or not (Claude vision) ----------
PROMPT = (
    "Two images from a fixed trail camera on a feral hog corral trap in East Texas: first the whole frame, then a "
    "close crop of the animal a detector flagged. At night the images are black-and-white infrared. Decide whether "
    "the animal is a feral hog (wild pig/boar, any age, including piglets).\n"
    "White-tailed deer visit this trap every night and are the usual false alarm. Deer: long thin legs, long neck, "
    "narrow head with large ears, slender body, white tail/rump patch, often grazing head-down. Hog: short legs, "
    "barrel-shaped body, massive head and shoulders with almost no neck, straight back or shoulder hump, snout, "
    "small eyes, tail hangs straight, usually in a group. Raccoons, opossums, armadillos, coyotes, dogs, cats, "
    "cattle, birds and people are NOT hogs.\n"
    "If the head or legs are not visible, or the animal is cut off by the edge of the frame, or it is too small or "
    "blurry to see body shape, say so in 'animal' and keep confidence at or below 0.5. Only give confidence above "
    "0.8 when you can see hog features clearly. Answer with JSON only, no prose: "
    '{"hog": true|false, "confidence": 0.0-1.0, "animal": "<what you think it is>", "count": <number of hogs>}'
)

def classify(jpeg, model=None, api_key=None, frame_jpg=None):
    """Ask Claude about one crop (plus the whole frame for context). Returns dict(hog, confidence, animal, count) or None."""
    model = model or CFG["CLAUDE_MODEL"]; api_key = api_key or CFG.get("ANTHROPIC_API_KEY")
    if not api_key: log("no ANTHROPIC_API_KEY; cannot classify"); return None
    img = lambda b: {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b).decode()}}
    content = ([img(frame_jpg)] if frame_jpg else []) + [img(jpeg), {"type": "text", "text": PROMPT}]
    body = {"model": model, "max_tokens": 400, "thinking": {"type": "disabled"},   # a yes/no needs no deliberation
            "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
                                 {"content-type": "application/json", "x-api-key": api_key,
                                  "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r: res = json.load(r)
    except urllib.error.HTTPError as e:
        try: err = json.load(e).get("error", {}).get("message", "")[:160]
        except Exception: err = ""
        log(f"claude api error {e.code}: {err}"); return None
    except Exception as e:
        log(f"claude api error: {e}"); return None
    text = "".join(p.get("text", "") for p in res.get("content", []) if p.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        log(f"claude gave no json: {text[:120]!r} stop={res.get('stop_reason')} blocks={[p.get('type') for p in res.get('content', [])]} "
            f"usage={res.get('usage')} err={res.get('error')}")
        return None
    try: v = json.loads(m.group(0))
    except Exception: log(f"claude json unreadable: {text[:120]!r}"); return None
    return {"hog": bool(v.get("hog")), "confidence": float(v.get("confidence", 0) or 0),
            "animal": str(v.get("animal", ""))[:60], "count": int(v.get("count", 0) or 0)}

# ---------- pushover ----------
def _multipart(fields, file_field=None, file_bytes=None, filename="hog.jpg"):
    b = uuid.uuid4().hex; out = b""
    for k, v in fields.items():
        out += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    if file_bytes is not None:
        out += (f"--{b}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n").encode() + file_bytes + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return out, f"multipart/form-data; boundary={b}"

def pushover_fields(title, message, priority=None):
    """Everything Pushover needs except the secrets and the picture (kept separate so tests can check it)."""
    pr = i("PUSHOVER_PRIORITY") if priority is None else priority
    fl = {"title": title, "message": message, "priority": pr, "sound": CFG["PUSHOVER_SOUND"],
          "url": CFG["ALERT_URL"], "url_title": "Open the hog cam"}
    if pr == 2: fl.update({"retry": max(30, i("PUSHOVER_RETRY")), "expire": min(10800, i("PUSHOVER_EXPIRE"))})
    return fl

def pushover(title, message, jpeg=None, priority=None):
    fields = pushover_fields(title, message, priority)
    if CFG.get("DRY_RUN") == "1": log(f"DRY RUN push: {fields}"); return True
    tok, usr = CFG.get("PUSHOVER_TOKEN"), CFG.get("PUSHOVER_USER")
    if not tok or not usr: log("PUSHOVER_TOKEN/PUSHOVER_USER missing; cannot push"); return False
    fields.update({"token": tok, "user": usr})
    body, ctype = _multipart(fields, "attachment", jpeg)
    req = urllib.request.Request("https://api.pushover.net/1/messages.json", body, {"Content-Type": ctype})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r); log(f"push sent (request {res.get('request', '?')})"); return True
        except urllib.error.HTTPError as e:
            try: msg = json.load(e).get("errors")
            except Exception: msg = e.code
            log(f"pushover refused: {msg}"); return False
        except Exception as e:
            log(f"pushover error (try {attempt + 1}): {e}"); time.sleep(5)
    return False

# ---------- the decision logic (pure, so it is testable) ----------
class HogLogic:
    """Feed it classifier verdicts; it says when to alert. Confirmations inside a window, then a cooldown.
    A partial view (animal cut off by the frame edge) needs edge_conf; a confident non-hog verdict clears the count."""
    def __init__(self, confirmations, window, cooldown, min_conf, now=time.time, edge_conf=0.9, clear_conf=0.8):
        self.n, self.window, self.cooldown, self.min_conf, self.now = confirmations, window, cooldown, min_conf, now
        self.edge_conf, self.clear_conf = edge_conf, clear_conf
        self.hits = deque(); self.last_alert = 0.0

    def verdict(self, v, partial=False):
        """Returns True when an alert should go out now."""
        t = self.now()
        while self.hits and t - self.hits[0] > self.window: self.hits.popleft()
        if v and not v["hog"] and v["confidence"] >= self.clear_conf: self.hits.clear(); return False
        need = self.edge_conf if partial else self.min_conf
        if not (v and v["hog"] and v["confidence"] >= need): return False
        self.hits.append(t)
        if len(self.hits) < self.n or t - self.last_alert < self.cooldown: return False
        self.last_alert = t; self.hits.clear(); return True

# ---------- hits folder ----------
def touches_edge(box, w, h, m=4):
    return box[0] <= m or box[1] <= m or box[2] >= w - m or box[3] >= h - m

def save_hit(frame_jpg, crop_jpg, box, verdict, alerted):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    day = HITS + "/" + ts[:8]; os.makedirs(day, exist_ok=True)
    base = f"{day}/{ts}-{'HOG' if verdict and verdict['hog'] else 'other'}"
    open(base + "-crop.jpg", "wb").write(crop_jpg)
    if (verdict and verdict["hog"]) or alerted: open(base + "-frame.jpg", "wb").write(frame_jpg)
    save_json(base + ".json", {"time": ts, "box": [round(v, 1) for v in box], "verdict": verdict, "alerted": alerted})
    return base

def prune_hits(days):
    cutoff = time.time() - days * 86400
    if not os.path.isdir(HITS): return
    for d in sorted(os.listdir(HITS)):
        p = f"{HITS}/{d}"
        try:
            if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                for fn in os.listdir(p): os.remove(f"{p}/{fn}")
                os.rmdir(p); log(f"pruned hits/{d}")
        except Exception as e: log(f"prune {d}: {e}")

# ---------- main loop ----------
def run():
    load_cfg()
    os.makedirs(HITS, exist_ok=True)
    st = load_json(STATE, {}) or {}
    st.update({"started": datetime.now(timezone.utc).isoformat(), "frames": 0, "animal_frames": 0,
               "classified": 0, "hogs": st.get("hogs", 0), "alerts": st.get("alerts", 0),
               "last_alert": st.get("last_alert"), "last_animal": st.get("last_animal"), "last_verdict": None})
    logic = HogLogic(i("CONFIRMATIONS"), f("CONFIRM_WINDOW"), f("COOLDOWN"), f("HOG_MIN_CONF"),
                     edge_conf=f("EDGE_MIN_CONF"), clear_conf=f("CLEAR_ON_OTHER_CONF"))
    if st.get("last_alert_ts"): logic.last_alert = float(st["last_alert_ts"])  # keep cooldown across restarts
    det = Detector(CFG["DET_MODEL"], i("DET_IMGSZ")); det.load()
    src = FrameSource(CFG["SOURCE_URL"], f("FPS")); src.start()
    min_area = f("DET_MIN_AREA") * src.w * src.h
    last_classify = 0.0; last_state = 0.0; last_prune = 0.0; api_fail = 0; api_pause_until = 0.0; every = f("CLASSIFY_EVERY")
    if not CFG.get("ANTHROPIC_API_KEY"): log("no ANTHROPIC_API_KEY yet: animals are detected and saved, but not classified")
    log(f"watching for hogs: confirm {CFG['CONFIRMATIONS']}x in {CFG['CONFIRM_WINDOW']}s, cooldown {CFG['COOLDOWN']}s, "
        f"dry_run={CFG['DRY_RUN']}")
    while True:
        frame = src.read()
        if frame is None: continue
        st["frames"] += 1
        try: boxes = det.animals(frame)
        except Exception as e:
            log(f"detector error: {e}"); time.sleep(2); continue
        boxes = [b for b in boxes if b[4] >= f("DET_MIN_CONF") and (b[2] - b[0]) * (b[3] - b[1]) >= min_area]
        now = time.time()
        if boxes:
            st["animal_frames"] += 1; st["last_animal"] = datetime.now().isoformat(timespec="seconds")
            if now - last_classify >= every and now >= api_pause_until:
                last_classify = now
                box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))   # biggest animal in frame
                partial = touches_edge(box, src.w, src.h)
                crop = crop_jpeg(frame, box); ctx = frame_jpeg(frame, max_side=1024, quality=70)
                if CFG.get("ANTHROPIC_API_KEY"):
                    v = classify(crop, frame_jpg=ctx); st["classified"] += 1
                    if v is None:
                        api_fail += 1
                        if api_fail >= 3: api_pause_until = now + 300; api_fail = 0; log("3 API failures; pausing classification for 5 min")
                    else: api_fail = 0
                else:
                    v = None; last_classify = now + 26   # no key: keep one crop every ~30 s for review, nothing else
                alert = logic.verdict(v, partial)
                # a confident "not a hog" slows the checks while that animal hangs around; any hog call speeds them up again
                every = f("CLASSIFY_EVERY_CALM") if (v and not v["hog"] and v["confidence"] >= f("CLEAR_ON_OTHER_CONF")) else f("CLASSIFY_EVERY")
                st["last_verdict"] = v
                if v: log(f"animal det={box[4]:.2f}{' edge' if partial else ''} -> {v['animal']!r} hog={v['hog']} conf={v['confidence']:.2f}"
                          f"{' (needs %.2f)' % logic.edge_conf if partial and v['hog'] else ''}")
                if v and v["hog"]: st["hogs"] += 1
                full = alert_jpeg(frame, box) if (alert or (v and v["hog"])) else b""
                base = save_hit(full, crop, box, v, alert)
                if alert:
                    n = max(1, v.get("count", 1))
                    msg = (f"{n} feral hog{'s' if n > 1 else ''} at the trap, {datetime.now().strftime('%-I:%M %p')} "
                           f"({v['animal']}, confidence {int(v['confidence'] * 100)}%).")
                    ok = pushover("Hog at the trap", msg, full)
                    st["alerts"] += 1; st["last_alert"] = datetime.now().isoformat(timespec="seconds")
                    st["last_alert_ts"] = now; st["last_alert_sent"] = ok
                    log(f"ALERT {'sent' if ok else 'FAILED'}: {msg}  ({os.path.relpath(base, WORK)})")
        if not boxes: every = f("CLASSIFY_EVERY")   # animal gone: next visitor gets the fast cadence
        if now - last_state > 30:
            last_state = now; st["updated"] = datetime.now().isoformat(timespec="seconds")
            st["feed_ok"] = now - src.last < 20; save_json(STATE, st)
        if now - last_prune > 3600: last_prune = now; prune_hits(i("KEEP_HITS_DAYS"))

def test_image(path):
    import numpy as np
    from PIL import Image
    load_cfg()
    frame = np.asarray(Image.open(path).convert("RGB"))
    det = Detector(CFG["DET_MODEL"], i("DET_IMGSZ")); det.load()
    boxes = det.animals(frame)
    print(f"animals found: {len(boxes)}")
    for b in boxes:
        v = classify(crop_jpeg(frame, b), frame_jpg=frame_jpeg(frame, max_side=1024, quality=70))
        print(f"  box {[round(x) for x in b[:4]]} det={b[4]:.2f}{' edge' if touches_edge(b, frame.shape[1], frame.shape[0]) else ''} -> {v}")

def main(argv):
    if "--test-push" in argv:
        load_cfg()
        rest = argv[argv.index("--test-push") + 1:]
        pr = int(rest[0]) if rest and rest[0].lstrip("-").isdigit() else 0
        ok = pushover("Hog alert test", "If you can read this, hog alerts can reach this phone.", priority=pr)
        sys.exit(0 if ok else 1)
    if "--image" in argv: test_image(argv[argv.index("--image") + 1]); return
    if "--status" in argv: print(json.dumps(load_json(STATE, {}), indent=1)); return
    run()

if __name__ == "__main__":
    main(sys.argv[1:])
