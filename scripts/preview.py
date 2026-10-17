"""Serve the finished browser build; double-clicking HTML cannot run WASM."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / "dist"
if not (root / "index.html").exists():
    raise SystemExit("Спершу зберіть гру: python scripts/build_web.py")
server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(SimpleHTTPRequestHandler, directory=str(root)))
print(f"Ліс відлунь: http://127.0.0.1:{args.port}", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
