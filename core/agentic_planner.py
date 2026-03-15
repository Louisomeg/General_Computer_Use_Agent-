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
            original_request, research_data, cad_params,
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
        """Use Gemini to extract ONE specific set of CAD dimensions from research.

        The key insight: research returns ranges and multiple options, but the
        CAD agent needs EXACTLY ONE concrete value per dimension.  We ask the
        LLM to choose the best single value based on the user's request.
        """
        findings = research_data.get("findings", {})
        data_points = findings.get("data_points", [])

        if not data_points:
            return {}

        dp_text = "\n".join(
            f"- {dp.get('fact', '')}: {dp.get('value', '')} {dp.get('unit', '')}"
            for dp in data_points
        )

        prompt = (
            "You are helping design a 3D CAD model. The research found various "
            "dimensions. Your job is to pick ONE specific set of concrete values "
            "that the CAD agent will use to build the model.\n\n"
            f"USER REQUEST: {original_request}\n\n"
            f"RESEARCH DATA:\n{dp_text}\n\n"
            "RULES:\n"
            "- Pick ONE specific value per dimension, NOT ranges (e.g. '150mm' not '100-200mm')\n"
            "- Convert all values to millimeters (mm)\n"
            "- If ranges are given, pick the middle value\n"
            "- Only include 3-6 key dimensions directly needed for 3D modeling\n"
            "- Include wall_thickness (typically 3-5mm for boxes, 2-3mm for brackets)\n"
            "- Use snake_case keys\n\n"
            "Return ONLY key=value pairs, one per line. NO ranges, NO text.\n\n"
            "Example for a jewelry box:\n"
            "width=180mm\n"
            "depth=130mm\n"
            "height=80mm\n"
            "wall_thickness=5mm"
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

        # Fallback: pick first few data points with concrete values
        params = {}
        for dp in data_points[:5]:
            key = dp.get("fact", "").lower().replace(" ", "_").replace("-", "_")
            val = f"{dp.get('value', '')} {dp.get('unit', '')}".strip()
            if key and val:
                params[key] = val
        return params

    @staticmethod
    def _parse_mm(value: str) -> float | None:
        """Extract a numeric mm value from strings like '180mm', '180 mm', '180'."""
        import re
        m = re.search(r"([\d.]+)", str(value))
        return float(m.group(1)) if m else None

    def _build_cad_description(
        self, original_request: str, research_data: dict,
        cad_params: dict | None = None,
    ) -> str:
        """Enrich the CAD task description with research findings AND
        specific FreeCAD workflow guidance with PRE-COMPUTED dimensions.

        The raw request ("Make a jewelry box") is too vague for the CAD agent.
        We add:
        1. A summary of research findings
        2. Concrete FreeCAD workflow steps with EXACT numeric dimensions
           so the vision agent never has to do arithmetic.
        """
        findings = research_data.get("findings", {})
        summary = findings.get("summary", "")
        cad_params = cad_params or {}

        parts = [original_request]

        if summary:
            parts.append(f"\nResearch findings:\n{summary}")

        # Add specific FreeCAD workflow guidance
        lower = original_request.lower()
        is_box = any(w in lower for w in [
            "box", "case", "enclosure", "container", "chest", "holder",
        ])

        if is_box:
            # Pre-compute all dimensions so the agent gets concrete numbers
            width = self._parse_mm(cad_params.get("width") or
                                   cad_params.get("total_width", ""))
            depth = self._parse_mm(cad_params.get("depth") or
                                   cad_params.get("total_depth", ""))
            height = self._parse_mm(cad_params.get("height") or
                                    cad_params.get("total_height", ""))
            wall = self._parse_mm(cad_params.get("wall_thickness", ""))

            # Sensible defaults if research didn't provide values
            width = width or 150.0
            depth = depth or 100.0
            height = height or 60.0
            wall = wall or 5.0

            inner_width = width - 2 * wall
            inner_depth = depth - 2 * wall
            pocket_depth = height - wall   # leave wall-thickness as bottom

            parts.append(f"""
## EXACT DIMENSIONS (pre-computed — use these numbers directly)

- Outer width:  {width} mm
- Outer depth:  {depth} mm
- Outer height: {height} mm
- Wall thickness: {wall} mm
- **Inner pocket width:  {inner_width} mm** (outer width minus 2 × wall)
- **Inner pocket depth:  {inner_depth} mm** (outer depth minus 2 × wall)
- **Pocket cut depth:    {pocket_depth} mm** (outer height minus bottom thickness)

## FreeCAD Workflow for this Part

You are building a HOLLOW box. Follow these steps EXACTLY:

STEP 1 — Create the outer solid:
  a) Open FreeCAD (if not already open)
  b) Part Design menu → Create body
  c) Part Design menu → Create sketch → select XY plane → OK
  d) Draw a rectangle using Sketch → Sketcher geometries → Rectangle
     (click two opposite corners anywhere in the viewport — exact size doesn't matter yet)
  e) Constrain the HORIZONTAL edge to {width} mm:
     click one horizontal edge → Sketch → Sketcher constraints → Constrain distance → type "{width} mm" → OK
  f) Constrain the VERTICAL edge to {depth} mm:
     click one vertical edge → Sketch → Sketcher constraints → Constrain distance → type "{depth} mm" → OK
  g) Close sketch: Sketch → Close sketch
  h) Pad it: Part Design menu → Pad → type "{height}" in the Length field → click OK

STEP 2 — Hollow it out with a Pocket:
  a) Click on the TOP FACE of the padded solid (the large flat face on top — it will highlight green)
  b) Part Design menu → Create sketch (a new sketch is created ON the top face)
  c) Draw a rectangle using Sketch → Sketcher geometries → Rectangle
     (click two opposite corners INSIDE the face — approximate size is fine)
  d) Constrain the HORIZONTAL edge to **{inner_width} mm**:
     click one horizontal edge → Sketch → Sketcher constraints → Constrain distance → type "{inner_width} mm" → OK
  e) Constrain the VERTICAL edge to **{inner_depth} mm**:
     click one vertical edge → Sketch → Sketcher constraints → Constrain distance → type "{inner_depth} mm" → OK
  f) OPTIONAL but recommended: center the inner rectangle on the face using
     Sketch → Sketcher constraints → Constrain symmetric (select two opposite edges + center axis)
  g) Close sketch: Sketch → Close sketch
  h) Part Design menu → Pocket → type "{pocket_depth}" in the Length/Depth field → click OK

The result is a hollow box: {width}×{depth}×{height} mm outer, with {wall} mm thick walls and bottom.

CRITICAL RULES:
- You MUST constrain BOTH edges (horizontal AND vertical) of each rectangle.
- The inner rectangle MUST be {inner_width} mm × {inner_depth} mm (NOT the same as the outer).
- Do NOT just make a solid block. The box MUST be hollow inside.
- After padding, you MUST click the TOP face, NOT a side face.
""")
        else:
            parts.append("""
## FreeCAD Workflow
1. Open FreeCAD → Part Design → Create body → Create sketch on XY plane
2. Draw the profile geometry and constrain dimensions
3. Close sketch → Pad to create the solid
4. Add features (fillets, pockets, chamfers) as needed
""")

        return "\n".join(parts)
