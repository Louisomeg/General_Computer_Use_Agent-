import io
import subprocess
import time
from typing import Optional

import pyautogui
from PIL import Image

from core import freecad_functions
from core.executor import Executor
from core.screenshot import capture_desktop_screenshot
from core.settings import (ACTION_DELAY, CLICK_DELAY, MODEL_SCREEN_HEIGHT,
                           MODEL_SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_WIDTH,
                           SCREENSHOT_PATH, TYPING_DELAY)


class DesktopExecutor(Executor):
    """Executes Gemini computer-use function calls on an Ubuntu desktop via xdotool.

    Handles both predefined Gemini functions (click_at, type_text_at, etc.)
    and custom functions (system_shortcut, freecad_shortcut, etc.).
    All actions are performed through xdotool subprocess calls.

    Coordinate mapping:
        The Gemini computer-use model outputs coordinates on a normalized
        0-1000 grid (x and y each range from 0 to ~999). These are
        proportional to the screenshot the model sees, regardless of its
        pixel dimensions.  We denormalize them to the actual screen
        resolution (SCREEN_WIDTH x SCREEN_HEIGHT) before sending to xdotool.

        Formula:  screen_x = int(normalized_x / 1000 * SCREEN_WIDTH)

        Google recommends a display resolution of 1440x900 for best results.
        The closest available VM resolution is 1280x800 (same 16:10 aspect).
    """

    def __init__(
        self, screen_width: Optional[int] = None, screen_height: Optional[int] = None
    ):
        self.screen_width = screen_width or SCREEN_WIDTH
        self.screen_height = screen_height or SCREEN_HEIGHT

    def denormalize(self, x: int, y: int) -> tuple:
        """Convert normalized 0-1000 coordinates to actual screen pixels.

        The Gemini computer-use model outputs coordinates on a 1000x1000 grid
        regardless of the screenshot resolution. We scale these to the actual
        screen resolution for xdotool.

        Example: x=500 on a 1280-wide screen → 500/1000 * 1280 = 640 (center).
        """
        screen_x = int(x / 1000 * self.screen_width)
        screen_y = int(y / 1000 * self.screen_height)
        print(f"     Coords: normalized({x}, {y}) -> screen({screen_x}, {screen_y})")
        return screen_x, screen_y

    def screenshot(self) -> bytes:
        # 1. Capture screenshot directly into a PIL Image object
        img = pyautogui.screenshot()

        # 2. Resize to the model's expected dimensions if necessary
        target = (MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT)
        if img.size != target:
            img = img.resize(target, Image.Resampling.LANCZOS)

        # 3. Save to a memory buffer instead of the disk
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        # 4. Return the raw bytes for the API request
        return buf.getvalue()

    def execute(self, function_calls) -> list:
        """Execute a list of function calls from a Gemini response.

        Args:
            function_calls: List of function call objects, each with
                .name (str) and .args (dict-like).

        Returns:
            List of (function_name, result_dict) tuples.
        """
        results = []

        for fc in function_calls:
            function_name = fc.name
            args = dict(fc.args) if fc.args else {}
            print(f"  -> Executing: {function_name}({args})")

            try:
                handler = self._get_handler(function_name)
                if handler:
                    result = handler(args)
                else:
                    print(f"  Warning: Unknown function '{function_name}'")
                    result = {"error": f"Unknown function: {function_name}"}
            except Exception as e:
                print(f"  Error executing {function_name}: {e}")
                result = {"error": str(e)}

            time.sleep(ACTION_DELAY)
            result["url"] = "local://desktop"
            results.append((function_name, result))

        return results

    def _get_handler(self, name: str):
        """Return the handler method for a given function name, or None."""
        handlers = {
            # Predefined Gemini functions (desktop via xdotool)
            "click_at": self._click_at,
            "hover_at": self._hover_at,
            "type_text_at": self._type_text_at,
            "key_combination": self._key_combination,
            "scroll_at": self._scroll_at,
            "scroll_document": self._scroll_document,
            "drag_and_drop": self._drag_and_drop,
            "wait_5_seconds": self._wait,
            # Custom functions
            "system_shortcut": self._system_shortcut,
            "freecad_shortcut": self._freecad_shortcut,
            "right_click_at": self._right_click_at,
            "double_click_at": self._double_click_at,
            "open_application": self._open_application,
            "open_freecad": self._open_freecad,
            # Completion signal
            "task_complete": self._task_complete,
        }
        return handlers.get(name)

    # =========================================================================
    # Predefined function handlers (xdotool implementations)
    # =========================================================================

    def _click_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        pyautogui.click(x, y)
        return {"success": True}

    def _hover_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        pyautogui.moveTo(x, y)
        return {"success": True}

    def _type_text_at(self, args: dict) -> dict:
        text = args["text"]
        press_enter: bool = args.get("press_enter", True)
        clear_before: bool = args.get("clear_before_typing", True)

        self._click_at(args)

        # Optionally clear existing text
        if clear_before:
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")

        # Type the text
        pyautogui.write(text)

        # Optionally press Enter
        if press_enter:
            pyautogui.press("enter")

        return {"success": True}

    # Map of common lowercase key names the model sends → X11 keysym names
    # xdotool requires proper keysym capitalization; lowercase variants are
    # silently ignored (exit 0 + warning to stderr), which breaks the agent.
    _KEY_ALIASES = {
        "delete": "Delete",
        "escape": "Escape",
        "return": "Return",
        "enter": "Return",
        "backspace": "BackSpace",
        "tab": "Tab",
        "space": "space",
        "shift": "Shift_L",
        "ctrl": "Control_L",
        "alt": "Alt_L",
        "super": "Super_L",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "home": "Home",
        "end": "End",
        "pageup": "Page_Up",
        "page_up": "Page_Up",
        "pagedown": "Page_Down",
        "page_down": "Page_Down",
        "insert": "Insert",
        "f1": "F1",
        "f2": "F2",
        "f3": "F3",
        "f4": "F4",
        "f5": "F5",
        "f6": "F6",
        "f7": "F7",
        "f8": "F8",
        "f9": "F9",
        "f10": "F10",
        "f11": "F11",
        "f12": "F12",
    }

    def _normalize_key(self, key: str) -> str:
        """Normalize a single key name to its X11 keysym equivalent."""
        return self._KEY_ALIASES.get(key.strip(), key.strip())

    def _normalize_keys(self, keys: str) -> str:
        """Normalize a key combination string like 'ctrl+delete' or 'shift+a'.

        Handles '+' separated combos (ctrl+shift+delete) and single keys.
        """
        parts = keys.split("+")
        normalized = [self._normalize_key(p) for p in parts]
        return "+".join(normalized)

    def _key_combination(self, args: dict) -> dict:
        keys = self._normalize_keys(args["keys"])
        keys = keys.split("+")
        pyautogui.hotkey(*keys)
        return {"success": True}

    def _scroll_at(self, args: dict) -> dict:
        # 1. Denormalize coordinates from 1000x1000 grid
        x, y = self.denormalize(args["x"], args["y"])

        direction = args["direction"]
        # 2. Handle magnitude with default if missing
        magnitude = args.get("magnitude", 800)

        # normalize magnitude for standard scroll behavior
        scroll_clicks = int(magnitude / 100)

        # 3. Directional logic
        if direction == "up":
            pyautogui.vscroll(scroll_clicks, x=x, y=y)
        elif direction == "down":
            pyautogui.vscroll(-scroll_clicks, x=x, y=y)
        elif direction == "right":
            pyautogui.hscroll(scroll_clicks, x=x, y=y)
        elif direction == "left":
            pyautogui.hscroll(-scroll_clicks, x=x, y=y)

        return {"success": True}

    def _scroll_document(self, args: dict) -> dict:
        # scroll_document usually maps to the entire viewport
        # We delegate to scroll_at using the center of the screen (500, 500)
        # as a sensible default for global page scrolling.
        return self._scroll_at(
            {
                "x": 500,
                "y": 500,
                "direction": args["direction"],
                "magnitude": args.get("magnitude", 800),
            }
        )

    def _drag_and_drop(self, args: dict) -> dict:
        start_x, start_y = self.denormalize(args["x"], args["y"])
        end_x, end_y = self.denormalize(args["destination_x"], args["destination_y"])

        # 1. Move to start
        pyautogui.moveTo(start_x, start_y)

        # 2. Click and hold (Essential for the GUI to register the 'grab')
        pyautogui.mouseDown()

        # 3. Short pause to ensure the UI 'latches' onto the item
        time.sleep(0.5)

        # 4. Drag to target
        pyautogui.moveTo(end_x, end_y, duration=0.5)

        # 5. Short pause to ensure the UI registers the target zone
        time.sleep(0.5)

        # 6. Drop
        pyautogui.mouseUp()
        return {"success": True}

    def _wait(self, _args: dict) -> dict:
        time.sleep(5)
        return {"success": True}

    # =========================================================================
    # Custom function handlers (delegate to freecad_functions)
    # =========================================================================

    def _system_shortcut(self, args: dict) -> dict:
        return freecad_functions.execute_system_shortcut(args["shortcut_name"])

    def _freecad_shortcut(self, args: dict) -> dict:
        return freecad_functions.execute_freecad_shortcut(args["shortcut_name"])

    def _right_click_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        return freecad_functions.right_click(x, y)

    def _double_click_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        return freecad_functions.double_click(x, y)

    def _open_freecad(self, _args: dict) -> dict:
        return freecad_functions.open_freecad()

    def _open_application(self, args: dict) -> dict:
        return freecad_functions.open_application(args["name"])

    def _task_complete(self, args: dict) -> dict:
        summary = args.get("summary", "Task completed")
        print(f"  [Task Complete] {summary}")
        return {"status": "task_complete", "summary": summary}
