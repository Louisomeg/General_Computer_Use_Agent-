"""
Emmanuel's Research Agent
========================
so basically this is a browser bot that does research for you.
you give it a question like "what are M6 bolt dimensions" and it
literally opens chrome, goes to google, clicks links, reads pages,
and comes back with actual data + the URLs where it found everything.

i use two models:
- gemini 3 pro for planning (its smarter but costs more so i only call it once)
- gemini 3 flash for actually driving the browser (way cheaper per turn)

theres also a parallel mode where it opens like 3 browsers at once
and each one researches a different part of the question. louis's
manager wanted more websites covered so thats what this does.

last updated: 27 feb 2026 - emmanuel
"""
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google import genai

from agents.registry import register
from core.agentic_loop import AgenticLoop, REPORT_FINDINGS_DECLARATION
from core.browser_executor import BrowserExecutor
from core.models import Task, TaskStatus

# documentation agent runs after us to make proper reports
try:
    from agents.documentation_agent import DocumentationAgent
    HAS_DOC_AGENT = True
except ImportError:
    HAS_DOC_AGENT = False


# pro is the smart one, flash is the fast one.
# we only hit pro once for planning cos its expensive.
# flash does all the actual browsing.
PLANNING_MODEL = "gemini-3-pro-preview"
BROWSER_MODEL = "gemini-3-flash-preview"

