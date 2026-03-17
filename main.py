"""
Main entry point — run the planner with a user request.

Usage:
    python main.py                                    # interactive mode
    python main.py "Create a 30mm cube"               # full pipeline (research if needed)
    python main.py --cad "Make a bracket for M6 bolt" # CAD only, skip research
    python main.py --cad --dims hole_diameter=6.6mm wall_thickness=3mm "L-bracket"
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


def _parse_args(argv):
    """Parse CLI arguments into mode, request, and optional dimensions.

    Returns:
        (mode, request, dims) where mode is 'full' or 'cad-only',
        request is the task string, and dims is a dict of dimensions.
    """
    mode = "full"
    dims = {}
    remaining = []
    i = 1  # skip argv[0]
    while i < len(argv):
        arg = argv[i]
        if arg in ("--cad", "--cad-only"):
            mode = "cad-only"
        elif arg == "--dims":
            # Consume all following key=value pairs until next flag or end
            i += 1
            while i < len(argv) and "=" in argv[i] and not argv[i].startswith("--"):
                k, v = argv[i].split("=", 1)
                dims[k.strip()] = v.strip()
                i += 1
            continue  # Don't increment i again
        else:
            remaining.append(arg)
        i += 1

    request = " ".join(remaining) if remaining else ""
    return mode, request, dims


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
        mode, request, dims = _parse_args(sys.argv)
        if not request:
            print("ERROR: No task description provided.")
            print('  Usage: python main.py "Create a 30mm cube"')
            print('         python main.py --cad "Make a bracket"')
            sys.exit(1)

        if mode == "cad-only":
            planner.run_cad_only(request, dims)
        else:
            planner.run(request)
    else:
        # Interactive mode
        print("Agentic Planner — type a request or 'quit' to exit")
        print("  Prefix with --cad to skip research\n")
        while True:
            try:
                request = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break
            if not request or request.lower() in ("quit", "exit", "q"):
                break
            if request.startswith("--cad "):
                planner.run_cad_only(request[6:].strip(), {})
            else:
                planner.run(request)


if __name__ == "__main__":
    main()
