import subprocess
import time

from core.settings import (
    UBUNTU_SHORTCUTS,
    FREECAD_SHORTCUTS,
    TYPING_DELAY,
    SHORTCUT_DELAY,
    FREECAD_SEQUENCE_DELAY,
    APP_LAUNCH_DELAY,
    SEARCH_TYPE_DELAY,
    CLICK_DELAY,
)


def execute_system_shortcut(shortcut_name: str) -> dict:
    """Execute an Ubuntu desktop keyboard shortcut by name.

    Looks up the shortcut in UBUNTU_SHORTCUTS and fires it via xdotool.
    """
    entry = UBUNTU_SHORTCUTS.get(shortcut_name)
    if not entry:
        return {"error": f"Unknown Ubuntu shortcut: {shortcut_name}"}

    try:
        subprocess.run(["xdotool", "key", entry["keys"]], check=True)
        time.sleep(SHORTCUT_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def execute_freecad_shortcut(shortcut_name: str) -> dict:
    """Execute a FreeCAD keyboard shortcut by name.

    Handles both single-key shortcuts (str) and two-key sequences (list).
    For sequences like ["g", "l"], presses each key with a delay between them.
    """
    entry = FREECAD_SHORTCUTS.get(shortcut_name)
    if not entry:
        return {"error": f"Unknown FreeCAD shortcut: {shortcut_name}"}

    keys = entry["keys"]

    try:
        if isinstance(keys, list):
            for key in keys:
                subprocess.run(["xdotool", "key", key], check=True)
                time.sleep(FREECAD_SEQUENCE_DELAY)
        else:
            subprocess.run(["xdotool", "key", keys], check=True)
        time.sleep(SHORTCUT_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def open_application(app_name: str) -> dict:
    """Launch an application by name using the Ubuntu desktop launcher.

    Presses Super to open Activities, types the app name, presses Enter.
    """
    try:
        subprocess.run(["xdotool", "key", "super"], check=True)
        time.sleep(SEARCH_TYPE_DELAY)
        subprocess.run(
            ["xdotool", "type", "--delay", str(TYPING_DELAY), app_name],
            check=True,
        )
        time.sleep(SEARCH_TYPE_DELAY)
        subprocess.run(["xdotool", "key", "Return"], check=True)
        time.sleep(APP_LAUNCH_DELAY)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def type_system_text(text: str) -> dict:
    """Type text at the current cursor position via xdotool."""
    try:
        subprocess.run(
            ["xdotool", "type", "--delay", str(TYPING_DELAY), text],
            check=True,
        )
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


def system_scroll(x: int, y: int, direction: str, clicks: int = 3) -> dict:
    """Scroll at the given pixel coordinates via xdotool.

    direction: "up", "down", "left", "right"
    clicks: number of scroll wheel ticks
    Button mapping: 4=up, 5=down, 6=left, 7=right
    """
    button_map = {"up": "4", "down": "5", "left": "6", "right": "7"}
    button = button_map.get(direction)
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
