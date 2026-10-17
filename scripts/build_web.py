"""Build only the game sources/assets and produce a Netlify Drop archive.

No npm, server, API keys, or Netlify account are needed to build.
The browser downloads the version-pinned pygame-web WebAssembly runtime.
"""
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build" / "echo-forest"
DIST = ROOT / "dist"


def make_icon(path):
    # A tiny original crystal icon, encoded with the standard library.
    rows = bytearray()
    for y in range(32):
        rows.append(0)
        for x in range(32):
            crystal = abs(x - 16) / 10 + abs(y - 16) / 13 < 1
            rows.extend((168, 215, 151, 255) if crystal else (20, 37, 39, 255))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


def build():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)
    for name in ("main.py", "RPG_Game.py", "rpg_core.py"):
        shutil.copy2(ROOT / name, STAGE / name)
    shutil.copytree(ROOT / "assets", STAGE / "assets")
    make_icon(STAGE / "favicon.png")
    subprocess.run([sys.executable, "-m", "pygbag", "--build", "--no_opt",
                    "--title", "Ліс відлунь", "--app_name", "echo-forest",
                    "--package", "games.echo.forest", "--width", "1152", "--height", "720",
                    "--can_close", "1",
                    "--template", str(ROOT / "web" / "runtime.tmpl"),
                    "--icon", str(STAGE / "favicon.png"), str(STAGE)], check=True, cwd=ROOT)
    game_output = STAGE / "build" / "web"
    if not (game_output / "index.html").is_file() or not (list(game_output.glob("*.apk")) or list(game_output.glob("*.tar.gz"))):
        raise SystemExit("Pygbag did not produce a complete web build.")
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(game_output, DIST / "game")
    for name in ("index.html", "style.css", "app.js", "favicon.svg", "_headers"):
        shutil.copy2(ROOT / "web" / name, DIST / name)
    shutil.copytree(ROOT / "assets" / "fonts", DIST / "fonts")
    shutil.copytree(ROOT / "web" / "vendor", DIST / "vendor")
    shutil.copy2(ROOT / "web" / "PYGBAG-LICENSE.txt", DIST / "game" / "PYGBAG-LICENSE.txt")
    shutil.make_archive(str(ROOT / "netlify-deploy"), "zip", DIST)
    size = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    print(f"\nReady: {DIST} ({size / 1024 / 1024:.1f} MB)")
    print("Drag dist/ into https://app.netlify.com/drop")
    print("Archive: netlify-deploy.zip")
    print("Local preview: python -m http.server 8000 --directory dist")


if __name__ == "__main__":
    build()
