import subprocess
import time


def execute_system_shortcut(shortcut_name):
    print(f"  -> System shortcut: {shortcut_name}")

    shortcuts = {
        "super": "super",
        "alt_f2": "alt+F2",
        "super_tab": "super+Tab",
        "super_backtick": "super+grave",
        "alt_escape": "alt+Escape",
        "ctrl_alt_tab": "ctrl+alt+Tab",
        "super_a": "super+a",
        "super_page_up": "super+Prior",
        "super_page_down": "super+Next",
        "shift_super_page_up": "shift+super+Prior",
        "shift_super_page_down": "shift+super+Next",
        "shift_super_left": "shift+super+Left",
        "shift_super_right": "shift+super+Right",
        "ctrl_alt_delete": "ctrl+alt+Delete",
        "super_l": "super+l",
        "super_v": "super+v",
        "select_all": "ctrl+a",
        "cut": "ctrl+x",
        "copy": "ctrl+c",
        "paste": "ctrl+v",
        "undo": "ctrl+z",
        "terminal_copy": "ctrl+shift+c",
        "terminal_paste": "ctrl+shift+v",

        "screenshot": "Print",
        "screenshot_window": "alt+Print",
        "screenshot_full": "shift+Print",
        "screencast_toggle": "shift+ctrl+alt+r",
    }

    keys = shortcuts.get(shortcut_name)
    if not keys:
        print(f"  Warning: Unknown shortcut '{shortcut_name}'")
        return {"error": f"Unknown shortcut: {shortcut_name}"}

    try:
        subprocess.run(["xdotool", "key", keys], check=True)
        time.sleep(0.5)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        print(f"  Error executing shortcut: {e}")
        return {"error": str(e)}


def type_system_text(text):
    try:
        subprocess.run(["xdotool", "type", "--delay", "50", text], check=True)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def system_click(x, y):
    try:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True)
        subprocess.run(["xdotool", "click", "1"], check=True)
        time.sleep(0.3)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def open_application(app_name):
    try:
        subprocess.run(["xdotool", "key", "super"], check=True)
        time.sleep(1)
        subprocess.run(["xdotool", "type", "--delay", "50", app_name], check=True)
        time.sleep(1)
        subprocess.run(["xdotool", "key", "Return"], check=True)
        time.sleep(2)
        return {"success": True}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}


def take_screenshot(output_path="/tmp/screen.png"):
    try:
        subprocess.run(["scrot", output_path, "-o"], check=True)
        return {"success": True, "path": output_path}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}