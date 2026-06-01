"""Serve the compiled SvelteKit dashboard (web/build) locally.

A plain static server can't honor the Cloudflare `_redirects` file, so this
tiny server reproduces it:
  * /api/*  -> reverse-proxied to the Python backend (default :8787)
  * /*      -> SPA fallback to index.html for client-side routing

Usage:  python serve_build.py [port] [backend_url]
        python serve_build.py 8788 http://127.0.0.1:8787
"""
import http.server
import os
import socketserver
import sys
import urllib.error
import urllib.request

BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
BACKEND = (sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8787").rstrip("/")
_HOP = {"transfer-encoding", "connection", "content-encoding", "keep-alive"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=BUILD, **k)

    def _proxy(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(BACKEND + self.path, data=body, method=self.command)
        for h in ("Content-Type", "Authorization", "X-Api-Key", "Accept"):
            if h in self.headers:
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload, status, headers = resp.read(), resp.status, resp.getheaders()
        except urllib.error.HTTPError as e:
            payload, status, headers = e.read(), e.code, list(e.headers.items())
        except Exception as e:  # backend down / unreachable
            self.send_error(502, f"backend proxy error: {e}")
            return
        self.send_response(status)
        sent_len = False
        for k, v in headers:
            if k.lower() in _HOP:
                continue
            if k.lower() == "content-length":
                sent_len = True
            self.send_header(k, v)
        if not sent_len:
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        if os.path.isfile(self.translate_path(self.path)):
            return super().do_GET()
        self.path = "/index.html"  # SPA fallback
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        self.send_error(404)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, *a):  # quiet
        pass


def main():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Upgraded dashboard (build) -> http://127.0.0.1:{PORT}")
        print(f"  /api/* proxied to {BACKEND}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
