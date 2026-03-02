import io
import subprocess

from PIL import Image

from core.settings import SCREENSHOT_PATH, MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT


def capture_desktop_screenshot() -> bytes:
    """Capture the full desktop screen and resize to model-optimal resolution.

    Captures at the VM's native resolution with scrot, then resizes to
    MODEL_SCREEN_WIDTH x MODEL_SCREEN_HEIGHT for the model.  When these
    match the screen dimensions (recommended setup), no resize is needed.

    The Gemini computer-use model outputs coordinates on a 0-1000
    normalized grid regardless of the screenshot resolution.
    DesktopExecutor.denormalize() converts these to actual screen
    pixels for xdotool.
    """
    subprocess.run(["scrot", SCREENSHOT_PATH, "-o"], check=True)

    with Image.open(SCREENSHOT_PATH) as img:
        target = (MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT)
        if img.size != target:
            img = img.resize(target, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
