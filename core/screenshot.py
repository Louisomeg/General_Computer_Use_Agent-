import io
import subprocess

from core.settings import SCREENSHOT_PATH, MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT

# When screen and model dimensions match, skip PIL decode/encode entirely.
_NEEDS_RESIZE = (MODEL_SCREEN_WIDTH != SCREEN_WIDTH or MODEL_SCREEN_HEIGHT != SCREEN_HEIGHT)

if _NEEDS_RESIZE:
    from PIL import Image


def capture_desktop_screenshot() -> bytes:
    """Capture the full desktop screen and resize to model-optimal resolution.

    Captures at the VM's native resolution with scrot, then resizes to
    MODEL_SCREEN_WIDTH x MODEL_SCREEN_HEIGHT for the model.  When these
    match the screen dimensions (recommended setup), the raw PNG bytes
    are returned directly without PIL decode/encode.

    The Gemini computer-use model outputs coordinates on a 0-1000
    normalized grid regardless of the screenshot resolution.
    DesktopExecutor.denormalize() converts these to actual screen
    pixels for xdotool.
    """
    subprocess.run(["scrot", SCREENSHOT_PATH, "-o"], check=True)

    if not _NEEDS_RESIZE:
        with open(SCREENSHOT_PATH, "rb") as f:
            return f.read()

    with Image.open(SCREENSHOT_PATH) as img:
        img = img.resize((MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
