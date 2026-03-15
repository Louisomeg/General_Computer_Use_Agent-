# =============================================================================
# Agentic Planner — routes user goals to the right agent(s)
# =============================================================================
# Routes requests to agents and chains them when needed:
#   - "cad"          → CAD agent only (dimensions already specified)
#   - "research"     → Research agent only (pure information lookup)
#   - "research+cad" → Research first, extract dimensions, then CAD
#
# Usage:
#   planner = Planner(client, executor)
#   result = planner.run("Create a 30mm cube in FreeCAD")
#   result = planner.run("Research M6 bolt dimensions")
#   result = planner.run("Make a phone holder for a bicycle")

from google import genai

from agents.registry import get_agent, list_agents
from core.executor import Executor
from core.models import Task, TaskStatus
from core.settings import DEFAULT_MODEL

# Import agent modules so @register decorators fire
import agents.cad_agent       # noqa: F401
import agents.research_agent  # noqa: F401


# The planner uses Gemini to figure out which agent to call and what params to extract.
PLANNER_PROMPT = """You are a task planner. Given a user request, decide which agent should handle it
and extract the relevant parameters.

Available agents: {agents}

Respond in EXACTLY this format (no extra text):
AGENT: <agent_name>
DESCRIPTION: <clear task description for the agent>
PARAMS: <key=value pairs, one per line, or NONE>

Rules:
- "cad" agent: creating/designing/modeling 3D parts in FreeCAD when dimensions are already known.
  Also for desktop tasks like opening applications, clicking on things, file management.
- "research" agent: ONLY for finding information online — specs, standards, looking things up on the web
- "research+cad" workflow: for design/creation tasks where the user does NOT provide specific
  dimensions or specifications. First research the right dimensions, then create in CAD.
  Use this when the user says "make a phone holder", "design a bracket for X", "create a mount
  for Y" — any design task where you'd need to look up real-world specs first.
- If the user already provides exact dimensions (e.g., "50mm tall cylinder with radius 15mm"),
  just use "cad" directly — no research needed.
- If the task requires browsing the internet for information only, use "research"
- DESCRIPTION should be a clear instruction the agent can act on
- PARAMS should extract specific values (dimensions, materials, part names, etc.)

Examples:

User: "Make me a 50mm tall cylinder with radius 15mm"
AGENT: cad
DESCRIPTION: Create a cylinder in FreeCAD
PARAMS:
height=50mm
radius=15mm

User: "What are the standard dimensions of an M8 hex bolt?"
AGENT: research
DESCRIPTION: Find standard dimensions of an M8 hex bolt including head size, thread pitch, and length options
PARAMS:
max_turns=30

User: "Open FreeCAD and create a new Part Design body"
AGENT: cad
DESCRIPTION: Open FreeCAD and create a new document with a Part Design Body
PARAMS: NONE

User: "Design a phone holder for a bicycle handlebar"
AGENT: research+cad
DESCRIPTION: Research bicycle handlebar and phone dimensions, then design a phone holder mount
PARAMS:
max_turns=30

User: "Make a bracket for an M6 bolt"
AGENT: research+cad
DESCRIPTION: Research M6 bolt dimensions including head size and thread specs, then create a mounting bracket
PARAMS:
max_turns=30
"""


