"""Unit tests for the parts that don't need the model or the network.  Run:  python3 -m unittest -v tests/test_hog_alert.py"""
import io, json, os, shutil, sys, tempfile, unittest, unittest.mock as mock

TMP = tempfile.mkdtemp()
os.environ["PVF_DIR"] = TMP
os.environ["HOG_ALERT_ENV"] = f"{TMP}/hog-alert.env"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hog_alert as h


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


class LogicTests(unittest.TestCase):
    def hog(self, c=0.9): return {"hog": True, "confidence": c, "animal": "feral hog", "count": 3}
    def deer(self): return {"hog": False, "confidence": 0.95, "animal": "deer", "count": 0}

    def test_needs_two_confirmations_then_cooldown(self):
        clk = Clock(); L = h.HogLogic(2, 45, 900, 0.7, now=clk)
        self.assertFalse(L.verdict(self.hog()))
        clk.t += 4
        self.assertTrue(L.verdict(self.hog()), "second hog verdict inside the window alerts")
        clk.t += 4
        self.assertFalse(L.verdict(self.hog())); clk.t += 4
        self.assertFalse(L.verdict(self.hog()), "inside cooldown: no re-alert")
        clk.t += 900
        self.assertFalse(L.verdict(self.hog())); clk.t += 4
        self.assertTrue(L.verdict(self.hog()), "after cooldown, two fresh confirmations alert again")

    def test_window_expires(self):
        clk = Clock(); L = h.HogLogic(2, 45, 900, 0.7, now=clk)
        L.verdict(self.hog()); clk.t += 60
        self.assertFalse(L.verdict(self.hog()), "a hit older than the window doesn't count")
        clk.t += 4
        self.assertTrue(L.verdict(self.hog()))

    def test_other_animals_and_low_confidence_never_alert(self):
        clk = Clock(); L = h.HogLogic(1, 45, 0, 0.7, now=clk)
        self.assertFalse(L.verdict(self.deer()))
        self.assertFalse(L.verdict(None))
        self.assertFalse(L.verdict(self.hog(0.5)))
        self.assertTrue(L.verdict(self.hog(0.7)))


class ConfigTests(unittest.TestCase):
    def test_env_file_and_quotes(self):
        with open(os.environ["HOG_ALERT_ENV"], "w") as f:
            f.write('PUSHOVER_TOKEN="abc"\nCOOLDOWN=60\n# comment\nexport FPS=\'3\'\n')
        cfg = h.load_cfg()
        self.assertEqual(cfg["PUSHOVER_TOKEN"], "abc"); self.assertEqual(h.i("COOLDOWN"), 60)
        self.assertEqual(h.f("FPS"), 3.0); self.assertEqual(cfg["CONFIRMATIONS"], "2")


class PushoverTests(unittest.TestCase):
    def setUp(self): h.load_cfg()

    def test_emergency_fields(self):
        fl = h.pushover_fields("Hog", "msg")
        self.assertEqual(fl["priority"], 2); self.assertEqual(fl["retry"], 60); self.assertEqual(fl["expire"], 1800)
        self.assertEqual(fl["url"], "https://pachamamavalleyfarm.com/#hogcam")
        self.assertNotIn("retry", h.pushover_fields("Hog", "msg", priority=0))

    def test_multipart_has_fields_and_image(self):
        body, ctype = h._multipart({"a": "1", "b": "x y"}, "attachment", b"\xff\xd8JPEG")
        self.assertIn("multipart/form-data; boundary=", ctype)
        self.assertIn(b'name="a"\r\n\r\n1\r\n', body); self.assertIn(b'filename="hog.jpg"', body); self.assertIn(b"\xff\xd8JPEG", body)

    def test_dry_run_sends_nothing(self):
        os.environ["DRY_RUN"] = "1"; h.load_cfg()
        with mock.patch("urllib.request.urlopen") as u:
            self.assertTrue(h.pushover("t", "m", b"img")); u.assert_not_called()
        del os.environ["DRY_RUN"]

    def test_missing_keys(self):
        os.environ["DRY_RUN"] = "0"; h.load_cfg(); h.CFG.pop("PUSHOVER_TOKEN", None)
        self.assertFalse(h.pushover("t", "m")); del os.environ["DRY_RUN"]


class ClassifyTests(unittest.TestCase):
    def fake(self, text):
        r = io.BytesIO(json.dumps({"content": [{"type": "text", "text": text}]}).encode())
        r.__enter__ = lambda s: s; r.__exit__ = lambda s, *a: None; return r

    def test_parses_json_and_prose_wrapped_json(self):
        with mock.patch("urllib.request.urlopen", return_value=self.fake('Sure: {"hog": true, "confidence": 0.92, "animal": "feral hog", "count": 2} ok')):
            v = h.classify(b"jpg", model="m", api_key="k")
        self.assertEqual(v, {"hog": True, "confidence": 0.92, "animal": "feral hog", "count": 2})

    def test_bad_reply_is_none(self):
        with mock.patch("urllib.request.urlopen", return_value=self.fake("I cannot tell")):
            self.assertIsNone(h.classify(b"jpg", model="m", api_key="k"))

    def test_sends_image_and_key(self):
        with mock.patch("urllib.request.urlopen", return_value=self.fake('{"hog": false}')) as u:
            h.classify(b"jpgbytes", model="claude-x", api_key="sk-test")
        req = u.call_args[0][0]
        self.assertEqual(req.get_header("X-api-key"), "sk-test")
        body = json.loads(req.data); self.assertEqual(body["model"], "claude-x")
        self.assertEqual(body["messages"][0]["content"][0]["source"]["media_type"], "image/jpeg")


class ImageTests(unittest.TestCase):
    def test_crop_and_hits(self):
        import numpy as np
        frame = np.zeros((720, 1280, 3), dtype=np.uint8); frame[300:400, 500:700] = 200
        crop = h.crop_jpeg(frame, (500, 300, 700, 400, 0.8)); full = h.frame_jpeg(frame)
        self.assertTrue(crop.startswith(b"\xff\xd8") and full.startswith(b"\xff\xd8"))
        base = h.save_hit(full, crop, (500, 300, 700, 400, 0.8), {"hog": True, "confidence": 0.9, "animal": "hog", "count": 1}, True)
        self.assertTrue(os.path.exists(base + "-crop.jpg") and os.path.exists(base + "-frame.jpg"))
        self.assertTrue(json.load(open(base + ".json"))["alerted"])
        old = f"{h.HITS}/20200101"; os.makedirs(old); open(f"{old}/x.json", "w").write("{}")
        os.utime(old, (0, 0)); h.prune_hits(30); self.assertFalse(os.path.exists(old))


class FrameSourceTests(unittest.TestCase):
    def test_reads_frames_from_ffmpeg_test_pattern(self):
        if shutil.which("ffmpeg") is None: self.skipTest("no ffmpeg")
        src = h.FrameSource("testsrc=size=320x180:rate=5", 2, 320, 180)
        src.url = "testsrc=size=320x180:rate=5"
        # lavfi input needs "-f lavfi"; patch the command through subprocess for the test
        real = h.subprocess.Popen
        def popen(cmd, **kw):
            i = cmd.index("-i"); cmd = cmd[:i] + ["-f", "lavfi"] + cmd[i:]; return real(cmd, **kw)
        with mock.patch.object(h.subprocess, "Popen", side_effect=popen):
            f = src.read(); f2 = src.read()
        src.stop()
        self.assertEqual(f.shape, (180, 320, 3)); self.assertEqual(f2.shape, (180, 320, 3))


if __name__ == "__main__":
    unittest.main()
