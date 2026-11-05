"""
Local server for Yorrity SEO Gen (standard library only).

 * Serves the bundled index.html on 127.0.0.1 (stable port => localStorage survives restarts)
 * Provides the CORS-free proxy the web app expects ("?url=" protocol), streaming
   responses so AI "stream: true" output still works.
 * Injects a tiny bridge script (window.native, external links, native Save dialog).
"""
import json
import os
import re
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFERRED_PORT = 47871
OLD_PROXY = "http://localhost:8787/?url="

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailers", "transfer-encoding", "upgrade", "host", "content-length", "origin",
    "referer", "accept-encoding", "cookie", "sec-fetch-site", "sec-fetch-mode",
    "sec-fetch-dest", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
}
SKIP_RESPONSE = {"connection", "keep-alive", "transfer-encoding", "content-length",
                 "content-encoding", "access-control-allow-origin"}

BRIDGE_JS = r"""
<script>
window.native = { version: %(version)s, desktop: true };
(function () {
  function openExternal(u) {
    try {
      var url = new URL(u, location.href);
      if (url.origin === location.origin) return false;
      if (url.protocol !== "http:" && url.protocol !== "https:" && url.protocol !== "mailto:") return false;
      fetch("/__open/%(token)s?u=" + encodeURIComponent(url.href)).catch(function () {});
      return true;
    } catch (e) { return false; }
  }
  window.open = function (u) { openExternal(u); return null; };
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || a.hasAttribute("download")) return;
    if (openExternal(a.href)) e.preventDefault();
  }, true);

  // Native "Save as" dialog for blob downloads (e.g. the .txt export)
  var origClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    var a = this;
    if (a.hasAttribute("download") && /^blob:/.test(a.href) && window.pywebview && window.pywebview.api) {
      var name = a.download || "download.txt";
      fetch(a.href).then(function (r) { return r.blob(); }).then(function (b) {
        var fr = new FileReader();
        fr.onload = function () {
          window.pywebview.api.save_file(name, String(fr.result).split(",")[1] || "");
        };
        fr.readAsDataURL(b);
      });
      return;
    }
    return origClick.apply(a, arguments);
  };
})();
</script>
"""


def _is_private_host(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"      # close-delimited => easy streaming
    server_version = "YorrityLocal/1.0"

    # injected by make_server
    html_bytes = b""
    token = ""
    on_open_external = staticmethod(lambda url: None)

    def log_message(self, *a):          # silence
        pass

    # ---- security: only our own page may talk to us (blocks DNS rebinding / other sites)
    def _host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return _is_private_host(host)

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urllib.parse.urlparse(origin).hostname or ""
        return _is_private_host(host)

    def _deny(self, code=403, msg="Forbidden"):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_PUT(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def do_PATCH(self):
        self._route()

    def _route(self):
        if not self._host_ok() or not self._origin_ok():
            return self._deny()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html") and self.command == "GET":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(self.html_bytes)))
            self.end_headers()
            self.wfile.write(self.html_bytes)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if path == f"/__open/{self.token}":
            url = (qs.get("u") or [""])[0]
            if re.match(r"^(https?://|mailto:)", url, re.I):
                self.on_open_external(url)
            self.send_response(204)
            self.end_headers()
            return

        if path == f"/__proxy/{self.token}":
            target = (qs.get("url") or [""])[0]
            return self._proxy(target)

        self._deny(404, "Not found")

    def _proxy(self, target):
        if not re.match(r"^https?://", target, re.I):
            return self._deny(400, "Bad url")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        headers.setdefault("User-Agent", "Mozilla/5.0 YorrityDesktop")
        req = urllib.request.Request(target, data=body, headers=headers, method=self.command)
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:      # upstream error: pass status + body through
            resp = e
        except Exception as e:                    # network failure
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": f"Proxy error: {e}"}}).encode())
            return

        try:
            self.send_response(resp.status if hasattr(resp, "status") else resp.code)
            for k, v in resp.headers.items():
                if k.lower() not in SKIP_RESPONSE:
                    self.send_header(k, v)
            self.end_headers()
            while True:
                chunk = resp.read(2048) if "text/event-stream" in (resp.headers.get("Content-Type") or "") else resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            resp.close()


def build_html(raw: str, version: str, token: str) -> bytes:
    html = raw
    # route the app's built-in proxy URL to our own, token-protected proxy
    html = html.replace(OLD_PROXY, f"/__proxy/{token}?url=")
    # desktop build: always use the proxy by default (no CORS errors)
    html = html.replace('store.get("yt_proxy", "0")', 'store.get("yt_proxy", "1")')
    bridge = BRIDGE_JS % {"version": json.dumps(version), "token": token}
    if "<head>" in html:
        html = html.replace("<head>", "<head>" + bridge, 1)
    else:
        html = bridge + html
    return html.encode("utf-8")


def _port_free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def make_server(assets_dir, on_open_external=lambda u: None):
    """Returns (server, url). Call server.serve_forever() in a thread."""
    with open(os.path.join(assets_dir, "index.html"), encoding="utf-8") as f:
        raw = f.read()
    try:
        with open(os.path.join(assets_dir, "version.json"), encoding="utf-8") as f:
            version = json.load(f).get("version", "1.0.0")
    except Exception:
        version = "1.0.0"

    token = secrets.token_urlsafe(16)

    class H(Handler):
        pass
    H.html_bytes = build_html(raw, version, token)
    H.token = token
    H.on_open_external = staticmethod(on_open_external)

    port = PREFERRED_PORT if _port_free(PREFERRED_PORT) else 0
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/", token


def start_in_thread(assets_dir, on_open_external=lambda u: None):
    srv, url, token = make_server(assets_dir, on_open_external)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, url
