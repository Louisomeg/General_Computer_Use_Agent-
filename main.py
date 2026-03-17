"""
Main entry point — run the planner with a user request.

Usage:
    python main.py                                    # interactive mode
    python main.py "Create a 30mm cube"               # full pipeline (research if needed)
    python main.py --cad "Make a bracket for M6 bolt" # CAD only, skip research
    python main.py --cad --dims hole_diameter=6.6mm wall_thickness=3mm "L-bracket"
    python main.py --claude --cad "Make a bracket"    # use Claude Computer Use backend
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
    """Parse CLI arguments into mode, request, dimensions, and backend.

    Returns:
        (mode, request, dims, backend) where mode is 'full' or 'cad-only',
        request is the task string, dims is a dict, and backend is 'gemini' or 'claude'.
    """
    mode = "full"
    dims = {}
    backend = "gemini"
    remaining = []
    i = 1  # skip argv[0]
    while i < len(argv):
        arg = argv[i]
        if arg in ("--cad", "--cad-only"):
            mode = "cad-only"
        elif arg == "--claude":
            backend = "claude"
        elif arg == "--gemini":
            backend = "gemini"
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
    return mode, request, dims, backend


def main():
    _clear_pycache()

    if len(sys.argv) > 1:
        mode, request, dims, backend = _parse_args(sys.argv)
    else:
        mode, request, dims, backend = "full", "", {}, "gemini"

    # Set backend via environment so agents pick it up
    if backend == "claude":
        os.environ["CAD_BACKEND"] = "claude"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ERROR: Set ANTHROPIC_API_KEY for Claude backend!")
            print('  export ANTHROPIC_API_KEY="your-key"')
            sys.exit(1)
        print("[Main] Using Claude Computer Use backend")
        # Create a dummy client (Claude doesn't need google genai client)
        client = None
    else:
        if not os.environ.get("GEMINI_API_KEY"):
            print("ERROR: Set GEMINI_API_KEY first!")
            print('  export GEMINI_API_KEY="your-key"')
            sys.exit(1)
        client = genai.Client()
        print("[Main] Using Gemini Computer Use backend")

    executor = DesktopExecutor()
    planner = Planner(client, executor, backend=backend)

    if len(sys.argv) > 1:
        if not request:
            print("ERROR: No task description provided.")
            print('  Usage: python main.py "Create a 30mm cube"')
            print('         python main.py --cad "Make a bracket"')
            print('         python main.py --claude --cad "Make a bracket"')
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
