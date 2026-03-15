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
from core.settings import DEFAULT_MODEL, PLANNING_MODEL

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
    PLAN_MODELS = [PLANNING_MODEL]

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

    # ── FreeCAD UI knowledge base ─────────────────────────────────────
    # This is fed to Gemini 3.1 Pro so it can produce an ultra-detailed
    # plan that accounts for every FreeCAD quirk and common mistake.

    FREECAD_KNOWLEDGE = """
You are a FreeCAD expert planner. You know EVERYTHING about FreeCAD 1.0's UI on Ubuntu XFCE.
A vision-based AI agent will follow your plan by looking at screenshots and clicking.
The agent is NOT smart — it follows instructions literally. Your plan must be FOOLPROOF.

## FreeCAD UI Layout (1440x900 resolution)
- Menu bar at the very top: File | Edit | View | Macro | Sketch | Part Design | App
- "Sketch" menu is at approximately x=236, y=62 in screen pixels
- "Part Design" menu is at approximately x=300, y=62 in screen pixels
- Model tree panel is on the LEFT side
- Tasks panel appears on the LEFT side when a dialog is active
- 3D viewport is the large area in the CENTER/RIGHT
- Console/log output at the BOTTOM

## FreeCAD Menu Structure (EXACT names)
Part Design menu contains:
  - "Create body" — creates a new Body in the model tree
  - "Create sketch" — opens the plane selection or creates sketch on selected face
  - "Pad" — extrudes a sketch into a 3D solid
  - Under "Create a subtractive feature": "Pocket" — cuts material away
  - "Fillet" — rounds edges

Sketch menu contains:
  - Under "Sketcher geometries": "Rectangle", "Circle", "Line", etc.
  - Under "Sketcher constraints": "Constrain distance", "Constrain radius", etc.
  - "Close sketch" — exits the sketcher

## COMMON MISTAKES the agent makes (your plan MUST prevent these):

1. CONSTRAINT WITHOUT SELECTION: The agent opens "Constrain distance" WITHOUT
   first clicking an edge. This causes "Datum X mm for constraint index N is invalid".
   → YOUR PLAN MUST SAY: "Click the edge (it turns green) THEN open constraint dialog"

2. MISSING VERTICAL CONSTRAINT: The agent constrains the horizontal edge then
   FORGETS to constrain the vertical edge, closing the sketch too early.
   → YOUR PLAN MUST SAY: "DO NOT close sketch. Now do the vertical edge."

3. MULTIPLE RECTANGLES: The agent draws 2-3 rectangles on one sketch, corrupting it.
   → YOUR PLAN MUST SAY: "NEVER draw a second shape. If wrong, Ctrl+Z to undo."

4. POCKET FAILS (Sub shape not found): Happens when the sketch has overlapping
   geometry or the sketch was created on the wrong face.
   → YOUR PLAN MUST include verification after each Pocket.

5. PRESS_ENTER vs CLICK_OK: The agent uses press_enter in dialogs which sometimes
   fails. Clicking the OK button is more reliable.
   → YOUR PLAN MUST SAY: "Click the OK button" not "press Enter"

6. TEXT-ONLY RESPONSES: The agent sometimes "thinks" without acting, wasting turns.
   → Keep instructions action-focused. Every step = one click or type action.

7. WRONG FACE FOR POCKET: Agent clicks a side face instead of the top face.
   → YOUR PLAN MUST SAY: "Click the LARGE FLAT face on TOP of the solid"

8. CONSTRAINT VALUE REJECTED: Typing "196.0 mm" might fail if the field already
   has text. The agent should triple-click to select all text first, then type.
   → YOUR PLAN MUST SAY: "Triple-click the input field to select all, then type the value"

## VERIFICATION CHECKPOINTS (your plan MUST include these):
- After drawing a rectangle: "VERIFY: you see 4 white/green lines forming a rectangle"
- After constraining an edge: "VERIFY: a dimension annotation (number with arrows) appears"
- After padding: "VERIFY: the model tree shows 'Pad' under 'Body' and a 3D solid is visible"
- After creating pocket sketch: "VERIFY: the sketch grid appears on the top face"
- After pocket: "VERIFY: the model tree shows 'Pocket' and the 3D view shows a hollow interior"

## OUTPUT FORMAT
Return a numbered action script. Each action is ONE atomic step:
  1. ACTION: <what to do>
     CLICK/TYPE: <exact UI element and value>
     IF_ERROR: <what to do if it fails>
     VERIFY: <what the screen should show after>
"""

    def _generate_cad_plan(
        self, original_request: str, cad_params: dict,
        research_summary: str = "",
    ) -> str:
        """Use Gemini 3.1 Pro to generate an ultra-detailed CAD action plan.

        The smarter model reasons about FreeCAD's UI and generates a numbered
        action script that the vision agent (Flash) follows mechanically.
        """
        # Pre-compute dimensions
        width = self._parse_mm(cad_params.get("width") or
                               cad_params.get("total_width", ""))
        depth = self._parse_mm(cad_params.get("depth") or
                               cad_params.get("total_depth", ""))
        height = self._parse_mm(cad_params.get("height") or
                                cad_params.get("total_height", ""))
        wall = self._parse_mm(cad_params.get("wall_thickness", ""))

        width = width or 150.0
        depth = depth or 100.0
        height = height or 60.0
        wall = wall or 5.0

        inner_width = width - 2 * wall
        inner_depth = depth - 2 * wall
        pocket_depth = height - wall

        task_context = f"""
TASK: {original_request}
{f"RESEARCH CONTEXT: {research_summary}" if research_summary else ""}

DIMENSIONS (pre-computed, use these exactly):
- Outer rectangle: {width} mm × {depth} mm
- Pad height: {height} mm
- Inner pocket rectangle: {inner_width} mm × {inner_depth} mm
- Pocket depth: {pocket_depth} mm
- Wall thickness: {wall} mm

Generate the complete numbered action script for building this in FreeCAD.
Start from a blank FreeCAD window. Include every single click and keystroke.
Account for all common mistakes listed above.
End with calling task_complete().
"""

        prompt = self.FREECAD_KNOWLEDGE + "\n" + task_context

        print(f"  [Planner] Generating detailed CAD plan with {PLANNING_MODEL}...")

        for model in self.PLAN_MODELS:
            try:
                response = self.client.models.generate_content(
                    model=model, contents=prompt,
                )
                plan = response.text.strip()
                if plan:
                    print(f"  [Planner] CAD plan generated ({len(plan)} chars)")
                    return plan
            except Exception as e:
                print(f"  [Planner] Plan generation failed ({e})")

        # Fallback: return a basic hardcoded plan
        print("  [Planner] Using fallback hardcoded plan")
        return self._fallback_cad_plan(
            width, depth, height, wall, inner_width, inner_depth, pocket_depth,
        )

    @staticmethod
    def _fallback_cad_plan(
        width, depth, height, wall, inner_width, inner_depth, pocket_depth,
    ) -> str:
        """Hardcoded fallback plan if Gemini 3.1 Pro is unavailable."""
        return f"""## ACTION SCRIPT — Follow each step exactly

STEP 1: Open FreeCAD (if not already open). Look at the screen.

STEP 2: Create a new body.
  ACTION: Click "Part Design" in the menu bar → click "Create body"
  VERIFY: "Body" appears in the model tree on the left

STEP 3: Create a sketch on XY plane.
  ACTION: Click "Part Design" in the menu bar → click "Create sketch"
  ACTION: In the dialog, select "XY_Plane (Base plane)" → click OK or press Enter
  VERIFY: A sketch grid appears in the viewport

STEP 4: Draw a rectangle.
  ACTION: Click "Sketch" menu → hover "Sketcher geometries" → click "Rectangle"
  ACTION: Click a first corner in the upper-left area of the viewport
  ACTION: Click a second corner diagonally opposite (lower-right area)
  ACTION: Press Escape to exit the rectangle tool
  VERIFY: You see 4 lines forming a rectangle. NEVER draw a second rectangle.

STEP 5: Constrain the horizontal edge to {width} mm.
  ACTION: Click on one HORIZONTAL edge of the rectangle (it turns green when selected)
  ACTION: Click "Sketch" menu → hover "Sketcher constraints" → click "Constrain distance"
  ACTION: A dialog appears. Triple-click the input field to select all, type "{width} mm"
  ACTION: Click the OK button in the dialog
  VERIFY: A dimension annotation showing {width} appears near the horizontal edge
  IF_ERROR: Press Ctrl+Z to undo, re-select the edge, and try again

STEP 6: Constrain the vertical edge to {depth} mm.
  ACTION: Click on one VERTICAL edge of the rectangle (it turns green when selected)
  ACTION: Click "Sketch" menu → hover "Sketcher constraints" → click "Constrain distance"
  ACTION: Triple-click the input field, type "{depth} mm"
  ACTION: Click the OK button
  VERIFY: A second dimension annotation showing {depth} appears near the vertical edge
  IF_ERROR: Press Ctrl+Z to undo, re-select the edge, and try again

STEP 7: Close the sketch.
  ACTION: Click "Sketch" menu → click "Close sketch"
  VERIFY: The sketch closes and you return to the 3D view

STEP 8: Pad the sketch to {height} mm.
  ACTION: Click "Part Design" menu → click "Pad"
  ACTION: In the Tasks panel, triple-click the Length field, type "{height}"
  ACTION: Click OK
  VERIFY: A 3D rectangular solid appears. The model tree shows "Pad" under "Body".

STEP 9: Select the top face for the pocket.
  ACTION: Click on the LARGE FLAT face on TOP of the solid (it highlights green/blue)
  VERIFY: The status bar at the bottom shows "Face" in the selection text

STEP 10: Create a sketch on the top face.
  ACTION: Click "Part Design" menu → click "Create sketch"
  VERIFY: A sketch grid appears ON the top face

STEP 11: Draw the inner rectangle for the pocket.
  ACTION: Click "Sketch" menu → hover "Sketcher geometries" → click "Rectangle"
  ACTION: Click a first corner INSIDE the face boundary
  ACTION: Click a second corner diagonally opposite, also INSIDE the face
  ACTION: Press Escape to exit the rectangle tool
  VERIFY: A rectangle appears. NEVER draw a second rectangle on this sketch.

STEP 12: Constrain inner horizontal edge to {inner_width} mm.
  ACTION: Click on one HORIZONTAL edge of the inner rectangle (it turns green)
  ACTION: Click "Sketch" menu → hover "Sketcher constraints" → click "Constrain distance"
  ACTION: Triple-click the input field, type "{inner_width} mm"
  ACTION: Click the OK button
  VERIFY: A dimension annotation showing {inner_width} appears
  IF_ERROR: Press Ctrl+Z and retry

STEP 13: Constrain inner vertical edge to {inner_depth} mm.
  DO NOT CLOSE THE SKETCH YET. You must constrain the vertical edge too.
  ACTION: Click on one VERTICAL edge of the inner rectangle (it turns green)
  ACTION: Click "Sketch" menu → hover "Sketcher constraints" → click "Constrain distance"
  ACTION: Triple-click the input field, type "{inner_depth} mm"
  ACTION: Click the OK button
  VERIFY: TWO dimension annotations are visible (one for each edge)
  IF_ERROR: Press Ctrl+Z and retry

STEP 14: Close the sketch.
  ONLY close after BOTH dimension annotations are visible.
  ACTION: Click "Sketch" menu → click "Close sketch"

STEP 15: Create the pocket.
  ACTION: Click "Part Design" menu → hover "Create a subtractive feature" → click "Pocket"
  ACTION: In the Tasks panel, triple-click the Length/Depth field, type "{pocket_depth}"
  ACTION: Click OK
  VERIFY: The 3D view shows a hollow box. The model tree shows "Pocket" under "Body".
  IF_ERROR: If "Sub shape not found" appears, press Ctrl+Z, re-select the top face, and redo steps 10-15.

STEP 16: Task complete.
  ACTION: Call task_complete(summary="Created hollow box: {width}x{depth}x{height}mm outer, {wall}mm walls, {inner_width}x{inner_depth}mm inner pocket {pocket_depth}mm deep")
"""

    def _build_cad_description(
        self, original_request: str, research_data: dict,
        cad_params: dict | None = None,
    ) -> str:
        """Build the CAD task description.

        For box/enclosure tasks: uses Gemini 3.1 Pro to generate an ultra-detailed
        action plan with error recovery and verification steps.
        For other tasks: returns a basic workflow outline.
        """
        findings = research_data.get("findings", {})
        summary = findings.get("summary", "")
        cad_params = cad_params or {}

        lower = original_request.lower()
        is_box = any(w in lower for w in [
            "box", "case", "enclosure", "container", "chest", "holder",
        ])

        if is_box and cad_params:
            # Use the smart planner to generate a detailed action script
            plan = self._generate_cad_plan(original_request, cad_params, summary)
            return f"{original_request}\n\n{plan}"
        else:
            parts = [original_request]
            if summary:
                parts.append(f"\nResearch findings:\n{summary}")
            parts.append("""
## FreeCAD Workflow
1. Open FreeCAD → Part Design → Create body → Create sketch on XY plane
2. Draw the profile geometry and constrain dimensions
3. Close sketch → Pad to create the solid
4. Add features (fillets, pockets, chamfers) as needed
""")
            return "\n".join(parts)
