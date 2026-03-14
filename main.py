"""
Main entry point — run the planner with a user request.

Usage:
    python main.py                          # interactive mode
    python main.py "Create a 30mm cube"     # direct CAD task
    python main.py "Research M6 bolt specs" # direct research task
"""
import os
import shutil
import sys

from google import genai

from core.agentic_planner import Planner
from core.desktop_executor import DesktopExecutor


def _clear_pycache():
    """Remove all __pycache__ dirs to prevent stale .pyc warnings."""
    root = os.path.dirname(os.path.abspath(__file__))
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)


def main():
    _clear_pycache()

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: Set GEMINI_API_KEY first!")
        print('  export GEMINI_API_KEY="your-key"')
        sys.exit(1)

    client = genai.Client()
    executor = DesktopExecutor()
    planner = Planner(client, executor)

    if len(sys.argv) > 1:
        # Direct mode: pass the request as a CLI argument
        request = " ".join(sys.argv[1:])
        planner.run(request)
    else:
        # Interactive mode
        print("Agentic Planner — type a request or 'quit' to exit\n")
        while True:
            try:
                request = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if not request or request.lower() in ("quit", "exit", "q"):
                break
            planner.run(request)


if __name__ == "__main__":
    main()
