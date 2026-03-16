#!/usr/bin/env python3
"""
Run the agent with environment setup and pre-flight checks.

Usage:
    python scripts/run_agent.py "Make a bracket for an M6 bolt"
    python scripts/run_agent.py                    # interactive mode
    python scripts/run_agent.py --check            # pre-flight checks only
"""
import os
import subprocess
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def load_env():
    """Load environment variables from .env file if it exists."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and value:
                        os.environ.setdefault(key, value)


def preflight_checks() -> list:
    """Run pre-flight checks and return a list of errors."""
    errors = []

    # Check API key
    if not os.environ.get("GEMINI_API_KEY"):
        errors.append(
            "GEMINI_API_KEY not set. "
            "Run: export GEMINI_API_KEY='your-key' "
            "or add it to .env file"
        )

    # Check DISPLAY (needed for xdotool/scrot)
    if not os.environ.get("DISPLAY"):
        errors.append(
            "DISPLAY not set. Agent requires X11. "
            "Run: export DISPLAY=:0"
        )

    # Check critical system commands
    for cmd in ("xdotool", "scrot"):
        try:
            subprocess.run(
                [cmd, "--version"],
                capture_output=True, timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            errors.append(
                f"{cmd} not found. "
                f"Install with: sudo apt install -y {cmd}"
            )

    # Check Python dependencies
    try:
        import google.genai  # noqa: F401
    except ImportError:
        errors.append(
            "google-genai not installed. "
            "Run: pip install -r requirements.txt"
        )

    # Check display resolution
    if not errors:
        try:
            result = subprocess.run(
                ["xdotool", "getdisplaygeometry"],
                capture_output=True, text=True, timeout=5,
            )
            geometry = result.stdout.strip()
            if geometry and geometry != "1280 800":
                errors.append(
                    f"Display resolution is {geometry}, expected 1280 800. "
                    f"Update SCREEN_WIDTH/SCREEN_HEIGHT in core/settings.py "
                    f"or change resolution with xrandr."
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Already caught above

    return errors


def clean_pycache():
    """Remove stale __pycache__ directories."""
    import shutil
    for dirpath, dirnames, _ in os.walk(PROJECT_ROOT):
        for d in dirnames:
            if d == "__pycache__":
                shutil.rmtree(
                    os.path.join(dirpath, d), ignore_errors=True
                )


def main():
    load_env()

    # --check flag: just run pre-flight checks
    if "--check" in sys.argv:
        errors = preflight_checks()
        if errors:
            print("Pre-flight check FAILED:")
            for e in errors:
                print(f"  x {e}")
            sys.exit(1)
        else:
            print("All pre-flight checks passed")
            sys.exit(0)

    # Run pre-flight checks
    errors = preflight_checks()
    if errors:
        print("Pre-flight check failed:")
        for e in errors:
            print(f"  x {e}")
        print("\nFix the issues above or run with --check to re-verify.")
        sys.exit(1)

    # Clean pycache
    clean_pycache()

    # Build the request from CLI args (excluding script name and flags)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    request = " ".join(args) if args else None

    # Import and run
    from google import genai
    from core.agentic_planner import Planner
    from core.desktop_executor import DesktopExecutor

    client = genai.Client()
    executor = DesktopExecutor()
    planner = Planner(client, executor)

    if request:
        planner.run(request)
    else:
        print("Agentic Planner — type a request or 'quit' to exit\n")
        while True:
            try:
                req = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if not req or req.lower() in ("quit", "exit", "q"):
                break
            planner.run(req)


if __name__ == "__main__":
    main()
