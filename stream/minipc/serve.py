#!/usr/bin/env python3
"""Read-only server (also serves status.json from the watchdog) for the bee yard HLS files. Bound to localhost; only the
Cloudflare Tunnel reaches it. Serves bees.m3u8 and bees_NNNNNN.ts, nothing else."""
import os, re
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT = "/opt/pvf-stream/hls"
OK = re.compile(r"^/(bees\.m3u8|bees_\d{6}\.ts|status\.json)$")
class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health"):
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
            self.wfile.write(b"ok"); return
        if not OK.match(path): self.send_error(404); return
        self.path = path; return super().do_GET()
    def do_HEAD(self): self.do_GET()
    def do_POST(self): self.send_error(405)
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        if self.path.endswith((".m3u8", ".json")): self.send_header("Cache-Control", "no-cache, no-store")
        elif self.path.endswith(".ts"): self.send_header("Cache-Control", "public, max-age=20")
        super().end_headers()
    def guess_type(self, p):
        return "application/vnd.apple.mpegurl" if p.endswith(".m3u8") else ("video/mp2t" if p.endswith(".ts") else super().guess_type(p))
    def log_message(self, *a): pass
os.makedirs(ROOT, exist_ok=True)
ThreadingHTTPServer(("127.0.0.1", 8088), H).serve_forever()
