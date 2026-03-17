"""
Project-level configuration loader.

Loads settings from .env file (if present) and exposes them as module-level
constants.  Falls back to defaults from core/settings.py when env vars are
not set.

Usage:
    from config import GEMINI_API_KEY, SCREEN_WIDTH
"""
import os


def _load_dotenv():
    """Load .env file into os.environ (no external dependency needed)."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    os.environ.setdefault(key, value)


_load_dotenv()

# API key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Display settings (override core/settings.py defaults via env)
SCREEN_WIDTH = int(os.environ.get("SCREEN_WIDTH", "1280"))
SCREEN_HEIGHT = int(os.environ.get("SCREEN_HEIGHT", "800"))
MODEL_SCREEN_WIDTH = int(os.environ.get("MODEL_SCREEN_WIDTH", "1440"))
MODEL_SCREEN_HEIGHT = int(os.environ.get("MODEL_SCREEN_HEIGHT", "900"))
