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
- "cad" agent: creating/designing/modeling 3D parts in FreeCAD. Use this for:
  (a) Tasks where the user provides exact dimensions (e.g., "50mm tall cylinder with radius 15mm")
  (b) SIMPLE everyday objects where default dimensions are fine (boxes, containers, trays,
      cubes, stands, plates, blocks, frames, simple holders). The system will add sensible
      default dimensions automatically. No research needed for these.
  (c) Desktop tasks like opening applications, clicking on things, file management.
- "research" agent: ONLY for finding information online — specs, standards, looking things up on the web
- "research+cad" workflow: ONLY for SPECIALIZED design tasks where you need specific real-world
  measurements that you don't know. Examples: "phone holder for bicycle handlebar" (need
  handlebar diameter and phone size), "bracket for M6 bolt" (need bolt specs), "mount for
  a GoPro camera" (need GoPro mounting standard). Use this ONLY when the design DEPENDS ON
  external measurements.
- IMPORTANT: for simple objects like "make a box", "create a container", "build a tray" —
  use "cad" NOT "research+cad". Research is expensive and often fails.
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

User: "Make a simple box to store jewelry"
AGENT: cad
DESCRIPTION: Create a hollow jewelry storage box in FreeCAD with sensible default dimensions
PARAMS: NONE

