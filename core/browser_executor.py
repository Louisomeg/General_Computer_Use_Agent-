"""
Browser Executor - the thing that actually controls Chrome
=========================================================
this translates gemini's "click at x,y" calls into real playwright clicks.
its basically the hands of the research agent. gemini says "click there"
and this does the clicking.

implements the same Executor interface as louis's DesktopExecutor so it
plugs straight into the agentic loop without changing anything.

- emmanuel
"""
import time
import sys
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
import playwright.sync_api

from core.executor import Executor

# these match what gemini's computer-use model expects
BROWSER_SCREEN_WIDTH = 1440
BROWSER_SCREEN_HEIGHT = 900

# small delays so pages have time to load after clicks
CLICK_DELAY = 0.3
LOAD_WAIT = 0.5


class BrowserExecutor(Executor):
    """
    controls a playwright chromium browser.
    use it as a context manager so it cleans up after itself:

        with BrowserExecutor() as browser:
            loop.agentic_loop("find M6 bolt specs", browser)
    """

    def __init__(self, screen_width=BROWSER_SCREEN_WIDTH, screen_height=BROWSER_SCREEN_HEIGHT,
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

    # ─── open and close the browser ──────────────────────────────────

    def __enter__(self):
        print("[BrowserExecutor] Starting Playwright ({0}x{1})...".format(
            self.screen_width, self.screen_height))
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            args=["--disable-extensions", "--disable-dev-shm-usage"],
            headless=self.headless,
        )
        self._context = self._browser.new_context(
            viewport={"width": self.screen_width, "height": self.screen_height}
        )
        self._page = self._context.new_page()
        self._page.goto(self.initial_url)

        # if a site opens a new tab, redirect it back to our main page
        # cos gemini can only see one tab at a time
        self._context.on("page", self._handle_new_page)

        print("[BrowserExecutor] Ready at {0}".format(self.initial_url))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            self._playwright.stop()
        print("[BrowserExecutor] Closed.")

    def _handle_new_page(self, new_page):
        """new tab opened? grab the url and redirect our main page there instead."""
        url = new_page.url
        new_page.close()
        self._page.goto(url)

    # ─── the main execute method (called by agentic loop) ────────────
    # gemini sends function calls like click_at(x=500, y=300)
    # and we translate those into real playwright actions

    def execute(self, function_calls) -> list:
        results = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args) if fc.args else {}

            try:
                handler = self._handlers().get(name)
                if handler:
                    result = handler(args)
                else:
                    result = {"error": "Unknown function: {0}".format(name)}
            except Exception as e:
                print("  Error in {0}: {1}".format(name, e))
                result = {"error": str(e)}

            results.append((name, result))
        return results

    def _handlers(self):
        """map of function names to handler methods."""
        return {
            "open_web_browser": self._open_web_browser,
            "click_at": self._click_at,
            "hover_at": self._hover_at,
            "type_text_at": self._type_text_at,
            "scroll_document": self._scroll_document,
            "scroll_at": self._scroll_at,
            "wait_5_seconds": self._wait,
            "go_back": self._go_back,
            "go_forward": self._go_forward,
            "search": self._search,
            "navigate": self._navigate,
            "key_combination": self._key_combination,
            "drag_and_drop": self._drag_and_drop,
            # our custom one — this is how flash tells us its done
            "report_findings": self._report_findings,
        }

    # ─── screenshot (the loop calls this every turn) ─────────────────

    def take_screenshot(self) -> bytes:
        """grab a png of whats on screen. the loop sends this to gemini."""
        self._page.wait_for_load_state()
        time.sleep(LOAD_WAIT)
        return self._page.screenshot(type="png", full_page=False)

    def current_url(self) -> str:
        return self._page.url

    # ─── coordinate helpers ──────────────────────────────────────────
    # gemini sends coordinates as 0-1000 (normalized)
    # we need to convert to actual pixel positions

    def dx(self, x):
        return int(x / 1000 * self.screen_width)

    def dy(self, y):
        return int(y / 1000 * self.screen_height)

    def _ok(self):
        """shorthand for the success response every handler returns."""
        return {"success": True, "url": self._page.url}

    # ─── all the action handlers ─────────────────────────────────────
    # one method per gemini function. most are simple — click, type, scroll.

    def _open_web_browser(self, a):
        return self._ok()

    def _click_at(self, a):
        self._page.mouse.click(self.dx(a["x"]), self.dy(a["y"]))
        self._page.wait_for_load_state()
        time.sleep(CLICK_DELAY)
        return self._ok()

    def _hover_at(self, a):
        self._page.mouse.move(self.dx(a["x"]), self.dy(a["y"]))
        return self._ok()

    def _type_text_at(self, a):
        self._page.mouse.click(self.dx(a["x"]), self.dy(a["y"]))
        self._page.wait_for_load_state()
        # clear the field first unless told not to
        if a.get("clear_before_typing", True):
            mod = "Meta+a" if sys.platform == "darwin" else "Control+a"
            self._page.keyboard.press(mod)
            self._page.keyboard.press("Delete")
        self._page.keyboard.type(a["text"])
        self._page.wait_for_load_state()
        if a.get("press_enter", False):
            self._page.keyboard.press("Enter")
            self._page.wait_for_load_state()
        return self._ok()

    def _scroll_document(self, a):
        d = a["direction"]
        if d == "down":
            self._page.keyboard.press("PageDown")
        elif d == "up":
            self._page.keyboard.press("PageUp")
        elif d in ("left", "right"):
            amt = self.screen_width // 2
            sign = "-" if d == "left" else ""
            self._page.evaluate("window.scrollBy({0}{1}, 0)".format(sign, amt))
        self._page.wait_for_load_state()
        return self._ok()

    def _scroll_at(self, a):
        x, y = self.dx(a["x"]), self.dy(a["y"])
        d = a["direction"]
        mag = a.get("magnitude", 800)
        mag = self.dy(mag) if d in ("up", "down") else self.dx(mag)
        self._page.mouse.move(x, y)
        ddx, ddy = 0, 0
        if d == "up": ddy = -mag
        elif d == "down": ddy = mag
        elif d == "left": ddx = -mag
        elif d == "right": ddx = mag
        self._page.mouse.wheel(ddx, ddy)
        self._page.wait_for_load_state()
        return self._ok()

    def _wait(self, a):
        time.sleep(5)
        return self._ok()

    def _go_back(self, a):
        self._page.go_back()
        self._page.wait_for_load_state()
        return self._ok()

    def _go_forward(self, a):
        self._page.go_forward()
        self._page.wait_for_load_state()
        return self._ok()

    def _search(self, a):
        self._page.goto("https://www.google.com")
        self._page.wait_for_load_state()
        return self._ok()

    def _navigate(self, a):
        url = a["url"]
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url)
        self._page.wait_for_load_state()
        return self._ok()

    def _key_combination(self, a):
        # gemini sends stuff like "control+a" and playwright wants "Control+a"
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
        self._page.mouse.move(self.dx(a["x"]), self.dy(a["y"]))
        self._page.mouse.down()
        time.sleep(0.1)
        self._page.mouse.move(self.dx(a["destination_x"]), self.dy(a["destination_y"]))
        self._page.mouse.up()
        return self._ok()

    # ─── report_findings (our custom function) ───────────────────────
    # this is how gemini tells us "im done, heres what i found"

    def _report_findings(self, a):
        print("[BrowserExecutor] report_findings() called — research complete!")
        self._research_findings = a
        return {"status": "research_complete", "url": self._page.url}

    @property
    def research_findings(self):
        return self._research_findings