# this prompt took me ages to get right honestly. every line is here
# cos without it the model does something stupid. like it would just
# sit on wikipedia scrolling forever. or it would hit a captcha and
# freeze up. or find the answer then keep searching instead of reporting.
# if you change anything in here, TEST IT because it will break.
RESEARCH_PROMPT = """You are a Research Agent — a specialised research assistant that uses a web browser to find accurate, verified technical information. You are methodical, thorough, and never guess.

=== RESEARCH METHODOLOGY ===

PHASE 1 — UNDERSTAND THE QUERY
Before doing anything, break the query into parts:
- What specific data points are being asked for? (dimensions, materials, standards, specifications)
- What domain does this fall under? (mechanical engineering, electronics, materials science, etc.)
- What units and precision are expected?

PHASE 2 — PLAN YOUR SEARCHES
Do NOT just type the raw user question into Google. Construct targeted search queries:
- Use technical terminology (e.g., "ISO 4210 bicycle handlebar diameter" not "how wide are handlebars")
- Search for standards bodies first (ISO, ANSI, ASTM, DIN)
- Then search manufacturer specifications
- Then search reputable engineering references (Engineering Toolbox, MatWeb, etc.)
- Last resort: forums and wikis (verify claims independently)

PHASE 3 — EXECUTE RESEARCH
For each sub-question in your research plan:
1. Navigate to Google or directly to a known high-quality source
2. Enter a well-formed search query
3. Click through to actual pages — do NOT rely on search result snippets alone
4. READ the page content carefully. Scroll down if needed.
5. Extract specific data points with their units
6. Note the URL as a source
7. Move to the next source and cross-reference

PHASE 4 — VERIFY AND CROSS-REFERENCE
- Every key data point must appear in at least 2 independent sources
- If sources disagree, note the discrepancy and which source is more authoritative
- Standards body > manufacturer spec > academic paper > engineering reference > forum

PHASE 5 — REPORT
When you have sufficient data (or have exhausted reasonable sources), call report_findings() with your structured results. Do not keep searching indefinitely — know when you have enough.

=== SEARCH STRATEGY RULES ===
1. Start with the most specific query possible
2. If results are poor, broaden the query
3. Never search the same query twice
4. Try different search engines (bing.com, duckduckgo.com) or direct URLs if Google is unhelpful
5. Prefer .edu, .gov, .org, and manufacturer domains over random blogs
6. If a page has a table of specifications, that is high-value data — read it carefully
7. If a page returns 404 or loads badly, go BACK and try the next link in the search results
8. Scroll through the search result hyperlinks and pick the best-looking ones before clicking

=== OBSTACLE HANDLING PROTOCOL ===

CAPTCHA Handling:
- Simple checkbox ("I am not a robot"): Click it once. Wait 3 seconds for the result.
- If an image puzzle appears (select traffic lights, buses, crosswalks, etc.):
  TRY TO SOLVE IT ONCE. Look at the images carefully, click the correct ones, then click Verify.
  If it gives you a second puzzle or says "try again", STOP. Go back immediately.
  Do NOT attempt more than one round of image puzzles.
- Cloudflare "checking your browser" page: Wait 5 seconds for it to resolve.
  If still blocked after waiting, go back. If blocked twice on same domain, abandon it.
- If Google itself keeps blocking you after one CAPTCHA attempt, switch to bing.com or duckduckgo.com.
- Strategy: Google first -> if blocked, try CAPTCHA once -> if still blocked, Bing -> if Bing blocked, DuckDuckGo -> if all blocked, navigate directly to known websites from your plan.

Cookie/Consent Banners:
- Look for buttons labeled: "Accept All", "Accept", "OK", "I Agree", "Got it", "Allow All"
- Click the accept/agree button to dismiss the banner
- If no clear accept button, look for an "X" or close button
- Then continue with your research — do not get stuck on banners

Popups and Modals:
- Newsletter signup popups: Look for "X", "Close", "No thanks", "Maybe later" — click it
- Login walls: DO NOT attempt to log in. Go back immediately. Try a different source.
- Paywalls: GO BACK immediately. Try a different source.
- Age verification: Only click "Yes" / "I am over 18" if the research requires it
- Any other modal blocking content: Try pressing Escape key, or look for close button

Page Load Failures:
- If a page shows an error (404, 500, timeout): Go back to search results
- If a page is blank or loads incorrectly: Go back and try the next result
- Never spend more than 2 attempts on a single problematic page

=== OUTPUT FORMAT ===
When you have gathered enough information, call the report_findings function with these arguments:
- summary: A clear paragraph summarising all findings
- data_points: Array of objects, each with fact, value, unit, source
- sources: List of all URLs visited
- confidence: "high", "medium", or "low"
- gaps: List of things you could NOT find

Confidence levels:
- HIGH: All key data points confirmed by 2+ independent sources
- MEDIUM: Most data found but some points only have 1 source
- LOW: Significant gaps, conflicting sources, or limited results

=== CRITICAL RULES ===
1. NEVER fabricate data. If you cannot find something, say so in the gaps list.
2. NEVER guess dimensions, specifications, or material properties.
3. ALWAYS note your sources — every data point needs a URL.
4. ALWAYS call report_findings() when done. Do not just stop.
5. If you are running low on turns, call report_findings() with partial results.
6. Be efficient — 2-3 good sources is enough for most facts.
7. Prioritise structured data (tables, spec sheets) over prose.
"""

# all json results and pdf reports go here
OUTPUT_DIR = Path("outputs/research_results")


