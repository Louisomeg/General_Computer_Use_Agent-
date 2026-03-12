import subprocess
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
