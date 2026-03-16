import os
import subprocess
import tempfile
import time

from core.settings import (
    TYPING_DELAY,
    APP_LAUNCH_DELAY,
    SEARCH_TYPE_DELAY,
    CLICK_DELAY,
)


# X11 scroll button numbers for xdotool
SCROLL_BUTTON_MAP = {"up": "4", "down": "5", "left": "6", "right": "7"}


def open_application(app_name: str) -> dict:
    """Launch an application by name using the Ubuntu desktop launcher.

    Presses Super to open Activities, types the app name, presses Enter.
    """
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "super"],
            check=True,
        )
        time.sleep(SEARCH_TYPE_DELAY)
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay",
             str(TYPING_DELAY), app_name],
            check=True,
        )
        time.sleep(SEARCH_TYPE_DELAY)
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "Return"],
            check=True,
        )
        time.sleep(APP_LAUNCH_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def system_click(x: int, y: int) -> dict:
    """Left-click at the given pixel coordinates via xdotool."""
    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(["xdotool", "click", "1"], check=True)
        time.sleep(CLICK_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def system_hover(x: int, y: int) -> dict:
    """Move the mouse to the given pixel coordinates via xdotool."""
    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def right_click(x: int, y: int) -> dict:
    """Right-click at the given pixel coordinates via xdotool."""
    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(["xdotool", "click", "3"], check=True)
        time.sleep(CLICK_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def double_click(x: int, y: int) -> dict:
    """Double-click at the given pixel coordinates via xdotool."""
    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(
            ["xdotool", "click", "--repeat", "2", "--delay", "100", "1"],
            check=True,
        )
        time.sleep(CLICK_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def execute_freecad_macro(code: str) -> dict:
    """Execute Python code in FreeCAD's Python console via macro file.

    Writes the code to a temporary .py file and runs it by typing an
    exec() command into FreeCAD's Python console using xdotool.
    This is more reliable than typing multi-line code directly.
    """
    macro_path = "/tmp/agent_macro.py"
    try:
        # Write the macro code to a temp file
        with open(macro_path, "w") as f:
            f.write(code)

        # Focus the Python console input at the bottom of FreeCAD
        subprocess.run(
            ["xdotool", "mousemove", "640", "780"],
            check=True,
        )
        subprocess.run(["xdotool", "click", "1"], check=True)
        time.sleep(CLICK_DELAY)

        # Clear existing text
        subprocess.run(["xdotool", "key", "ctrl+a"], check=True)
        subprocess.run(["xdotool", "key", "BackSpace"], check=True)
        time.sleep(0.1)

        # Type the command to run the macro file
        # Using a safe, fixed path — no user input in the command
        run_cmd = "exec(open('/tmp/agent_macro.py').read())"
        subprocess.run(
            ["xdotool", "type", "--delay", str(TYPING_DELAY), run_cmd],
            check=True,
        )
        subprocess.run(["xdotool", "key", "Return"], check=True)
        time.sleep(1.0)  # Give FreeCAD time to execute

        return {"success": True, "macro_path": macro_path}
    except subprocess.CalledProcessError as e:
        return {"error": f"Macro execution failed: {e}"}
    except IOError as e:
        return {"error": f"Failed to write macro file: {e}"}


def system_scroll(x: int, y: int, direction: str, clicks: int = 3) -> dict:
    """Scroll at the given pixel coordinates via xdotool.

    direction: "up", "down", "left", "right"
    clicks: number of scroll wheel ticks
    """
    button = SCROLL_BUTTON_MAP.get(direction)
    if not button:
        return {"error": f"Unknown scroll direction: {direction}"}

    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(
            ["xdotool", "click", "--repeat", str(clicks), button],
            check=True,
        )
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}
