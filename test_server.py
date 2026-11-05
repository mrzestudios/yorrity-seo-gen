"""Offline test of the local server + proxy (stdlib only)."""
import json, os, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
import server

class Up(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps({"echo": json.loads(body), "auth": self.headers.get("Authorization")}).encode())
    def do_GET(self):
        if self.path == "/sse":
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for i in range(3): self.wfile.write(f"data: {i}\n\n".encode()); self.wfile.flush()
        else:
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"error":"bad key"}')

up = HTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
UP = f"http://127.0.0.1:{up.server_address[1]}"
opened = []
srv, url, token = server.make_server(os.path.join(os.path.dirname(__file__), "assets"), opened.append)
threading.Thread(target=srv.serve_forever, daemon=True).start()

page = urllib.request.urlopen(url).read().decode()
assert "window.native" in page and "8787" not in page and f"/__proxy/{token}?url=" in page
assert 'store.get("yt_proxy", "1")' in page
print("page injected OK, version:", "1.0.0" in page)

def call(path, data=None, headers=None, method=None):
    r = urllib.request.Request(url.rstrip("/") + path, data=data, headers=headers or {}, method=method)
    return urllib.request.urlopen(r)

q = urllib.parse.quote
r = call(f"/__proxy/{token}?url=" + q(UP + "/v1/chat"), json.dumps({"a": 1}).encode(),
         {"Authorization": "Bearer k", "Content-Type": "application/json"})
j = json.loads(r.read()); assert j == {"echo": {"a": 1}, "auth": "Bearer k"}, j
print("POST proxy OK")
assert b"data: 2" in call(f"/__proxy/{token}?url=" + q(UP + "/sse")).read(); print("SSE stream OK")
try: call(f"/__proxy/{token}?url=" + q(UP + "/x")); raise SystemExit("expected 401")
except urllib.error.HTTPError as e: assert e.code == 401 and b"bad key" in e.read(); print("upstream error passthrough OK")
for bad in (f"/__proxy/wrong?url=" + q(UP), f"/__proxy/{token}?url=" + q("file:///etc/passwd")):
    try: call(bad); raise SystemExit("should fail")
    except urllib.error.HTTPError as e: print("blocked", e.code)
try: call("/", headers={"Host": "evil.com"}); raise SystemExit("host check failed")
except urllib.error.HTTPError as e: print("bad Host blocked", e.code)
try: call("/", headers={"Origin": "https://evil.com"}); raise SystemExit("origin check failed")
except urllib.error.HTTPError as e: print("foreign Origin blocked", e.code)
call(f"/__open/{token}?u=" + q("https://example.com")); call(f"/__open/{token}?u=" + q("file:///c:/x"))
assert opened == ["https://example.com"], opened; print("external-link bridge OK")
print("ALL PASSED")