User: "Create a container for pens"
AGENT: cad
DESCRIPTION: Create a hollow pen/pencil container in FreeCAD with sensible default dimensions
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

        # For CAD design tasks without specific dimensions, add sensible
        # defaults and generate a detailed action plan.  This skips research
        # entirely — much faster and avoids rate-limit / captcha failures.
        if agent_name == "cad" and self._is_design_task(user_request) and not params:
            print("  [Planner] Design task without dimensions — adding defaults")
            params = self._get_default_dimensions(user_request)
            print(f"  [Planner] Default params: {params}")
            description = self._build_cad_description(
                user_request, {}, params,
            )

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

        # Simple everyday objects that don't need research
        simple_objects = [
            "box", "cube", "container", "tray", "shelf", "plate",
            "block", "stand", "base", "frame", "chest", "case",
            "drawer", "bin", "pot", "cup", "vase",
        ]

        if any(kw in lower for kw in research_keywords):
            return "research", request, {"max_turns": 20}
        elif any(kw in lower for kw in design_keywords) and not has_dimensions:
            # Simple common objects → cad with defaults (no research needed)
            if any(obj in lower for obj in simple_objects):
                return "cad", request, {}
            # Specialized items → research first
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

    # ── Simple design tasks (skip research) ──────────────────────────

    @staticmethod
    def _is_design_task(request: str) -> bool:
        """Check if this is a design/creation task (vs a desktop/info task)."""
        lower = request.lower()
        design_words = [
            "make", "create", "design", "build", "model",
            "box", "container", "holder", "bracket", "case",
            "enclosure", "tray", "stand", "shelf", "mount",
        ]
        return any(w in lower for w in design_words)

    def _get_default_dimensions(self, request: str) -> dict:
        """Pick sensible default dimensions for common objects.

        Uses Gemini 3.1 Pro to reason about the right size, with a
        hardcoded fallback if the LLM call fails.
        """
        prompt = (
            f'Pick sensible real-world default dimensions for: "{request}"\n\n'
            "Return ONLY key=value pairs, one per line. All values in mm.\n"
            "Include: width, depth, height, wall_thickness\n"
            "Keep it practical — use real-world sizes for the object.\n\n"
            "Example for a jewelry box:\n"
            "width=180mm\n"
            "depth=120mm\n"
            "height=60mm\n"
            "wall_thickness=5mm\n"
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
                    print(f"  [Planner] LLM-generated defaults: {params}")
                    return params
            except Exception as e:
                print(f"  [Planner] Default dimension generation failed ({e})")

        # Hardcoded fallback for common objects
        lower = request.lower()
        if any(w in lower for w in ["jewelry", "jewellery", "trinket", "ring"]):
            return {"width": "180mm", "depth": "120mm", "height": "60mm",
                    "wall_thickness": "5mm"}
        elif any(w in lower for w in ["pen", "pencil", "marker", "stationery"]):
            return {"width": "80mm", "depth": "80mm", "height": "120mm",
                    "wall_thickness": "4mm"}
        elif any(w in lower for w in ["tool", "wrench", "screwdriver"]):
            return {"width": "300mm", "depth": "150mm", "height": "80mm",
                    "wall_thickness": "5mm"}
        elif any(w in lower for w in ["phone", "mobile"]):
            return {"width": "85mm", "depth": "175mm", "height": "15mm",
                    "wall_thickness": "3mm"}
        else:
            # Generic box/container
            return {"width": "150mm", "depth": "100mm", "height": "60mm",
                    "wall_thickness": "5mm"}

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
You are a FreeCAD 1.0 expert planner. Your knowledge comes from the official FreeCAD wiki.
A vision-based AI agent will follow your plan by looking at screenshots and clicking/typing.
The agent is NOT smart — it follows instructions literally. Your plan must be FOOLPROOF.

## FreeCAD UI Layout (1440x900 resolution, Ubuntu XFCE)
- Menu bar at top: File | Edit | View | Macro | Sketch | Part Design | App
- Model tree panel on the LEFT side
- Tasks panel appears on the LEFT side when a dialog is active
- 3D viewport is the large CENTER/RIGHT area
- Console/log output at the BOTTOM

## VIEW MANAGEMENT (CRITICAL — keep the object visible and centered at all times)
The agent relies on screenshots to click on faces and edges. If the object is
off-screen, too zoomed in, or at a bad angle, the agent CANNOT work reliably.
- After EVERY major operation (Pad, closing a sketch, selecting a face), add:
  "View" menu -> "Standard views" -> "Fit All" to re-center and zoom to fit.
- Before selecting the TOP face for a pocket, ALWAYS use:
  "View" menu -> "Standard views" -> "Top" to get a top-down view,
  THEN "View" menu -> "Standard views" -> "Fit All" to ensure it fills the viewport.
- After the Pocket operation, use:
  "View" menu -> "Standard views" -> "Home" (or "Isometric") to see the 3D result.
- NEVER let the object drift off-screen or get so zoomed in that edges are not visible.

## HOW TO ACTIVATE TOOLS
Most operations use menus. But Rectangle and Constrain distance have 3-level
submenus that are unreliable, so use their KEYBOARD SHORTCUTS instead:

SHORTCUTS (use these — they bypass unreliable 3-level submenus):
- Rectangle tool:     press key_combination("g"), then press key_combination("r")
- Constrain distance: press key_combination("k"), then press key_combination("d")

MENUS (use for everything else — these are 1-2 level menus that work reliably):
- Create body:   "Part Design" menu -> "Create body"
- Create sketch: "Sketch" menu -> "Create sketch" (NOT Part Design menu!)
                 If a face is pre-selected, sketch is created ON that face instantly.
- Close sketch:  "Sketch" menu -> "Close sketch"
- Pad:           "Part Design" menu -> "Create an additive feature" -> "Pad"
- Pocket:        "Part Design" menu -> "Create a subtractive feature" -> "Pocket"
- Fillet:        "Part Design" menu -> "Fillet"
- Undo:          "Edit" menu -> "Undo"

## CONSTRAINT WORKFLOW (from official wiki — "Run-once mode")
The correct way to constrain an edge is:
  1. SELECT the edge first (click it — it turns green)
  2. THEN press key_combination("k"), then press key_combination("d")
  3. A dialog appears with an input field
  4. Type the value WITH units (e.g. "196.0 mm")
  5. Click the OK button (do NOT press Enter)
IMPORTANT: selecting the edge FIRST is called "Run-once mode" and is more reliable.

## RECTANGLE WORKFLOW (from official wiki)
  1. Press key_combination("g"), then press key_combination("r") to activate
  2. Click first corner in viewport
  3. Click opposite diagonal corner
  4. The rectangle is created between those two points
  5. Press Escape to exit the rectangle tool
  6. NEVER draw a second rectangle on the same sketch

## PAD WORKFLOW (from official wiki)
  - The Pad tool extrudes a sketch along a straight path
  - Select the sketch first (or it uses the last sketch)
  - Menu: Part Design -> Create an additive feature -> Pad
  - The "Pad parameters" task panel appears with a Length field
  - Set Type to "Dimension", enter Length value, click OK

## POCKET WORKFLOW (from official wiki)
  - The Pocket tool cuts solids by extruding a sketch
  - Menu: Part Design -> Create a subtractive feature -> Pocket
  - Note the submenu name: "Create a subtractive feature" (not "substractive")
  - The "Pocket parameters" task panel appears with a Length field
  - Set Type to "Dimension", enter Length value, click OK

## COMMON MISTAKES the agent makes (your plan MUST prevent these):

1. MENU NAVIGATION FAILS: Agent clicks wrong submenu items in 3-level menus.
   -> Use shortcuts for Rectangle (G R) and Constrain distance (K D) to avoid this.

2. CONSTRAINT WITHOUT SELECTION: Agent invokes constraint tool WITHOUT selecting edge.
   -> SELECT edge first (green), THEN press K D.

3. MISSING VERTICAL CONSTRAINT: Agent constrains horizontal edge then closes sketch.
   -> Explicit step: "DO NOT close sketch. Now constrain the vertical edge."

4. MULTIPLE RECTANGLES: Agent draws 2-3 rectangles on one sketch, corrupting it.
   -> "NEVER draw a second rectangle. If wrong, Edit -> Undo."

5. WRONG FACE FOR POCKET: Agent clicks a side face instead of the top face.
   -> "Click the LARGE FLAT face on TOP of the solid"

6. POCKET FAILS (Sub shape not found): Sketch has overlapping geometry.
   -> Include verification after Pocket. If it fails, Edit -> Undo and redo.

7. CONSTRAINT VALUE REJECTED: Input field has old text.
   -> "Triple-click the input field to select all, then type the value"

8. POCKET SKETCH NOT CENTERED: Inner rectangle drawn near an edge, pocket cuts through walls.
   -> Draw the inner rectangle CENTERED on the top face. Pick the first corner roughly
      {wall_thickness}mm inside the top-left edge and the second corner roughly
      {wall_thickness}mm inside the bottom-right edge. The rectangle MUST be fully
      inside the face boundary with equal margins on all sides.

## VERIFICATION CHECKPOINTS (your plan MUST include these):
- After rectangle: "VERIFY: 4 white/green lines forming a rectangle in the viewport"
- After constraint: "VERIFY: a dimension annotation (number with arrows) near the edge"
- After pad: "VERIFY: model tree shows 'Pad' under 'Body', 3D solid visible"
- After pocket sketch: "VERIFY: sketch grid appears on the top face"
- After pocket: "VERIFY: model tree shows 'Pocket', 3D view shows hollow interior"

## IMPORTANT RULES FOR THE PLAN
- Step 1 MUST be: "Minimize the terminal window" (right-click terminal in taskbar -> Minimize)
- The LAST step MUST be: Call task_complete(summary="description of what was built")
- For Rectangle: ALWAYS use shortcut G R (press G then R). NEVER navigate the 3-level menu.
- For Constrain distance: ALWAYS use shortcut K D (press K then D). NEVER navigate the 3-level menu.
- For everything else: use MENU navigation (Create body, Create sketch, Pad, Pocket, Close sketch, etc.)
- The keyboard actions allowed are: G, R, K, D (shortcuts), Escape (cancel tool), typing values in dialogs.
- Use "Edit" menu -> "Undo" for mistakes (not Ctrl+Z).
- NEVER click small toolbar icons — use the menu bar text (Sketch, Part Design, Edit, etc.)

## OUTPUT FORMAT
Return a numbered action script. Each step is ONE atomic action the agent performs.
Format:
  1. ACTION: <what to do>
     HOW: <exact menu path or click>
     IF_ERROR: <recovery action>
     VERIFY: <what the screen should show>
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
        return f"""## ACTION SCRIPT — Follow each step exactly. Use G R for rectangle, K D for constraints, menus for everything else.

STEP 1: Minimize the terminal window.
  ACTION: Right-click the terminal in the TASKBAR (top bar) and click "Minimize"
  VERIFY: The terminal is gone. You can see the desktop or FreeCAD.

STEP 2: Open FreeCAD (if not already open). Look at the screen.

STEP 3: Create a new body.
  ACTION: Click "Part Design" in the menu bar, then click "Create body"
  VERIFY: "Body" appears in the model tree on the left

STEP 4: Create a sketch on XY plane.
  ACTION: Click "Sketch" in the menu bar (NOT Part Design!), then click "Create sketch"
  ACTION: In the dialog, select "XY_Plane" and click OK
  VERIFY: A sketch grid appears in the viewport

STEP 5: Draw a rectangle using the keyboard shortcut.
  ACTION: Press key_combination("g"), then press key_combination("r") to activate the rectangle tool
  ACTION: Click a first corner in the upper-left area of the viewport
  ACTION: Click a second corner diagonally opposite (lower-right area)
  ACTION: Press key_combination("escape") to exit the rectangle tool
  VERIFY: You see 4 lines forming a rectangle. NEVER draw a second rectangle.

STEP 6: Constrain the horizontal edge to {width} mm.
  ACTION: Click on one HORIZONTAL edge of the rectangle (it turns green when selected)
  ACTION: Press key_combination("k"), then press key_combination("d") to open constrain distance
  ACTION: A dialog appears. Triple-click the input field to select all, type "{width} mm"
  ACTION: Click the OK button in the dialog
  VERIFY: A dimension annotation showing {width} appears near the horizontal edge
  IF_ERROR: Click "Edit" menu -> "Undo", re-select the edge, and try again

STEP 7: Constrain the vertical edge to {depth} mm.
  DO NOT close the sketch yet!
  ACTION: Click on one VERTICAL edge of the rectangle (it turns green when selected)
  ACTION: Press key_combination("k"), then press key_combination("d") to open constrain distance
  ACTION: Triple-click the input field, type "{depth} mm"
  ACTION: Click the OK button
  VERIFY: A second dimension annotation showing {depth} appears near the vertical edge
  IF_ERROR: Click "Edit" menu -> "Undo", re-select the edge, and try again

STEP 8: Close the sketch.
  ONLY close after you see TWO dimension annotations.
  ACTION: Click "Sketch" menu -> "Close sketch"
  VERIFY: The sketch closes and you return to the 3D view

STEP 9: Pad the sketch to {height} mm.
  ACTION: Click "Part Design" menu, then "Create an additive feature", then "Pad"
  ACTION: In the Tasks panel, triple-click the Length field, type "{height}"
  ACTION: Click OK
  VERIFY: A 3D rectangular solid appears. The model tree shows "Pad" under "Body".

STEP 10: Re-center the view and switch to top-down.
  ACTION: Click "View" menu -> "Standard views" -> "Top"
  ACTION: Click "View" menu -> "Standard views" -> "Fit All"
  VERIFY: You see the solid from directly above, centered and filling the viewport.

STEP 11: Select the top face for the pocket.
  ACTION: Click on the LARGE FLAT face on TOP of the solid (it highlights green/blue)
  VERIFY: The face is highlighted. Do NOT click a thin side face.

STEP 12: Create a sketch on the top face.
  ACTION: Click "Sketch" in the menu bar (NOT Part Design!), then click "Create sketch"
  VERIFY: A sketch grid appears ON the top face (sketch is auto-attached to selected face)

STEP 13: Draw the inner rectangle CENTERED on the top face.
  ACTION: Press key_combination("g"), then press key_combination("r") to activate the rectangle tool
  ACTION: Click the first corner roughly {wall} mm INSIDE the top-left edge of the face
  ACTION: Click the second corner roughly {wall} mm INSIDE the bottom-right edge
  IMPORTANT: The rectangle MUST be fully inside the face with equal margins on all sides.
             Do NOT draw it near an edge — it must be CENTERED.
  ACTION: Press key_combination("escape") to exit the rectangle tool
  VERIFY: A rectangle appears INSIDE the face boundary. NEVER draw a second rectangle.

STEP 14: Constrain inner horizontal edge to {inner_width} mm.
  ACTION: Click on one HORIZONTAL edge of the inner rectangle (it turns green)
  ACTION: Press key_combination("k"), then press key_combination("d") to open constrain distance
  ACTION: Triple-click the input field, type "{inner_width} mm"
  ACTION: Click the OK button
  VERIFY: A dimension annotation showing {inner_width} appears
  IF_ERROR: Click "Edit" menu -> "Undo" and retry

STEP 15: Constrain inner vertical edge to {inner_depth} mm.
  DO NOT CLOSE THE SKETCH. You must constrain the vertical edge too.
  ACTION: Click on one VERTICAL edge of the inner rectangle (it turns green)
  ACTION: Press key_combination("k"), then press key_combination("d") to open constrain distance
  ACTION: Triple-click the input field, type "{inner_depth} mm"
  ACTION: Click the OK button
  VERIFY: TWO dimension annotations are visible (one for width, one for depth)
  IF_ERROR: Click "Edit" menu -> "Undo" and retry

STEP 16: Close the sketch.
  ONLY close after BOTH dimension annotations are visible.
  ACTION: Click "Sketch" menu -> "Close sketch"

STEP 17: Create the pocket.
  ACTION: Click "Part Design" menu, then "Create a subtractive feature", then "Pocket"
  ACTION: In the Tasks panel, triple-click the Length/Depth field, type "{pocket_depth}"
  ACTION: Click OK
  VERIFY: The 3D view shows a hollow box. The model tree shows "Pocket" under "Body".
  IF_ERROR: If "Sub shape not found", click "Edit" -> "Undo", re-select the top face, redo steps 12-17.

STEP 18: Final view — see the result.
  ACTION: Click "View" menu -> "Standard views" -> "Home"
  ACTION: Click "View" menu -> "Standard views" -> "Fit All"
  VERIFY: The hollow box is visible from an isometric angle, centered in the viewport.

STEP 19: Task complete.
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