@register("research")
class ResearchAgent:
    """
    the main agent. give it a question, it goes and browses for you.

    normal:   agent.run("M6 bolt dimensions", max_turns=20)
    parallel: agent.run_parallel("drone materials", num_workers=3)
    pdf only: agent.generate_pdf()  # uses last run's results

    via registry:
        agent = get_agent("research", client=client)
        task = Task(description="Find M6 bolt dimensions")
        agent.execute(task)
    """

    def __init__(self, client: genai.Client):
        self.client = client
        self.research_plan = None   # gets set when we call plan_research
        self.findings = None        # gets set after the browser does its thing

    def execute(self, task: Task) -> Task:
        """Standard agent interface — run research from a Task object."""
        task.status = TaskStatus.WORKING
        try:
            max_turns = task.params.get("max_turns", 20)
            headless = task.params.get("headless", False)
            result = self.run(task.description, max_turns=max_turns, headless=headless)
            task.complete(
                result=result["findings"].get("summary", "Research complete"),
                artifacts=[result],
            )
        except Exception as e:
            task.fail(error=str(e))
        return task

    # ─── PLANNING ────────────────────────────────────────────────────────
    # this part is cheap — just one text call to pro, no browser involved.
    # pro figures out what to search for so flash doesnt waste turns
    # typing dumb queries into google.

    def plan_research(self, query: str) -> str:
        """ask gemini pro to make a plan. returns sub-questions + search queries."""
        print(f"\n{'='*60}")
        print(f"PLANNING with {PLANNING_MODEL}")
        print(f"Query: {query}")
        print(f"{'='*60}")

        prompt = f"""You are a research planning assistant. Create a focused research plan.

QUERY: {query}

Respond ONLY with this format:

SUB-QUESTIONS:
1. [specific data point to find]
2. [specific data point to find]
3. [specific data point to find]

SEARCH QUERIES (4 different phrasings, use technical terms):
- [targeted search query 1]
- [different angle query 2]
- [more specific query 3]
- [alternative phrasing query 4]

BEST WEBSITES TO CHECK DIRECTLY:
- [URL of authoritative source]
- [URL of another good source]
- [URL of a third source]

DONE WHEN:
- [criteria including "data from 2-3 independent sources"]"""

        try:
            resp = self.client.models.generate_content(model=PLANNING_MODEL, contents=prompt)
            print(f"\nPlan:\n{resp.text}")
            return resp.text
        except Exception as e:
            # pro crashed or rate limited — no big deal, we have a backup plan
            print(f"Planning failed ({e}), using a basic fallback plan")
            return (f"SUB-QUESTIONS:\n1. Key specs for {query}\n2. Relevant standards\n3. Typical values\n\n"
                    f"SEARCH QUERIES:\n- {query} specifications\n- {query} technical data sheet\n"
                    f"- {query} ISO standard\n- {query} engineering reference\n\n"
                    f"BEST WEBSITES TO CHECK DIRECTLY:\n"
                    f"- https://en.wikipedia.org\n- https://www.engineeringtoolbox.com\n"
                    f"- https://www.engineersedge.com\n\n"
                    f"DONE WHEN:\n- Data confirmed from 2-3 sources")

    # ─── SINGLE BROWSER RUN ─────────────────────────────────────────────
    # the standard mode. one browser, one question, does everything start to finish.
    # this is what runs when you dont pass --parallel

    def run(self, query: str, max_turns: int = 20, headless: bool = False) -> dict:
        """open one browser, do the research, save json + pdf."""
        start = time.time()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # get a plan from pro first
        self.research_plan = self.plan_research(query)

        # now hand it to flash with the browser and let it do its thing
        full_prompt = (
            f"RESEARCH TASK: {query}\n\n"
            f"RESEARCH PLAN:\n{self.research_plan}\n\n"
            f"Execute this plan now. Start searching. If Google blocks you, "
            f"use bing.com or duckduckgo.com. Visit multiple different websites. "
            f"If a page is broken or blocked, go back and try the next search result. "
            f"Call report_findings() when you have enough data."
        )

        print(f"\n{'='*60}")
        print(f"BROWSING with {BROWSER_MODEL} (max {max_turns} turns)")
        print(f"{'='*60}\n")

        turns_used = 0
        try:
            with BrowserExecutor(headless=headless) as browser:
                loop = AgenticLoop(
                    client=self.client,
                    model_name=BROWSER_MODEL,
                    system_instruction=RESEARCH_PROMPT,
                    screenshot_fn=browser.take_screenshot,
                    extra_declarations=[REPORT_FINDINGS_DECLARATION],
                    max_turns=max_turns,
                    use_browser_environment=True,
                )
                loop.agentic_loop(full_prompt, browser)
                self.findings = browser.research_findings
                turns_used = loop.turn_count
        except Exception as e:
            # browser crashed or api died — save whatever we got
            print(f"something went wrong: {e}")
            self.findings = {
                "summary": f"Research got interrupted: {str(e)[:200]}",
                "data_points": [], "sources": [],
                "confidence": "low", "gaps": ["research was cut short by an error"],
            }

        # package it all up into a nice dict
        findings = self.findings or {}
        result = {
            "query": query,
            "research_plan": self.research_plan,
            "findings": {
                "summary": findings.get("summary", "No findings."),
                "data_points": findings.get("data_points", []),
                "sources": findings.get("sources", []),
                "confidence": findings.get("confidence", "low"),
                "gaps": findings.get("gaps", []),
            },
            "metadata": {
                "status": "complete" if findings.get("data_points") else "incomplete",
                "planning_model": PLANNING_MODEL,
                "browser_model": BROWSER_MODEL,
                "turns_used": turns_used,
                "max_turns": max_turns,
                "elapsed_seconds": round(time.time() - start, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        self._save(result)
        self._display(result)
        self.generate_pdf(result)
        self._run_doc_agent(result)
        return result

    # ─── PARALLEL MODE ───────────────────────────────────────────────────
    # the cool bit. instead of one browser doing everything sequentially,
    # we split the question into parts and open multiple browsers at once.
    # each one handles a different sub-topic. way more websites get visited
    # in the same amount of wall-clock time.
    #
    # the manager said we werent hitting enough websites — well now we are.

    def _run_single_worker(self, sub_query, worker_id, max_turns, headless, results_list):
        """
        one thread, one browser, one sub-question.
        dont call this yourself — run_parallel handles the threading.
        """
        print(f"\n[Worker {worker_id}] Starting: {sub_query}")

        # each worker tracks its own stuff independently
        worker_result = {
            "sub_query": sub_query,
            "worker_id": worker_id,
            "data_points": [],
            "sources": [],
            "gaps": [],
            "summary": "",
            "confidence": "low",
            "turns_used": 0,
        }

        try:
            prompt = (
                f"RESEARCH TASK: {sub_query}\n\n"
                f"Find this specific information. Visit 2-3 websites. "
                f"If Google blocks you, use bing.com or duckduckgo.com. "
                f"Call report_findings() when you have the data."
            )
            with BrowserExecutor(headless=headless) as browser:
                loop = AgenticLoop(
                    client=self.client,
                    model_name=BROWSER_MODEL,
                    system_instruction=RESEARCH_PROMPT,
                    screenshot_fn=browser.take_screenshot,
                    extra_declarations=[REPORT_FINDINGS_DECLARATION],
                    max_turns=max_turns,
                    use_browser_environment=True,
                )
                loop.agentic_loop(prompt, browser)

                # pull out whatever this worker found
                findings = browser.research_findings or {}
                worker_result["data_points"] = findings.get("data_points", [])
                worker_result["sources"] = findings.get("sources", [])
                worker_result["gaps"] = findings.get("gaps", [])
                worker_result["summary"] = findings.get("summary", "")
                worker_result["confidence"] = findings.get("confidence", "low")
                worker_result["turns_used"] = loop.turn_count

                print(f"[Worker {worker_id}] Done — got {len(worker_result['data_points'])} data points")
        except Exception as e:
            # if one worker dies the others should keep going
            print(f"[Worker {worker_id}] Crashed: {e}")
            worker_result["gaps"].append(f"Worker failed: {str(e)[:100]}")

        results_list.append(worker_result)

    def plan_parallel(self, query: str, num_workers: int = 3) -> list:
        """
        ask pro to break one big question into smaller independent ones.
        like "M6 bolt dimensions" becomes:
          1. "M6 thread pitch ISO 261"
          2. "M6 hex head width across flats DIN 933"
          3. "M6 clearance hole diameter"
        each one gets its own browser.
        """
        print(f"\n{'='*60}")
        print(f"PARALLEL PLANNING with {PLANNING_MODEL}")
        print(f"Query: {query}")
        print(f"Workers: {num_workers}")
        print(f"{'='*60}")

        prompt = f"""Split this research query into {num_workers} INDEPENDENT sub-queries that can be researched separately and in parallel.

QUERY: {query}

Each sub-query should:
- Focus on a different aspect of the topic
- Be self-contained (can be answered without the others)
- Be specific enough to search for directly

Respond ONLY with this format (no extra text):
SUB-QUERY 1: [specific searchable question]
SUB-QUERY 2: [specific searchable question]
SUB-QUERY 3: [specific searchable question]"""

        try:
            resp = self.client.models.generate_content(model=PLANNING_MODEL, contents=prompt)
            text = resp.text
            print(f"\nParallel plan:\n{text}")

            # pull the sub-queries out of pro's response
            sub_queries = []
            for line in text.strip().split("\n"):
                line = line.strip()
                if line.upper().startswith("SUB-QUERY") and ":" in line:
                    q = line.split(":", 1)[1].strip()
                    if q:
                        sub_queries.append(q)

            # if we couldnt parse anything just run the whole query as one worker
            if not sub_queries:
                sub_queries = [query]
            return sub_queries[:num_workers]

        except Exception as e:
            print(f"Parallel planning failed ({e}), just running as one query")
            return [query]

    def run_parallel(self, query: str, num_workers: int = 3,
                     turns_per_worker: int = 12, headless: bool = False) -> dict:
        """
        the parallel version — multiple browsers at once.
        3 workers x 12 turns each = 36 total actions happening simultaneously.
        way more coverage than one browser doing 20 turns.
        """
        start = time.time()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # ask pro to split the question up
        sub_queries = self.plan_parallel(query, num_workers)
        actual_workers = len(sub_queries)

        print(f"\n{'='*60}")
        print(f"LAUNCHING {actual_workers} PARALLEL WORKERS")
        print(f"Turns per worker: {turns_per_worker}")
        print(f"{'='*60}\n")

        # fire off all the threads. we wait 1 second between each one
        # so we dont spam the API and get rate limited immediately
        results_list = []
        threads = []
        for i, sq in enumerate(sub_queries):
            t = threading.Thread(
                target=self._run_single_worker,
                args=(sq, i + 1, turns_per_worker, headless, results_list),
            )
            threads.append(t)
            t.start()
            time.sleep(1)  # stagger so the api doesnt choke

        # sit and wait for everyone to finish
        for t in threads:
            t.join()

        # now merge everything together from all the workers
        all_data_points = []
        all_sources = []
        all_gaps = []
        all_summaries = []
        total_turns = 0

        for wr in sorted(results_list, key=lambda x: x["worker_id"]):
            all_data_points.extend(wr["data_points"])
            all_sources.extend(wr["sources"])
            all_gaps.extend(wr["gaps"])
            if wr["summary"]:
                all_summaries.append(wr["summary"])
            total_turns += wr["turns_used"]

        # get rid of duplicate URLs
        seen = set()
        unique_sources = []
        for s in all_sources:
            if s not in seen:
                seen.add(s)
                unique_sources.append(s)

        # work out the overall confidence from all the workers
        # basically: if most workers found good stuff we're confident,
        # if only one did its medium, if none did its low
        confidences = [wr["confidence"] for wr in results_list if wr["data_points"]]
        if len(confidences) >= 2 and all(c == "high" for c in confidences):
            overall_confidence = "high"
        elif any(c in ("high", "medium") for c in confidences):
            overall_confidence = "medium"
        else:
            overall_confidence = "low"

        # smash all the summaries together
        merged_summary = " | ".join(all_summaries) if all_summaries else "No findings."

        result = {
            "query": query,
            "mode": "parallel",
            "sub_queries": sub_queries,
            "worker_results": [
                {"sub_query": wr["sub_query"], "data_points": len(wr["data_points"]),
                 "sources": len(wr["sources"]), "confidence": wr["confidence"]}
                for wr in sorted(results_list, key=lambda x: x["worker_id"])
            ],
            "findings": {
                "summary": merged_summary,
                "data_points": all_data_points,
                "sources": unique_sources,
                "confidence": overall_confidence,
                "gaps": all_gaps,
            },
            "metadata": {
                "status": "complete" if all_data_points else "incomplete",
                "planning_model": PLANNING_MODEL,
                "browser_model": BROWSER_MODEL,
                "num_workers": actual_workers,
                "turns_per_worker": turns_per_worker,
                "total_turns": total_turns,
                "elapsed_seconds": round(time.time() - start, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        self._save(result)
        self._display(result)
        self.generate_pdf(result)
        self._run_doc_agent(result)
        return result

    # ─── SAVING + DISPLAY ────────────────────────────────────────────────
    # boring but necessary bits — save json, print to terminal, make pdf

    def _run_doc_agent(self, result):
        """hand off to the documentation agent for proper reports."""
        if not HAS_DOC_AGENT:
            return
        try:
            doc_agent = DocumentationAgent(self.client)
            paths = doc_agent.generate(result)
            print(f"[ResearchAgent] Documentation agent produced: {paths}")
        except Exception as e:
            # doc agent failing shouldnt kill the whole research
            print(f"[ResearchAgent] Doc agent failed ({e}), raw results still saved")

    def _save(self, result):
        """dump the result dict to a json file in the outputs folder."""
        safe = "".join(c if c.isalnum() or c == " " else "_" for c in result["query"][:40])
        fp = OUTPUT_DIR / f"research_{safe.strip().replace(' ','_')}_{datetime.now():%Y%m%d_%H%M%S}.json"
        fp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\nSaved: {fp}")

    def _display(self, result):
        """print a nice summary to the terminal so you can see whats going on."""
        f = result["findings"]
        m = result["metadata"]
        print(f"\n{'='*60}")
        print(f"RESULTS — {f['confidence']} confidence")
        print(f"{'='*60}")
        print(f"Summary: {f['summary'][:400]}")
        if f["data_points"]:
            print(f"\nData ({len(f['data_points'])}):")
            for dp in f["data_points"]:
                print(f"  {dp.get('fact','?')}: {dp.get('value','?')} {dp.get('unit','')}")
                print(f"    from: {dp.get('source','?')}")
        if f["sources"]:
            print(f"\nSites visited ({len(f['sources'])}):")
            for s in f["sources"]:
                print(f"  {s}")
        if f["gaps"]:
            print(f"\nNot found:")
            for g in f["gaps"]:
                print(f"  - {g}")
        # parallel mode uses 'total_turns', single mode uses 'turns_used'
        turns = m.get('turns_used', m.get('total_turns', 0))
        print(f"\n{turns} turns, {m['elapsed_seconds']}s")
        print(f"{'='*60}\n")

    # ─── PDF REPORT ──────────────────────────────────────────────────────
    # generates a proper styled PDF from the results. auto-runs after
    # every research, but you can also call it separately on old results.
    # uses fpdf2 — installs itself if you dont have it.

    def generate_pdf(self, result: dict = None, filepath: str = None) -> Path:
        """
        make a nice looking pdf report from the research results.
        if you dont pass a result dict it'll use the most recent json file.
        """
        # try importing fpdf2, install it if its not there
        try:
            from fpdf import FPDF
        except ImportError:
            print("you dont have fpdf2, installing it now...")
            import subprocess
            subprocess.check_call(["pip", "install", "fpdf2", "--quiet"])
            from fpdf import FPDF

        # no result passed in? grab the latest json from the outputs folder
        if result is None:
            jsons = sorted(OUTPUT_DIR.glob("research_*.json"), key=lambda p: p.stat().st_mtime)
            if not jsons:
                print("no research results found — run a research first")
                return None
            result = json.loads(jsons[-1].read_text())

        f = result["findings"]
        m = result["metadata"]
        query = result["query"]

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # --- title section ---
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_text_color(43, 87, 151)
        pdf.cell(0, 14, "Research Report", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 7, f"Generated {datetime.now():%d %B %Y at %H:%M}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, "Emmanuel Omego - Research Agent", new_x="LMARGIN", new_y="NEXT")

        # blue line under the title
        pdf.ln(4)
        pdf.set_draw_color(43, 87, 151)
        pdf.set_line_width(0.8)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(8)

        # --- what was asked ---
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, "Research Query", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, query)
        pdf.ln(4)

        # --- confidence badge (green/amber/red depending on how sure we are) ---
        conf = f.get("confidence", "low")
        colors = {"high": (34, 139, 34), "medium": (200, 150, 0), "low": (180, 50, 50)}
        r, g, b = colors.get(conf, (100, 100, 100))
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 7, f"Confidence: {conf.upper()}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # --- summary paragraph ---
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, "Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 6, f.get("summary", "No summary."))
        pdf.ln(6)

        # --- data points table (the actual findings) ---
        dps = f.get("data_points", [])
        if dps:
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(0, 8, f"Data Points ({len(dps)})", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            # table header row — blue background white text
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_fill_color(43, 87, 151)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(65, 8, "Fact", border=1, fill=True)
            pdf.cell(40, 8, "Value", border=1, fill=True)
            pdf.cell(20, 8, "Unit", border=1, fill=True)
            pdf.cell(65, 8, "Source", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

            # data rows — alternating light blue / white for readability
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(50, 50, 50)
            for i, dp in enumerate(dps):
                stripe = i % 2 == 0
                if stripe:
                    pdf.set_fill_color(240, 245, 250)
                fact = str(dp.get("fact", ""))[:45]
                val = str(dp.get("value", ""))[:28]
                unit = str(dp.get("unit", ""))[:12]
                src = str(dp.get("source", ""))
                if len(src) > 45:
                    src = src[:42] + "..."
                pdf.cell(65, 7, fact, border=1, fill=stripe)
                pdf.cell(40, 7, val, border=1, fill=stripe)
                pdf.cell(20, 7, unit, border=1, fill=stripe)
                pdf.cell(65, 7, src, border=1, fill=stripe, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(6)

        # --- list of URLs we actually visited ---
        sources = f.get("sources", [])
        if sources:
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(0, 8, f"Sources ({len(sources)})", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(43, 87, 151)
            for s in sources:
                pdf.multi_cell(0, 5, s)
            pdf.ln(4)

        # --- stuff we couldnt find (gaps) ---
        gaps = f.get("gaps", [])
        if gaps:
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(180, 50, 50)
            pdf.cell(0, 8, "Gaps", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(80, 80, 80)
            for g in gaps:
                pdf.multi_cell(0, 6, f"  - {g}")
            pdf.ln(4)

        # --- footer with metadata ---
        pdf.ln(6)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(130, 130, 130)
        mode = result.get("mode", "single")
        if mode == "parallel":
            w = m.get('num_workers', '?')
            t = m.get('total_turns', '?')
            pdf.cell(0, 5, f"Parallel: {w} workers, {t} turns, {m['elapsed_seconds']}s", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.cell(0, 5, f"Single: {m.get('turns_used','?')} turns, {m['elapsed_seconds']}s", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"Models: {m.get('planning_model','')} + {m.get('browser_model','')}", new_x="LMARGIN", new_y="NEXT")

        # --- save the pdf ---
        if filepath is None:
            safe = "".join(c if c.isalnum() or c == " " else "_" for c in query[:40])
            filepath = OUTPUT_DIR / f"report_{safe.strip().replace(' ','_')}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        filepath = Path(filepath)
        pdf.output(str(filepath))
        print(f"\nPDF report saved: {filepath}")
        return filepath
