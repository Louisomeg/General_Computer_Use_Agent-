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

    Handles both predefined Gemini functions (click_at, type_text_at, etc.)
    and custom functions (system_shortcut, freecad_shortcut, etc.).
    All actions are performed through xdotool subprocess calls.
    """

    def __init__(self, screen_width: int = None, screen_height: int = None):
        self.screen_width = screen_width or SCREEN_WIDTH
        self.screen_height = screen_height or SCREEN_HEIGHT

    def denormalize(self, value: int, screen_dimension: int) -> int:
        """Convert a 0-999 normalized coordinate to actual pixel coordinate."""
        return int(value / 1000 * screen_dimension)

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
        }
        return handlers.get(name)

    # =========================================================================
    # Predefined function handlers (xdotool implementations)
    # =========================================================================

    def _click_at(self, args: dict) -> dict:
        x = self.denormalize(args["x"], self.screen_width)
        y = self.denormalize(args["y"], self.screen_height)
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(["xdotool", "click", "1"], check=True)
        time.sleep(CLICK_DELAY)
        return {"success": True}

    def _hover_at(self, args: dict) -> dict:
        x = self.denormalize(args["x"], self.screen_width)
        y = self.denormalize(args["y"], self.screen_height)
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        return {"success": True}

    def _type_text_at(self, args: dict) -> dict:
        x = self.denormalize(args["x"], self.screen_width)
        y = self.denormalize(args["y"], self.screen_height)
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

    def _key_combination(self, args: dict) -> dict:
        keys = args["keys"]
        subprocess.run(["xdotool", "key", keys], check=True)
        return {"success": True}

    def _scroll_at(self, args: dict) -> dict:
        x = self.denormalize(args["x"], self.screen_width)
        y = self.denormalize(args["y"], self.screen_height)
        direction = args["direction"]
        magnitude = args.get("magnitude", 500)

        # Convert magnitude (0-1000) to scroll wheel clicks (1-10)
        scroll_clicks = max(1, int(magnitude / 100))

        button_map = {"up": "4", "down": "5", "left": "6", "right": "7"}
        button = button_map.get(direction)
        if not button:
            return {"error": f"Unknown scroll direction: {direction}"}

        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(
            ["xdotool", "click", "--repeat", str(scroll_clicks), button],
            check=True,
        )
        return {"success": True}

    def _scroll_document(self, args: dict) -> dict:
        direction = args["direction"]
        # Scroll at screen center with default magnitude
        center_x = self.screen_width // 2
        center_y = self.screen_height // 2

        button_map = {"up": "4", "down": "5", "left": "6", "right": "7"}
        button = button_map.get(direction)
        if not button:
            return {"error": f"Unknown scroll direction: {direction}"}

        subprocess.run(
            ["xdotool", "mousemove", str(center_x), str(center_y)],
            check=True,
        )
        subprocess.run(
            ["xdotool", "click", "--repeat", "5", button],
            check=True,
        )
        return {"success": True}

    def _drag_and_drop(self, args: dict) -> dict:
        start_x = self.denormalize(args["x"], self.screen_width)
        start_y = self.denormalize(args["y"], self.screen_height)
        end_x = self.denormalize(args["destination_x"], self.screen_width)
        end_y = self.denormalize(args["destination_y"], self.screen_height)

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

    def _system_shortcut(self, args: dict) -> dict:
        return freecad_functions.execute_system_shortcut(args["shortcut_name"])

    def _freecad_shortcut(self, args: dict) -> dict:
        return freecad_functions.execute_freecad_shortcut(args["shortcut_name"])

    def _right_click_at(self, args: dict) -> dict:
        x = self.denormalize(args["x"], self.screen_width)
        y = self.denormalize(args["y"], self.screen_height)
        return freecad_functions.right_click(x, y)

    def _double_click_at(self, args: dict) -> dict:
        x = self.denormalize(args["x"], self.screen_width)
        y = self.denormalize(args["y"], self.screen_height)
        return freecad_functions.double_click(x, y)

    def _open_application(self, args: dict) -> dict:
        return freecad_functions.open_application(args["name"])
