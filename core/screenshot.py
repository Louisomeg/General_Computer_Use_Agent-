import subprocess

from core.settings import SCREENSHOT_PATH


def capture_desktop_screenshot() -> bytes:
    """Capture the full desktop screen using scrot and return PNG bytes.

    The agent loop calls this after each action round to send the current
    screen state to Gemini as a FunctionResponseBlob.
    """
    subprocess.run(["scrot", SCREENSHOT_PATH, "-o"], check=True)
    with open(SCREENSHOT_PATH, "rb") as f:
        return f.read()
