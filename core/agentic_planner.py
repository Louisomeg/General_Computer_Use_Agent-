# =============================================================================
# Agentic Planner — routes user goals to the right agent(s)
# =============================================================================
# Routes requests to agents and chains them when needed:
#   - "cad"          -> CAD agent only (dimensions already specified)
#   - "research"     -> Research agent only (pure information lookup)
#   - "research+cad" -> Research first, extract dimensions, then CAD
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

        # For CAD design tasks, expand compact dimension strings (e.g.
        # "50x30x5mm") into width/height/depth params, then generate a
        # goal-based prompt.
        if agent_name == "cad" and self._is_design_task(user_request):
            params = self._expand_dimensions(params, user_request)
            if not params:
                print("  [Planner] Design task without dimensions — adding defaults")
                params = self._get_default_dimensions(user_request)
            print(f"  [Planner] Params: {params}")
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
            # Simple common objects -> cad with defaults (no research needed)
            if any(obj in lower for obj in simple_objects):
                return "cad", request, {}
            # Specialized items -> research first
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

    @classmethod
    def _expand_dimensions(cls, params: dict, request: str) -> dict:
        """Expand compact dimension strings like '50x30x5mm' into width/height/depth.

        Also passes through already-expanded params unchanged.
        """
        if not params:
            return {}

        # Already expanded (has width/height/depth keys)
        if any(k in params for k in ["width", "height", "depth"]):
            return params

        # Look for a compact dimensions string like "50x30x5mm"
        import re
        dim_str = params.get("dimensions", "")
        if not dim_str:
            # Try the request itself
            dim_str = request

        # Match patterns like "50x30x5mm", "50x30x5", "50*30*5mm"
        m = re.search(r"(\d+)\s*[x×*]\s*(\d+)(?:\s*[x×*]\s*(\d+))?\s*(?:mm)?", dim_str, re.I)
        if m:
            expanded = {"width": f"{m.group(1)}mm", "height": f"{m.group(2)}mm"}
            if m.group(3):
                expanded["depth"] = f"{m.group(3)}mm"

            # For brackets, the third dimension is typically depth/thickness
            lower = request.lower()
            if any(w in lower for w in ["bracket", "l-shaped", "l shaped", "angle"]):
                expanded["leg_thickness"] = expanded.get("depth", "5mm")
            return expanded

        return params

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
        elif any(w in lower for w in ["l-bracket", "l bracket", "l-shaped", "l shaped"]):
            return {"width": "50mm", "height": "30mm", "depth": "5mm",
                    "leg_thickness": "5mm"}
        elif any(w in lower for w in ["u-channel", "u channel", "u-shaped", "u shaped"]):
            return {"width": "50mm", "height": "30mm", "depth": "5mm",
                    "wall_thickness": "5mm"}
        elif any(w in lower for w in ["t-bracket", "t bracket", "t-shaped", "t shaped"]):
            return {"width": "60mm", "height": "40mm", "depth": "5mm",
                    "wall_thickness": "5mm"}
        elif any(w in lower for w in ["bracket", "mount", "angle"]):
            return {"width": "50mm", "height": "30mm", "depth": "5mm",
                    "wall_thickness": "5mm"}
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

    # ── FreeCAD tips (minimal — only things Flash can't figure out visually) ──

    FREECAD_TIPS = """## Critical FreeCAD Tips
- Rectangle shortcut: press G then R (bypasses broken 3-level submenu)
- Constrain distance shortcut: press K then D (bypasses broken 3-level submenu)
- Create sketch is under "Sketch" menu, NOT "Part Design" menu
- Select an edge BEFORE pressing K D to constrain it
- Constrain BOTH width and height before closing a sketch
- Thickness tool: select a face, then click Thickness in the left panel or Part Design menu. It hollows out a solid block — easiest way to make boxes, trays, and channels
- Use View -> Standard views -> Fit All to re-center the object after major operations
- Use "Edit" menu -> "Undo" if something goes wrong
- Call task_complete() when done
"""

    # ── Shape decomposition (complex shapes → simple rectangle operations) ──

    SHAPE_PATTERNS = {
        "l_bracket": ["l-shaped", "l shaped", "l bracket", "l-bracket"],
        "u_channel": ["u-shaped", "u shaped", "u channel", "u-channel"],
        "t_bracket": ["t-shaped", "t shaped", "t bracket", "t-bracket"],
        "cylinder_hole": ["cylinder with", "hole through", "tube", "pipe"],
        "shelf": ["shelf", "bookend"],
    }

    @classmethod
    def _detect_shape(cls, request: str) -> str | None:
        """Detect if the request is a complex shape we should decompose."""
        lower = request.lower()
        for shape, keywords in cls.SHAPE_PATTERNS.items():
            if any(kw in lower for kw in keywords):
                return shape
        return None

    @classmethod
    def _decompose_shape(cls, shape: str, params: dict) -> dict:
        """Return decomposition info: bounding box + cutout dimensions + workflow.

        Strategy: build complex shapes by subtracting rectangles from a
        bounding-box block.  Flash already knows rectangles (G R), pad,
        and pocket — no polylines needed.
        """
        w = cls._parse_mm(params.get("width") or params.get("total_width", "")) or 50.0
        h = cls._parse_mm(params.get("height") or params.get("total_height", "")) or 30.0
        d = cls._parse_mm(params.get("depth") or params.get("total_depth",
                          params.get("thickness", ""))) or 5.0
        wall = cls._parse_mm(params.get("wall_thickness") or
                             params.get("leg_thickness", "")) or d  # leg width = depth for brackets

        if shape == "l_bracket":
            # L = full rectangle minus one corner
            # Bounding box: w x h, extruded d
            # Cutout: (w - wall) x (h - wall) at one corner
            cut_w = w - wall
            cut_h = h - wall
            return {
                "box_w": w, "box_h": h, "box_d": d,
                "cuts": [{"w": cut_w, "h": cut_h, "label": "corner cutout"}],
                "workflow": (
                    f"Step 1: Create body -> Sketch on XY plane -> "
                    f"G R rectangle -> constrain to {w}x{h}mm -> Close sketch -> Pad {d}mm\n"
                    f"Step 2: Select top face -> Sketch on face -> "
                    f"G R rectangle in one corner -> constrain to {cut_w}x{cut_h}mm -> "
                    f"Close sketch -> Pocket through all\n"
                    f"Result: L-shaped bracket with {wall}mm thick legs"
                ),
            }

        elif shape == "u_channel":
            # U-channel = a box open at the top (like a tray with tall walls)
            # Use Thickness tool — Flash already knows this from box-making
            return {
                "box_w": w, "box_h": h, "box_d": d,
                "cuts": [],
                "workflow": (
                    f"Step 1: Create body -> Sketch on XY plane -> "
                    f"G R rectangle -> constrain to {w}x{h}mm -> Close sketch -> Pad {h}mm\n"
                    f"Step 2: Click the top face of the block -> "
                    f"Use Thickness tool (Part Design menu or left panel) -> "
                    f"set thickness to {wall}mm -> OK\n"
                    f"Result: U-channel / open-top tray with {wall}mm thick walls"
                ),
            }

        elif shape == "t_bracket":
            # T = full rectangle minus two top corners
            cut_w = (w - wall) / 2
            cut_h = h - wall
            return {
                "box_w": w, "box_h": h, "box_d": d,
                "cuts": [
                    {"w": cut_w, "h": cut_h, "label": "left corner cutout"},
                    {"w": cut_w, "h": cut_h, "label": "right corner cutout"},
                ],
                "workflow": (
                    f"Step 1: Create body -> Sketch on XY plane -> "
                    f"G R rectangle -> constrain to {w}x{h}mm -> Close sketch -> Pad {d}mm\n"
                    f"Step 2: Select top face -> Sketch on face -> "
                    f"G R rectangle in top-left corner -> constrain to {cut_w}x{cut_h}mm -> "
                    f"Close sketch -> Pocket through all\n"
                    f"Step 3: Select top face -> Sketch on face -> "
                    f"G R rectangle in top-right corner -> constrain to {cut_w}x{cut_h}mm -> "
                    f"Close sketch -> Pocket through all\n"
                    f"Result: T-shaped bracket with {wall}mm thick web"
                ),
            }

        # Default: no decomposition needed
        return None

    def _generate_cad_goal(
        self, original_request: str, cad_params: dict,
        research_summary: str = "",
    ) -> str:
        """Build a SHORT goal-based prompt for the CAD agent.

        Philosophy: Flash is a vision agent — it works BEST when given a clear
        goal and dimensions, then allowed to look at the screen and figure out
        the clicks.  Detailed step-by-step scripts (19 steps, 7000+ chars)
        actually make it WORSE because it stops using visual reasoning and
        tries to follow text literally, repeating coordinates from the plan.

        We provide ONLY: the goal, dimensions, and a few critical tips for
        things that genuinely can't be figured out visually (keyboard shortcuts
        for broken submenus, which menu has "Create sketch", etc).

        For complex shapes (L-bracket, U-channel, T-bracket), we decompose
        them into simple rectangle + pocket operations that Flash already
        knows how to do — no polylines needed.
        """
        # Check if this is a complex shape we should decompose
        shape = self._detect_shape(original_request)
        decomposition = self._decompose_shape(shape, cad_params) if shape else None

        if decomposition:
            print(f"  [Planner] Decomposing {shape} into rectangle+pocket operations")
            return self._build_decomposed_goal(
                original_request, decomposition, research_summary,
            )

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

        lower = original_request.lower()
        is_hollow = any(w in lower for w in [
            "box", "case", "enclosure", "container", "chest", "holder",
            "tray", "drawer", "bin", "hollow",
        ])

        parts = [f"## Goal\n{original_request}\n"]

        if research_summary:
            parts.append(f"## Context\n{research_summary}\n")

        parts.append("## Dimensions")
        parts.append(f"- Outer: {width} x {depth} x {height} mm")
        if is_hollow:
            parts.append(f"- Wall thickness: {wall} mm")

        parts.append("")

        if is_hollow:
            parts.append("## Workflow")
            parts.append("Create body -> Sketch on XY plane -> Rectangle -> "
                         f"Constrain to {width}x{depth}mm -> Close sketch -> "
                         f"Pad {height}mm -> Click top face -> "
                         f"Thickness tool (set to {wall}mm) -> OK")
        else:
            parts.append("## Workflow")
            parts.append("Create body -> Sketch -> Draw profile -> "
                         "Constrain dimensions -> Close sketch -> Pad/Extrude")

        parts.append("")
        parts.append(self.FREECAD_TIPS)

        goal = "\n".join(parts)
        print(f"  [Planner] Goal prompt: {len(goal)} chars")
        return goal

    def _build_decomposed_goal(
        self, original_request: str, decomposition: dict,
        research_summary: str = "",
    ) -> str:
        """Build a goal prompt for shapes decomposed into rectangle+pocket ops."""
        parts = [f"## Goal\n{original_request}\n"]

        if research_summary:
            parts.append(f"## Context\n{research_summary}\n")

        parts.append("## Build Strategy (use ONLY rectangles — no polylines)")
        parts.append(decomposition["workflow"])
        parts.append("")
        parts.append(self.FREECAD_TIPS)

        goal = "\n".join(parts)
        print(f"  [Planner] Decomposed goal prompt: {len(goal)} chars")
        return goal

    def _build_cad_description(
        self, original_request: str, research_data: dict,
        cad_params: dict | None = None,
    ) -> str:
        """Build the CAD task description — goal + dimensions + minimal tips.

        Philosophy: give the vision agent a clear goal and let it figure out
        the clicks by looking at the screen. Less text = better performance.
        """
        findings = research_data.get("findings", {})
        summary = findings.get("summary", "")
        cad_params = cad_params or {}

        if cad_params:
            return self._generate_cad_goal(
                original_request, cad_params, summary,
            )
        else:
            parts = [f"## Goal\n{original_request}\n"]
            if summary:
                parts.append(f"## Context\n{summary}\n")
            parts.append(self.FREECAD_TIPS)
            return "\n".join(parts)
