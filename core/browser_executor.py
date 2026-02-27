"""
Browser Executor — Playwright-based action execution for browser agents.
Parallel to DesktopExecutor. Same Executor interface.
"""
import time
import sys
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
import playwright.sync_api

from core.executor import Executor

BROWSER_WIDTH = 1440
BROWSER_HEIGHT = 900


class BrowserExecutor(Executor):
    """Executes Gemini function calls in a Playwright browser.

    Same Executor interface as DesktopExecutor, plugs into
    AgenticLoop.agentic_loop(prompt, executor).
    """

    def __init__(self, screen_width=BROWSER_WIDTH, screen_height=BROWSER_HEIGHT,
                 initial_url="https://www.google.com", headless=False):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.initial_url = initial_url
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._research_findings = None

    # Context manager 

    def __enter__(self):
        print(f"[BrowserExecutor] Starting Playwright ({self.screen_width}x{self.screen_height})...")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            args=["--disable-extensions", "--disable-dev-shm-usage"],
            headless=self.headless,
        )
        self._context = self._browser.new_context(
            viewport={"width": self.screen_width, "height": self.screen_height},
        )
        self._page = self._context.new_page()
        self._page.goto(self.initial_url, wait_until="domcontentloaded")
        self._context.on("page", self._on_new_page)
        print(f"[BrowserExecutor] Ready at {self.initial_url}")
        return self

    def __exit__(self, *args):
        if self._context:
            self._context.close()
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        if self._playwright:
            self._playwright.stop()
        print("[BrowserExecutor] Closed.")

    def _on_new_page(self, new_page):
        url = new_page.url
        new_page.close()
        if url and url != "about:blank":
            self._page.goto(url, wait_until="domcontentloaded")

    # Screenshot (called by agentic loop each turn) 

    def take_screenshot(self) -> bytes:
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        time.sleep(0.3)
        return self._page.screenshot(type="png", full_page=False)

    def current_url(self) -> str:
        return self._page.url

    # Executor interface 

    def execute(self, function_calls) -> list:
        results = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args) if fc.args else {}
            try:
                handler = self._HANDLERS.get(name)
                result = handler(self, args) if handler else {"error": f"Unknown: {name}"}
            except Exception as e:
                print(f"  [BrowserExecutor] Error {name}: {e}")
                result = {"error": str(e)}
            result.setdefault("url", self._page.url)
            results.append((name, result))
        return results

    # Coordinate helpers

    def _dx(self, x): return int(x / 1000 * self.screen_width)
    def _dy(self, y): return int(y / 1000 * self.screen_height)
    def _ok(self): return {"success": True, "url": self._page.url}
    def _safe_wait(self):
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

    # Predefined Gemini computer-use function handlers 

    def _open_web_browser(self, a):
        return self._ok()

    def _click_at(self, a):
        self._page.mouse.click(self._dx(a["x"]), self._dy(a["y"]))
        self._safe_wait()
        time.sleep(0.3)
        return self._ok()

    def _hover_at(self, a):
        self._page.mouse.move(self._dx(a["x"]), self._dy(a["y"]))
        return self._ok()

    def _type_text_at(self, a):
        self._page.mouse.click(self._dx(a["x"]), self._dy(a["y"]))
        self._safe_wait()
        if a.get("clear_before_typing", True):
            mod = "Meta+a" if sys.platform == "darwin" else "Control+a"
            self._page.keyboard.press(mod)
            self._page.keyboard.press("Delete")
        self._page.keyboard.type(a["text"])
        self._safe_wait()
        if a.get("press_enter", False):
            self._page.keyboard.press("Enter")
            self._safe_wait()
        return self._ok()

    def _scroll_document(self, a):
        d = a["direction"]
        if d == "down": self._page.keyboard.press("PageDown")
        elif d == "up": self._page.keyboard.press("PageUp")
        elif d in ("left", "right"):
            amt = self.screen_width // 2
            sign = "-" if d == "left" else ""
            self._page.evaluate(f"window.scrollBy({sign}{amt}, 0)")
        self._safe_wait()
        return self._ok()

    def _scroll_at(self, a):
        x, y = self._dx(a["x"]), self._dy(a["y"])
        d = a["direction"]
        mag = a.get("magnitude", 800)
        mag = self._dy(mag) if d in ("up", "down") else self._dx(mag)
        self._page.mouse.move(x, y)
        dx, dy = 0, 0
        if d == "up": dy = -mag
        elif d == "down": dy = mag
        elif d == "left": dx = -mag
        elif d == "right": dx = mag
        self._page.mouse.wheel(dx, dy)
        self._safe_wait()
        return self._ok()

    def _wait_5_seconds(self, a):
        time.sleep(5)
        return self._ok()

    def _go_back(self, a):
        self._page.go_back()
        self._safe_wait()
        return self._ok()

    def _go_forward(self, a):
        self._page.go_forward()
        self._safe_wait()
        return self._ok()

    def _search(self, a):
        self._page.goto("https://www.google.com", wait_until="domcontentloaded")
        return self._ok()

    def _navigate(self, a):
        url = a["url"]
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url, wait_until="domcontentloaded")
        return self._ok()

    def _key_combination(self, a):
        KEYMAP = {
            "control": "Control", "alt": "Alt", "shift": "Shift",
            "command": "Meta", "enter": "Enter", "escape": "Escape",
            "backspace": "Backspace", "tab": "Tab", "space": "Space",
            "delete": "Delete",
        }
        keys = [KEYMAP.get(k.lower(), k) for k in a["keys"].split("+")]
        for k in keys[:-1]:
            self._page.keyboard.down(k)
        self._page.keyboard.press(keys[-1])
        for k in reversed(keys[:-1]):
            self._page.keyboard.up(k)
        return self._ok()

    def _drag_and_drop(self, a):
        self._page.mouse.move(self._dx(a["x"]), self._dy(a["y"]))
        self._page.mouse.down()
        time.sleep(0.1)
        self._page.mouse.move(self._dx(a["destination_x"]), self._dy(a["destination_y"]))
        self._page.mouse.up()
        return self._ok()

    # Custom: report_findings 

    def _report_findings(self, a):
        print("[BrowserExecutor] report_findings() called — research complete!")
        self._research_findings = a
        return {"status": "research_complete", "url": self._page.url}

    @property
    def research_findings(self):
        return self._research_findings

    # Handler dispatch table 

    _HANDLERS = {
        "open_web_browser": _open_web_browser,
        "click_at": _click_at,
        "hover_at": _hover_at,
        "type_text_at": _type_text_at,
        "scroll_document": _scroll_document,
        "scroll_at": _scroll_at,
        "wait_5_seconds": _wait_5_seconds,
        "go_back": _go_back,
        "go_forward": _go_forward,
        "search": _search,
        "navigate": _navigate,
        "key_combination": _key_combination,
        "drag_and_drop": _drag_and_drop,
        "report_findings": _report_findings,
    }
