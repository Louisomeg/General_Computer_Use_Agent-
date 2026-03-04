"""
Main entry point — run the planner with a user request.

Usage:
    python main.py                          # interactive mode
    python main.py "Create a 30mm cube"     # direct CAD task
    python main.py "Research M6 bolt specs" # direct research task
"""

import sys

from google import genai

from core.agentic_planner import Planner
from core.desktop_executor import DesktopExecutor


def main():
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
            try:
                planner.run(request)
            except Exception as e:
                print(e)
                break
        client.close()


if __name__ == "__main__":
    main()
