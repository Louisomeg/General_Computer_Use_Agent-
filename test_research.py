"""
quick way to test the research agent from the command line.
run this from the repo root folder.

examples:
  python test_research.py --quick
  python test_research.py --query "M6 bolt dimensions" --max-turns 20
  python test_research.py --parallel --query "drone frame materials"
  python test_research.py --pdf              # generate pdf from last run
  python test_research.py --pdf "outputs/research_results/some_file.json"
"""
import argparse
import os
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Test the Research Agent")
    parser.add_argument("--query", type=str, default=None, help="What to research")
    parser.add_argument("--max-turns", type=int, default=20, help="Max browser turns (default 20)")
    parser.add_argument("--headless", action="store_true", help="Run browser without visible window")
    parser.add_argument("--quick", action="store_true", help="Quick test: simple query, 8 turns")
    parser.add_argument("--engineering", action="store_true", help="Engineering preset: 25 turns")
    parser.add_argument("--plan-only", action="store_true", help="Just show the plan, dont browse")
    parser.add_argument("--parallel", action="store_true", help="Run multiple browsers at once")
    parser.add_argument("--workers", type=int, default=3, help="Parallel workers (default 3)")
    parser.add_argument("--turns-per-worker", type=int, default=12, help="Turns per worker (default 12)")
    parser.add_argument("--pdf", type=str, nargs="?", const="latest", help="Generate PDF from JSON results")
    args = parser.parse_args()

    # pdf mode doesnt need an api key
    if args.pdf:
        from agents.research_agent import ResearchAgent
        agent = ResearchAgent(None)
        if args.pdf == "latest":
            agent.generate_pdf()
        else:
            import json
            result = json.loads(Path(args.pdf).read_text())
            agent.generate_pdf(result)
        return

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: Set GEMINI_API_KEY first!")
        print('  PowerShell: $env:GEMINI_API_KEY="your-key"')
        print('  Linux:      export GEMINI_API_KEY="your-key"')
        sys.exit(1)

    from google import genai
    from agents.research_agent import ResearchAgent

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    agent = ResearchAgent(client)

    # figure out the query
    if args.quick:
        query = args.query or "boiling point of water at sea level"
        max_turns = 8
    elif args.engineering:
        query = args.query or "standard bicycle handlebar clamp diameter ISO 4210"
        max_turns = 25
    else:
        query = args.query or "M6 bolt head dimensions DIN 933"
        max_turns = args.max_turns

    print(f"\nQuery: {query}")
    print(f"Mode: {'parallel' if args.parallel else 'single'}")
    print(f"Turns: {max_turns if not args.parallel else f'{args.workers} x {args.turns_per_worker}'}")
    print()

    if args.plan_only:
        plan = agent.plan_research(query)
        print("\nDone — plan only, no browsing.")
        return

    if args.parallel:
        result = agent.run_parallel(
            query=query,
            num_workers=args.workers,
            turns_per_worker=args.turns_per_worker,
            headless=args.headless,
        )
    else:
        result = agent.run(
            query=query,
            max_turns=max_turns,
            headless=args.headless,
        )

    # quick summary
    f = result["findings"]
    print(f"\n{'='*50}")
    print(f"DONE — {f['confidence']} confidence")
    print(f"Data points: {len(f['data_points'])}")
    print(f"Sites: {len(f['sources'])}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
