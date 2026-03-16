import subprocess
import time

from core.settings import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    ACTION_DELAY,
    TYPING_DELAY,
    CLICK_DELAY,
)
from core import freecad_functions
from core.executor import Executor


class DesktopExecutor(Executor):
    """Executes Gemini computer-use function calls on an Ubuntu desktop via xdotool.

    Handles predefined Gemini functions (click_at, type_text_at, etc.)
    and custom functions (right_click_at, double_click_at, open_application).
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

    # Functions that don't need a post-action UI settling delay
    _NO_DELAY_FUNCTIONS = frozenset({"task_complete", "wait_5_seconds"})

    def __init__(self, screen_width: int = None, screen_height: int = None):
        self.screen_width = screen_width or SCREEN_WIDTH
        self.screen_height = screen_height or SCREEN_HEIGHT
        self._handlers = {
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
            "right_click_at": self._right_click_at,
            "double_click_at": self._double_click_at,
            "execute_freecad_macro": self._execute_freecad_macro,
            # Completion signal
            "task_complete": self._task_complete,
        }

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
            # Strip safety_decision — handled by the agentic loop, not here
            args.pop("safety_decision", None)
            args.pop("safetyDecision", None)
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

            if function_name not in self._NO_DELAY_FUNCTIONS:
                time.sleep(ACTION_DELAY)
            results.append((function_name, result))

        return results

    def _get_handler(self, name: str):
        """Return the handler method for a given function name, or None."""
        return self._handlers.get(name)

    # =========================================================================
    # Predefined function handlers (xdotool implementations)
    # =========================================================================

    def _click_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        return freecad_functions.system_click(x, y)

    def _hover_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        return freecad_functions.system_hover(x, y)

    def _type_text_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        text = args["text"]
        press_enter = args.get("press_enter", True)
        clear_before = args.get("clear_before_typing", True)

        # Click to focus the input field
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(["xdotool", "click", "1"], check=True)
        time.sleep(CLICK_DELAY)

        # Optionally clear existing text
        if clear_before:
            subprocess.run(["xdotool", "key", "ctrl+a"], check=True)
            subprocess.run(["xdotool", "key", "BackSpace"], check=True)

        # Type the text
        subprocess.run(
            ["xdotool", "type", "--delay", str(TYPING_DELAY), text],
            check=True,
        )

        # Optionally press Enter
        if press_enter:
            subprocess.run(["xdotool", "key", "Return"], check=True)

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
        "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
        "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
        "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
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
        result = subprocess.run(
            ["xdotool", "key", keys],
            capture_output=True, text=True,
        )
        # xdotool returns 0 even when it can't find a key name, but prints
        # a warning to stderr. Detect this and report the error to the model.
        if result.returncode != 0:
            return {"error": f"xdotool failed: {result.stderr.strip()}"}
        if "No such key name" in result.stderr:
            return {"error": f"Invalid key '{args['keys']}': {result.stderr.strip()}"}
        return {"success": True}

    def _scroll_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        direction = args["direction"]
        magnitude = args.get("magnitude", 500)
        # Convert magnitude (0-1000) to scroll wheel clicks (1-10)
        scroll_clicks = max(1, int(magnitude / 100))
        return freecad_functions.system_scroll(x, y, direction, scroll_clicks)

    def _scroll_document(self, args: dict) -> dict:
        center_x = self.screen_width // 2
        center_y = self.screen_height // 2
        return freecad_functions.system_scroll(center_x, center_y, args["direction"], 5)

    def _drag_and_drop(self, args: dict) -> dict:
        start_x, start_y = self.denormalize(args["x"], args["y"])
        end_x, end_y = self.denormalize(args["destination_x"], args["destination_y"])

        subprocess.run(
            ["xdotool", "mousemove", str(start_x), str(start_y)],
            check=True,
        )
        subprocess.run(["xdotool", "mousedown", "1"], check=True)
        time.sleep(0.1)
        subprocess.run(
            ["xdotool", "mousemove", "--sync", str(end_x), str(end_y)],
            check=True,
        )
        subprocess.run(["xdotool", "mouseup", "1"], check=True)
        return {"success": True}

    def _wait(self, args: dict) -> dict:
        time.sleep(5)
        return {"success": True}

    # =========================================================================
    # Custom function handlers (delegate to freecad_functions)
    # =========================================================================

    def _right_click_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        return freecad_functions.right_click(x, y)

    def _double_click_at(self, args: dict) -> dict:
        x, y = self.denormalize(args["x"], args["y"])
        return freecad_functions.double_click(x, y)

    def _execute_freecad_macro(self, args: dict) -> dict:
        code = args.get("code", "")
        if not code:
            return {"error": "No code provided"}
        return freecad_functions.execute_freecad_macro(code)

    def _task_complete(self, args: dict) -> dict:
        summary = args.get("summary", "Task completed")
        print(f"  [Task Complete] {summary}")
        return {"status": "task_complete", "summary": summary}
