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


MACRO_LOG_PATH = "/tmp/agent_macro_log.txt"


def execute_freecad_macro(code: str) -> dict:
    """Execute Python code in FreeCAD's Python console via macro file.

    Writes the code to a temporary .py file, wrapped in try/except to
    capture errors.  After execution, reads the log file to check for
    errors and returns them to the agent so it can self-correct.
    """
    macro_path = "/tmp/agent_macro.py"
    try:
        # Wrap user code in try/except that writes errors to a log file.
        # This is the ONLY way to detect FreeCAD Python errors since we
        # execute via xdotool (no stdout/stderr access).
        wrapped_code = (
            "import traceback as _tb\n"
            f"_log = open('{MACRO_LOG_PATH}', 'w')\n"
            "try:\n"
        )
        # Indent each line of user code
        for line in code.splitlines():
            wrapped_code += f"    {line}\n"
        wrapped_code += (
            "    _log.write('OK\\n')\n"
            "except Exception as _e:\n"
            "    _log.write(f'ERROR: {_e}\\n')\n"
            "    _log.write(_tb.format_exc())\n"
            "finally:\n"
            "    _log.close()\n"
        )

        with open(macro_path, "w") as f:
            f.write(wrapped_code)

        # Clear any previous log
        with open(MACRO_LOG_PATH, "w") as f:
            f.write("")

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
        # Give FreeCAD time to execute.  Complex macros (creating multiple
        # features, recomputing shapes) can take several seconds.
        # Scale wait time based on code length as a rough proxy for complexity.
        wait_time = min(2.0 + len(code) / 500, 8.0)
        time.sleep(wait_time)

        # Read the log file to check for errors
        try:
            with open(MACRO_LOG_PATH, "r") as f:
                log_content = f.read().strip()
        except IOError:
            log_content = ""

        if not log_content:
            # Log file empty — macro may not have finished or crashed hard
            return {
                "success": False,
                "warning": "Macro produced no output — it may have crashed or is still running. "
                           "Check the screenshot for error dialogs.",
                "macro_path": macro_path,
            }
        elif log_content.startswith("ERROR:"):
            # Macro raised a Python exception — return the full traceback
            return {
                "error": f"FreeCAD macro error: {log_content}",
                "macro_path": macro_path,
            }
        else:
            return {"success": True, "macro_path": macro_path}

    except subprocess.CalledProcessError as e:
        return {"error": f"Macro execution failed (xdotool): {e}"}
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
