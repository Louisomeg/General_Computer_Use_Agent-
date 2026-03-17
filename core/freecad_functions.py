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


def _find_freecad_console_y():
    """Find the Python console input Y position inside FreeCAD.

    Searches for the FreeCAD window, gets its geometry, and calculates
    where the Python console input line should be (near the bottom of
    the window, above the status bar).

    Returns the screen Y coordinate, or None if FreeCAD is not found.
    """
    try:
        result = subprocess.run(
            ["xdotool", "search", "--name", "FreeCAD"],
            capture_output=True, text=True, timeout=5,
        )
        window_ids = [w for w in result.stdout.strip().split('\n') if w]
        if not window_ids:
            return None

        window_id = window_ids[-1]  # Main window is usually last

        # Get window geometry
        geo = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", window_id],
            capture_output=True, text=True, timeout=5,
        )
        vals = {}
        for line in geo.stdout.strip().split('\n'):
            if '=' in line:
                k, v = line.split('=', 1)
                try:
                    vals[k] = int(v)
                except ValueError:
                    vals[k] = v

        win_y = vals.get('Y', 0)
        win_h = vals.get('HEIGHT', 800)

        # Python console input is near the bottom of FreeCAD window.
        # Layout from top: menu(~25) + toolbar(~35) + 3D viewport +
        # model tree | properties | python console + status bar(~22)
        # The console input line is typically ~30-40px from bottom.
        console_y = win_y + win_h - 35
        return console_y
    except (subprocess.SubprocessError, OSError):
        return None


def _focus_freecad_window():
    """Focus the FreeCAD window and return True if successful."""
    try:
        result = subprocess.run(
            ["xdotool", "search", "--name", "FreeCAD"],
            capture_output=True, text=True, timeout=5,
        )
        window_ids = [w for w in result.stdout.strip().split('\n') if w]
        if not window_ids:
            return False

        window_id = window_ids[-1]
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", window_id],
            check=True, timeout=5,
        )
        time.sleep(0.3)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def execute_freecad_macro(code):
    """Run Python code in FreeCAD's Python console via macro file.

    Writes the code to a temporary .py file, wrapped in try/except to
    capture errors.  Focuses the FreeCAD Python console dynamically
    (not at hardcoded coordinates) and pastes the run command.
    After running, reads the log file to check for errors.
    """
    macro_path = "/tmp/agent_macro.py"
    try:
        # Wrap user code in try/except that writes errors to a log file.
        wrapped_code = (
            "import traceback as _tb\n"
            f"_log = open('{MACRO_LOG_PATH}', 'w')\n"
            "try:\n"
        )
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

        # Focus FreeCAD window first
        if not _focus_freecad_window():
            return {"error": "FreeCAD window not found. Is FreeCAD running?"}

        # Find the Python console Y position dynamically
        console_y = _find_freecad_console_y()
        if console_y is None:
            console_y = 760  # Fallback: 40px from bottom of 800px screen

        # Click the Python console input line
        # Use center X of screen (FreeCAD is usually maximized)
        console_x = 640
        subprocess.run(
            ["xdotool", "mousemove", str(console_x), str(console_y)],
            check=True,
        )
        subprocess.run(["xdotool", "click", "1"], check=True)
        time.sleep(CLICK_DELAY)

        # Clear existing text in the console input
        subprocess.run(["xdotool", "key", "ctrl+a"], check=True)
        subprocess.run(["xdotool", "key", "BackSpace"], check=True)
        time.sleep(0.1)

        # Build the command to run the macro file
        # NOTE: This uses Python's exec() to run a file inside FreeCAD's
        # embedded Python console — this is the standard FreeCAD macro
        # execution pattern and is intentional.
        run_cmd = "exec(open('" + macro_path + "').read())"

        # Try xclip paste first (faster), fall back to xdotool type
        pasted = False
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=run_cmd.encode(), check=True, timeout=3,
            )
            subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
            pasted = True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass  # xclip not installed or failed

        if not pasted:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay",
                 str(TYPING_DELAY), run_cmd],
                check=True,
            )

        subprocess.run(["xdotool", "key", "Return"], check=True)

        # Wait for FreeCAD to run the macro. Scale by code complexity.
        wait_time = min(2.0 + len(code) / 500, 8.0)
        time.sleep(wait_time)

        # Read the log file to check for errors
        try:
            with open(MACRO_LOG_PATH, "r") as f:
                log_content = f.read().strip()
        except IOError:
            log_content = ""

        if not log_content:
            return {
                "success": False,
                "warning": "Macro produced no output — it may have crashed or is still running. "
                           "Check the screenshot for error dialogs. "
                           "TIP: The Python console input may not be focused. "
                           "Try clicking the bottom area of FreeCAD first, then retry.",
                "macro_path": macro_path,
            }
        elif log_content.startswith("ERROR:"):
            return {
                "error": f"FreeCAD macro error: {log_content}",
                "macro_path": macro_path,
            }
        else:
            return {"success": True, "macro_path": macro_path}

    except subprocess.CalledProcessError as e:
        return {"error": f"Macro failed (xdotool): {e}"}
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
