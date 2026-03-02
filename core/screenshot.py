import io
import subprocess

from PIL import Image

from core.settings import SCREENSHOT_PATH, MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT


def capture_desktop_screenshot() -> bytes:
    """Capture the full desktop screen and resize to model-optimal resolution.

    Google's Gemini computer-use model is optimized for 1440x900 screenshots.
    We capture at native resolution with scrot, then resize for the model.
    Coordinates are normalized 0-999, so resizing doesn't affect coordinate
    mapping — the denormalization in DesktopExecutor uses actual screen dims.
    """
    subprocess.run(["scrot", SCREENSHOT_PATH, "-o"], check=True)

    with Image.open(SCREENSHOT_PATH) as img:
        target = (MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT)
        if img.size != target:
            img = img.resize(target, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
