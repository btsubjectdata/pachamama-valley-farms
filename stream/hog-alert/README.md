# Hog alert (stream/hog-alert)

Rings Bradley's phone when a **feral hog** shows up on the Pachamama Valley Farm hog trap camera. Deer, raccoons,
coyotes, dogs and the barn cat do not ring the phone.

Runs on **beehive1** (the Ubuntu mini PC that already relays the farm cameras to YouTube and the website) as the
`pvf-hogalert` systemd service, next to the `pvf-stream` relay from
[pachamama-valley-farms/stream/minipc](https://github.com/btsubjectdata/pachamama-valley-farms/tree/main/stream/minipc).

## How it decides

```
hog cam 720p feed (localhost HLS)  ──2 fps──▶  MegaDetector v6  ──animal?──▶  Claude vision  ──hog?──▶  Pushover
                                              (CPU, trail-cam model)        (crop of the animal)      (emergency push)
```

1. **Frames** come from the relay's own `hog_720.m3u8` on `127.0.0.1:8088`, so there is no extra RTSP session
   against UniFi (a second 4K pull is what made Protect drop sessions on Nov 6).
2. **MegaDetector v6** (Microsoft's trail-camera model, built for IR night footage) runs on the CPU and says whether
   there is an *animal* in the frame. The Intel GPU is untouched; it keeps doing the YouTube encodes.
3. When an animal is present, the largest one is **cropped** (with some context) and sent to **Claude** (Haiku,
   vision) at most once every 4 s, asking "feral hog or not?" with a confidence. That is a handful of API calls per
   animal visit - pennies a month.
4. **Two hog verdicts** (confidence ≥ 0.7) inside **45 s** = one **Pushover emergency push** with the snapshot and a
   link to the hog cam page. It repeats every 60 s until acknowledged (up to 30 min) and gets through Do Not
   Disturb. Then a **15 min cooldown**, so a sounder rooting around is one alert, not forty.
5. Every classified crop and verdict is saved under `/opt/pvf-stream/hog-alert/hits/<date>/` (30 days), so false
   alarms and misses can be reviewed and thresholds tuned - and later a local hog classifier can be trained on it.

All of those numbers live in `/opt/pvf-stream/hog-alert.env` (see `hog-alert.env.example`).

## Install on beehive1

```bash
ssh hiveadmin@100.123.15.47
curl -fsSL https://raw.githubusercontent.com/btsubjectdata/pachamama-valley-farms/main/stream/hog-alert/install.sh | sudo bash
```
(The installer clones this repo to `/opt/pvf-stream/hog-alert/repo` and runs from `stream/hog-alert` there.)

The installer makes a Python venv in `/opt/pvf-stream/hog-alert/venv` (CPU-only PyTorch + Ultralytics, ~1 GB),
downloads the MegaDetector weights, runs a self-test, and starts the service in **dry run** (detects and logs,
sends nothing). Then:

1. `sudo nano /opt/pvf-stream/hog-alert.env` - paste in:
   - `PUSHOVER_TOKEN` - at pushover.net → *Create an Application/API Token* (name it "Hog trap")
   - `PUSHOVER_USER` - your User Key on the pushover.net home page
   - `ANTHROPIC_API_KEY` - console.anthropic.com → API keys
   - set `DRY_RUN="0"`
2. `sudo systemctl restart pvf-hogalert`
3. `sudo pvf-hog test` - normal-priority test push. `sudo pvf-hog test 2` sends an emergency one so you can hear
   what a real alert does (and practice acknowledging it).

## Day to day

| Command | What |
|---|---|
| `sudo pvf-hog` | service state, counters (frames, animals, hogs, alerts), last verdict |
| `sudo pvf-hog log` | follow the log |
| `sudo pvf-hog hits` | today's detections (crop + verdict JSON per animal) |
| `sudo pvf-hog image photo.jpg` | run both stages on one picture - handy to check a screenshot |
| `sudo pvf-hog test [0\|1\|2]` | test push at that priority |
| `sudo pvf-hog update` | pull the latest code and restart |

Log: `/opt/pvf-stream/logs/pvf-hogalert.log` (rotated weekly with the other relay logs).
State for the ops channel: `/opt/pvf-stream/hog-alert/state.json`.

## Tuning

| Symptom | Change in `hog-alert.env` |
|---|---|
| Too many alerts for one visit | raise `COOLDOWN` (seconds) |
| Missed a quick pass-through | `CONFIRMATIONS="1"` or shorter `CLASSIFY_EVERY` |
| False alarms on deer at night | raise `HOG_MIN_CONF` to 0.8–0.85; check `hits/` to see what Claude said |
| Bugs/birds triggering Claude calls | raise `DET_MIN_AREA` (fraction of frame) or `DET_MIN_CONF` |
| CPU too busy | `FPS="1"` or `DET_IMGSZ="640"` |
| Want it quieter at night | `PUSHOVER_PRIORITY="1"` (high, no repeat) - but hogs come at night, so probably not |

## Secrets

`hog-alert.env` is `600`, owned by `pvf`, git-ignored, and never printed. The ops-sync redaction in the main repo
already strips tokens, and `pvf-hogalert` is in its log list, so the service log shows up in the ops channel.

## Tests

`python3 -m unittest -v tests/test_hog_alert.py` - covers the confirm/cooldown logic, Pushover payload, Claude
reply parsing, crop/hit storage and ffmpeg frame reading. The model and the APIs are exercised by `install.sh`
and `pvf-hog test` on the box.

## Later

- Train a small local hog classifier on the saved crops (no API call at all) once there are a few hundred hits.
- A second "all clear / they left" push, or a low-priority "animal but not hog" daily digest.
- Count the sounder and wait for the whole group before alerting (the gate-drop decision).
