import io
import subprocess

from PIL import Image

from core.settings import SCREENSHOT_PATH, MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT


def capture_desktop_screenshot() -> bytes:
    """Capture the full desktop screen and resize to model-optimal resolution.

    We capture at native resolution (e.g. 1920x1080) with scrot, then resize
    to MODEL_SCREEN_WIDTH x MODEL_SCREEN_HEIGHT (e.g. 1280x720) for the model.

    The Gemini computer-use model outputs coordinates as pixel positions in
    the screenshot image. DesktopExecutor.to_screen_coords() scales these
    back to the native screen resolution for xdotool.
    """
    subprocess.run(["scrot", SCREENSHOT_PATH, "-o"], check=True)

    with Image.open(SCREENSHOT_PATH) as img:
        target = (MODEL_SCREEN_WIDTH, MODEL_SCREEN_HEIGHT)
        if img.size != target:
            img = img.resize(target, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
