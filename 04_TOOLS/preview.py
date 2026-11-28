"""Local preview: no deployment, no database, no bot."""
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import webbrowser
class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
root = Path(__file__).resolve().parents[1] / "02_MINI_APP" / "public"
with ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root))) as server:
    url = f"http://127.0.0.1:{server.server_port}/?build=0080-editorial"
    print("LUMI 008.0 EDITORIAL — " + url, flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