class Planner:
    """Routes user goals to the right agent."""

    def __init__(self, client: genai.Client, executor: Executor = None):
        self.client = client
        self.executor = executor  # only needed for agents that use desktop (cad)

    def run(self, user_request: str) -> Task:
        """Plan and execute a user request end-to-end."""
        print(f"\n{'='*60}")
        print(f"PLANNER")
        print(f"Request: {user_request}")
        print(f"Available agents: {list_agents()}")
        print(f"{'='*60}\n")

        agent_name, description, params = self._plan(user_request)

        print(f"  Agent:       {agent_name}")
        print(f"  Description: {description}")
        print(f"  Params:      {params}")
        print()

        # Multi-agent workflow: research first, then CAD
        if agent_name == "research+cad":
            return self._run_research_then_cad(user_request, description, params)

        # Single-agent path (existing behavior)
        task = Task(description=description, params=params)
        try:
            kwargs = self._build_agent_kwargs(agent_name)
            agent = get_agent(agent_name, **kwargs)
            result = agent.execute(task)
        except KeyError as e:
            print(f"  [Planner] Agent error: {e}")
            task.fail(error=str(e))
            result = task

        self._report(result)
        return result

    def _report(self, result: Task):
        """Print result summary."""
        print(f"\n{'='*60}")
        print(f"PLANNER RESULT")
        print(f"  Status: {result.status.value}")
        if result.result:
            print(f"  Result: {result.result[:200]}")
        if result.error:
            print(f"  Error:  {result.error}")
        print(f"{'='*60}\n")

    # Models to try for planning, in order.  Planning is text-only so any
    # model works.  If the primary model has no quota (e.g. free tier), we
    # automatically try the next one.
    PLAN_MODELS = [DEFAULT_MODEL]

    def _plan(self, user_request: str) -> tuple[str, str, dict]:
        """Use Gemini to decide agent + params. Falls back to parsing if API fails."""
        prompt = PLANNER_PROMPT.format(agents=", ".join(list_agents()))
        prompt += f"\n\nUser: \"{user_request}\""

        for model in self.PLAN_MODELS:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                return self._parse_plan(response.text, user_request)
            except Exception as e:
                print(f"  [Planner] {model} failed ({e})")

        print("  [Planner] All models failed, using keyword fallback")
        return self._fallback_plan(user_request)

    def _parse_plan(self, text: str, original: str) -> tuple[str, str, dict]:
        """Parse the structured LLM response."""
        agent_name = ""
        description = ""
        params = {}
        in_params = False

        for line in text.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("AGENT:"):
                agent_name = line.split(":", 1)[1].strip().lower()
                in_params = False
            elif line.upper().startswith("DESCRIPTION:"):
                description = line.split(":", 1)[1].strip()
                in_params = False
            elif line.upper().startswith("PARAMS:"):
                rest = line.split(":", 1)[1].strip()
                if rest.upper() == "NONE":
                    in_params = False
                else:
                    in_params = True
                    # params might be on the same line
                    if "=" in rest:
                        k, v = rest.split("=", 1)
                        params[k.strip()] = v.strip()
            elif in_params and "=" in line:
                k, v = line.split("=", 1)
                params[k.strip()] = v.strip()

        # Validation
        if not agent_name:
            agent_name, description, params = self._fallback_plan(original)
        if not description:
            description = original

        return agent_name, description, params

    def _fallback_plan(self, request: str) -> tuple[str, str, dict]:
        """Simple keyword-based fallback if LLM fails."""
        lower = request.lower()
        research_keywords = ["research", "look up", "what is", "what are",
                             "specifications", "standard", "how much", "how many"]
        design_keywords = ["design", "make", "build", "create"]
        has_dimensions = any(c.isdigit() for c in request) and "mm" in lower

        if any(kw in lower for kw in research_keywords):
            return "research", request, {"max_turns": 20}
        elif any(kw in lower for kw in design_keywords) and not has_dimensions:
            # Design task without dimensions — research first
            return "research+cad", request, {"max_turns": 20}
        else:
            # Default to desktop agent — most tasks involve the GUI
            return "cad", request, {}

    def _build_agent_kwargs(self, agent_name: str) -> dict:
        """Build the kwargs needed to instantiate the agent."""
        if agent_name == "cad":
            return {"client": self.client, "executor": self.executor}
        elif agent_name == "research":
            return {"client": self.client}
        else:
            # generic fallback
            return {"client": self.client}

    # ── Multi-agent workflow ──────────────────────────────────────────

    def _run_research_then_cad(
        self, original_request: str, description: str, params: dict,
    ) -> Task:
        """Run research first, extract dimensions, then CAD."""
        # Phase 1: Research
        print(f"\n{'='*60}")
        print(f"PLANNER — Phase 1: Research")
        print(f"{'='*60}\n")

        research_task = Task(
            description=description,
            params={"max_turns": int(params.get("max_turns", 20))},
        )
        try:
            research_agent = get_agent("research", client=self.client)
            research_result = research_agent.execute(research_task)
        except Exception as e:
            print(f"  [Planner] Research agent error: {e}")
            research_task.fail(error=str(e))
            self._report(research_task)
            return research_task

        if research_result.status != TaskStatus.COMPLETED:
            print("[Planner] Research failed — cannot proceed to CAD")
            self._report(research_result)
            return research_result

        # Quality gate: check if research actually produced useful data.
        # The research agent catches internal errors and still marks the
        # task as COMPLETED with a low-confidence empty result.
        research_data = (
            research_result.artifacts[0] if research_result.artifacts else {}
        )
        findings = research_data.get("findings", {})
        data_points = findings.get("data_points", [])
        confidence = findings.get("confidence", "low")

        if not data_points and confidence == "low":
            print("[Planner] Research completed but produced no useful data — cannot proceed to CAD")
            research_result.fail(
                error="Research returned no data points with low confidence"
            )
            self._report(research_result)
            return research_result

        self._report(research_result)
        cad_params = self._extract_dimensions(research_data, original_request)

        # Phase 3: CAD with enriched description
        print(f"\n{'='*60}")
        print(f"PLANNER — Phase 2: CAD Design")
        print(f"  Extracted params: {cad_params}")
        print(f"{'='*60}\n")

        cad_description = self._build_cad_description(
            original_request, research_data,
        )
        cad_task = Task(description=cad_description, params=cad_params)

        try:
            cad_agent = get_agent(
                "cad", client=self.client, executor=self.executor,
            )
            cad_result = cad_agent.execute(cad_task)
        except Exception as e:
            print(f"  [Planner] CAD agent error: {e}")
            cad_task.fail(error=str(e))
            self._report(cad_task)
            return cad_task

        self._report(cad_result)
        return cad_result

    def _extract_dimensions(
        self, research_data: dict, original_request: str,
    ) -> dict:
        """Use Gemini to extract CAD-relevant dimensions from research."""
        findings = research_data.get("findings", {})
        data_points = findings.get("data_points", [])

        if not data_points:
            return {}

        dp_text = "\n".join(
            f"- {dp.get('fact', '')}: {dp.get('value', '')} {dp.get('unit', '')}"
            for dp in data_points
        )

        prompt = (
            "From these research findings, extract the key dimensions "
            "needed to design this part in CAD.\n\n"
            f"USER REQUEST: {original_request}\n\n"
            f"RESEARCH DATA:\n{dp_text}\n\n"
            "Return ONLY key=value pairs (one per line) for dimensions "
            "relevant to the CAD design.\n"
            "Use snake_case keys. Include units in the values.\n"
            "Only include dimensions directly useful for 3D modeling.\n\n"
            "Example output:\n"
            "handlebar_diameter=25.4mm\n"
            "phone_width=75mm\n"
            "mount_thickness=3mm"
        )

        for model in self.PLAN_MODELS:
            try:
                response = self.client.models.generate_content(
                    model=model, contents=prompt,
                )
                params = {}
                for line in response.text.strip().split("\n"):
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        params[k.strip()] = v.strip()
                if params:
                    return params
            except Exception as e:
                print(f"  [Planner] Dimension extraction failed ({e})")

        # Fallback: mechanical conversion of all data points
        params = {}
        for dp in data_points:
            key = dp.get("fact", "").lower().replace(" ", "_").replace("-", "_")
            val = f"{dp.get('value', '')} {dp.get('unit', '')}".strip()
            if key and val:
                params[key] = val
        return params

    def _build_cad_description(
        self, original_request: str, research_data: dict,
    ) -> str:
        """Enrich the CAD task description with research findings."""
        findings = research_data.get("findings", {})
        summary = findings.get("summary", "")

        if summary:
            return f"{original_request}\n\nResearch findings:\n{summary}"
        return original_request
