"""Optional real-browser smoke check. Install playwright separately to use it.

Start scripts/preview.py --port 8765 first. Uses an isolated browser profile.
On macOS, the installed Chrome is used; elsewhere use `playwright install chromium`.
"""
from pathlib import Path
import argparse
import json
import time
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8765")
parser.add_argument("--mobile", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
out = root / "artifacts"
out.mkdir(exist_ok=True)
errors, requests, logs = [], [], []
chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path=str(chrome) if chrome.exists() else None,
                                 args=["--autoplay-policy=no-user-gesture-required"])
    context = browser.new_context(viewport={"width": 1280, "height": 1000}, has_touch=args.mobile, is_mobile=args.mobile)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    def console(message):
        logs.append(f"{message.type}: {message.text}")
        if message.type == "error":
            print("Browser console:", message.text, flush=True)
    page.on("console", console)
    page.on("requestfailed", lambda request: requests.append({"url": request.url, "failure": request.failure}))
    page.goto(args.url, wait_until="domcontentloaded")
    frame = page.frame_locator("#game")
    info = frame.locator("#infobox")
    try:
        def wait_ready():
            # The runtime can start immediately or wait for a user gesture.
            for _ in range(90):
                if frame.locator('#canvas[data-game-ready="true"]').count():
                    break
                if info.is_visible() and "Ліс готовий" in info.inner_text():
                    info.click()
                page.wait_for_timeout(1000)
            expect(frame.locator('#canvas')).to_have_attribute('data-game-ready', 'true', timeout=30000)
            expect(info).to_be_hidden()
            print('Python/WebAssembly game ready.', flush=True)
        wait_ready()
        # Pygame's async loop starts just after the runtime hides its loader.
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "browser-menu.png"), full_page=True)
        canvas = frame.locator("#canvas")
        box = canvas.bounding_box()
        def click(x, y):
            page.mouse.click(box["x"] + box["width"] * x / 1152,
                             box["y"] + box["height"] * y / 720)
        def tap(x, y):
            page.touchscreen.tap(box["x"] + box["width"] * x / 1152,
                                 box["y"] + box["height"] * y / 720)
        if args.mobile:
            tap(250, 514)
            expect(canvas).to_have_attribute('data-screen', 'playing')
            page.wait_for_timeout(200)
            tap(576, 676)  # Touch-only inventory button; absent in desktop HUD.
            expect(canvas).to_have_attribute('data-screen', 'inventory')
            tap(576, 595)
            expect(canvas).to_have_attribute('data-screen', 'playing')
            tap(1075, 590)
            tap(980, 550)
            page.screenshot(path=str(out / 'browser-touch-controls.png'), full_page=True)
            print('Real browser touch events and touch-only controls verified.', flush=True)
        else:
            click(250, 514)
        page.wait_for_timeout(300)
        expect(canvas).to_have_attribute('data-screen', 'playing')
        page.keyboard.down("w")
        page.wait_for_timeout(480)
        page.keyboard.up("w")
        page.keyboard.down("a")
        page.wait_for_timeout(370)
        page.keyboard.up("a")
        page.keyboard.press("e")
        page.wait_for_timeout(250)
        expect(canvas).to_have_attribute('data-screen', 'dialog')
        page.screenshot(path=str(out / "browser-dialog.png"), full_page=True)
        page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        page.wait_for_timeout(250)
        expect(canvas).to_have_attribute('data-screen', 'map')
        page.screenshot(path=str(out / "browser-map.png"), full_page=True)
        page.keyboard.press("Tab")
        page.keyboard.press("i")
        page.wait_for_timeout(200)
        expect(canvas).to_have_attribute('data-screen', 'inventory')
        page.screenshot(path=str(out / "browser-inventory.png"), full_page=True)
        page.keyboard.press("Escape")
        page.keyboard.press("q")
        page.keyboard.press("Shift")
        page.keyboard.press("Space")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "browser-game.png"), full_page=True)
        page.keyboard.press("Escape")
        page.reload(wait_until="domcontentloaded")
        info = frame.locator("#infobox")
        wait_ready()
        page.wait_for_timeout(700)
        page.screenshot(path=str(out / "browser-reloaded.png"), full_page=True)
        # Continue must return to the saved objective, not silently start over.
        page.frame_locator('#game').locator('#canvas').click(position={'x': 190, 'y': 300})
        page.keyboard.press('Enter')
        expect(canvas).to_have_attribute('data-screen', 'playing')
        page.keyboard.press('i')
        expect(canvas).to_have_attribute('data-screen', 'inventory')
        page.screenshot(path=str(out / 'browser-restored-inventory.png'), full_page=True)
        page.keyboard.press('Escape')
        page.get_by_role("button", name="Відкрити гру на весь екран").click()
        page.wait_for_timeout(250)
        page.screenshot(path=str(out / "browser-fullscreen.png"))
        # Browser chrome shortcuts are not guaranteed in headless mode.
        page.evaluate("async () => { if (document.fullscreenElement) await document.exitFullscreen(); }")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(350)
        expect(info).to_be_hidden()
        page.screenshot(path=str(out / "browser-mobile-layout.png"), full_page=True)
        print("Browser startup, input, dialogs, map, reload, fullscreen and responsive page exercised.")
    except Exception:
        page.screenshot(path=str(out / "browser-failure.png"), full_page=True)
        raise
    finally:
        (out / "browser-log.json").write_text(json.dumps({"errors": errors, "requests": requests, "console": logs}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"errors": errors, "failed_requests": requests}, ensure_ascii=False))
        browser.close()
    if errors or requests or any(line.startswith('error:') for line in logs):
        raise SystemExit("Browser JavaScript errors; inspect artifacts/browser-log.json")
