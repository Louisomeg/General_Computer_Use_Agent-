# =============================================================================
# CAD Agent — FreeCAD design agent
# =============================================================================
# Receives high-level design tasks from the planner, decomposes them,
# and drives FreeCAD through the agentic loop + desktop executor.
#
# Usage:
#   from agents.registry import get_agent
#   from core.models import Task
#
#   agent = get_agent("cad", client=client, executor=executor)
#   task = Task(description="Create an M10x30 hex bolt", params={...})
#   result = agent.execute(task)

import re
import subprocess

from google.genai import Client, types

from agents.registry import register
from core.agentic_loop import AgenticLoop
from core.custom_tools import get_custom_declarations
from core.executor import Executor
from core.models import Task, TaskStatus, ProcedureState, load_skill, load_tutorial_skills
from core.settings import SYSTEM_INSTRUCTION


# Agent Card — describes what this agent can do (A2A-style, kept in code)
AGENT_CARD = {
    "name": "cad_agent",
    "description": "Creates and modifies 3D CAD models in FreeCAD from specifications",
    "version": "0.1.0",
    "skills": [
        {
            "name": "create_3d_part",
            "description": "Design and model a 3D mechanical part from a description and dimensions",
        },
        {
            "name": "modify_part",
            "description": "Modify an existing part — add features, change dimensions, apply operations",
        },
        {
            "name": "create_sketch",
            "description": "Create a 2D sketch with geometry and constraints on a given plane",
        },
    ],
}


# ---------------------------------------------------------------------------
# CAD-specific ADDENDUM — extends the base SYSTEM_INSTRUCTION, not replaces it
# ---------------------------------------------------------------------------
# The base SYSTEM_INSTRUCTION (from core.settings) teaches the model:
#   - coordinate system (0-1000 normalized grid, denormalized to screen pixels)
#   - visual-first navigation (look at screenshot, click visible elements)
#   - GNOME desktop navigation (Activities, taskbar, app grid)
#   - 5-step application launch procedure
#   - FreeCAD basics (menus, toolbars, panels)
#
# This addendum adds CAD-specific workflow on top of that foundation.
# ---------------------------------------------------------------------------

CAD_ADDENDUM = """

## CRITICAL: Terminal Window
When you start, you will see a terminal window on screen running the agent script.
IMMEDIATELY right-click the terminal in the TASKBAR (top bar) and click "Minimize",
or click the minimize button (—) in the terminal's title bar. Do NOT try to close,
read, or interact with the terminal — just minimize it and move on.
After minimizing, focus EXCLUSIVELY on FreeCAD for the rest of the task.

## PRIMARY METHOD: Use FreeCAD Menus for ALL Operations
FreeCAD toolbar icons are TINY (~24px) and packed tightly together — NEVER click them.

ALWAYS use the MENU BAR at the top of the window for ALL FreeCAD operations:

- Sketcher geometry tools: "Sketch" menu → "Sketcher geometries" → choose tool
  (Rectangle, Line, Circle, Arc, Polyline, etc.)
- Sketcher constraints: "Sketch" menu → "Sketcher constraints" → choose constraint
  (Constrain distance, Constrain horizontal, Constrain equal, etc.)
- Close sketch: "Sketch" menu → "Close sketch"
- Pad / Pocket / Fillet: "Part Design" menu → choose operation
- Create sketch / Create body: "Part Design" menu → choose item
  NOTE: In FreeCAD 1.0, the menu item is "Create sketch" (NOT "New Sketch").
- View operations: "View" menu → "Standard views" → choose view
- File operations: "File" menu → "New", "Save", "Save As", "Export"
- Undo: "Edit" menu → "Undo" (use this instead of Ctrl+Z)

HOW TO NAVIGATE SUBMENUS:
1. Click the menu name in the menu bar (e.g. "Sketch")
2. A dropdown appears. Hover over the submenu item (e.g. "Sketcher geometries")
3. A second dropdown appears to the right. Click the specific tool (e.g. "Rectangle")
If the submenu doesn't appear, try clicking on the submenu item instead of hovering.

THE ONLY KEYBOARD ACTIONS YOU SHOULD USE:
- key_combination("escape") — cancel an active tool (e.g. after drawing a rectangle)
- key_combination("ctrl+z") — undo mistakes (press MULTIPLE TIMES)
- Typing values into dialog fields (e.g. "30 mm" in a constraint dialog)
- If Escape or Undo seems to not work, click once in the 3D viewport first, then retry.

Safe mouse clicks:
- Drawing geometry (clicking corner points for rectangle, etc.)
- Selecting edges/faces for constraints
- Clicking "OK" / "Close" buttons in the Tasks panel (left side)
- Clicking items in the model tree (left panel)
- Clicking menu items in the menu bar

## How FreeCAD's Rectangle Tool Works (IMPORTANT)
The rectangle tool uses a TWO-CLICK workflow:
1. Activate the tool via: "Sketch" menu → "Sketcher geometries" → "Rectangle"
2. Click the FIRST corner point in the viewport
3. Click the SECOND corner point (the opposite diagonal corner)
4. The rectangle is now created between those two points
5. Press key_combination("escape") to exit the rectangle tool

AFTER the rectangle is drawn, add dimension constraints:
- Click on one HORIZONTAL edge of the rectangle (click at the midpoint of the line)
- Activate constraint via: "Sketch" menu → "Sketcher constraints" → "Constrain distance"
- A dialog appears with a number field — type the value WITH units, e.g. "30 mm"
  (always include " mm" after the number — FreeCAD may default to µm otherwise)
- Click the OK button in the dialog to confirm (do NOT just press Enter)
- Repeat for one VERTICAL edge

IMPORTANT: Draw the rectangle AWAY from the center origin (avoid the area where
the red X-axis and green Y-axis lines cross). Place both clicks in the upper-left
area of the viewport so edges don't overlap with axis lines.

## Closing the Sketch — CRITICAL
Do NOT rely on pressing Escape to close the sketch. Escape only cancels the active tool.
INSTEAD: use the menu: "Sketch" → "Close sketch". This is 100% reliable.
ALTERNATIVE: click the "Close" button in the Tasks panel (left side).

## Error Recovery — CRITICAL RULES
- NEVER use the Delete key. It permanently removes the WRONG thing.
- ALWAYS use "Edit" menu → "Undo" or key_combination("ctrl+z") to fix mistakes.
  Press MULTIPLE TIMES to undo several steps.
- If you trigger a wrong tool: key_combination("escape"), then undo multiple times.
- If you leave a sketch by accident: double-click "Sketch" in the model tree to re-enter.
- After 3 failed attempts at the SAME action, call task_complete() with a status report.
- Do NOT blindly repeat the same failed action — re-examine the screenshot each time.

## Completion
When finished, call task_complete(summary="description of what was built").
"""

# Full system prompt = base desktop instructions + CAD addendum
CAD_SYSTEM_INSTRUCTION = SYSTEM_INSTRUCTION + CAD_ADDENDUM


# Function declaration so the CAD agent can signal "I'm done"
TASK_COMPLETE_DECLARATION = types.FunctionDeclaration(
    name="task_complete",
    description=(
        "Call this when you have finished the design task or when you need to stop. "
        "Include a brief summary of what was created or what went wrong."
    ),
    parameters_json_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief description of what was created or accomplished",
            },
        },
        "required": ["summary"],
    },
)


@register("cad")
class CADAgent:
    """FreeCAD design agent that decomposes tasks and drives the desktop."""

    def __init__(self, client: Client, executor: Executor):
        self.client = client
        self.executor = executor

        self.loop = AgenticLoop(
            client,
            system_instruction=CAD_SYSTEM_INSTRUCTION,   # base + CAD addendum
            max_turns=100,
            extra_declarations=[TASK_COMPLETE_DECLARATION],
            custom_declarations=get_custom_declarations(),
        )
        self.state = None  # active ProcedureState, if running a skill

    @property
    def card(self) -> dict:
        return AGENT_CARD

    def _prepare_freecad_environment(self):
        """Clean up stale FreeCAD state before starting a task.

        Removes crash recovery files that trigger the "Document Recovery"
        dialog on startup, which wastes several agent turns every time.
        """
        recovery_paths = [
            "~/.local/share/FreeCAD/recovery",   # FreeCAD 1.0+
            "~/.FreeCAD/recovery",                # Older versions
        ]
        for path in recovery_paths:
            subprocess.run(
                ["bash", "-c", f"rm -rf {path}/* 2>/dev/null"],
                capture_output=True,
            )
        print("[CAD Agent] Cleaned FreeCAD recovery files")

    # ------------------------------------------------------------------
    # Shape detection & geometry-specific instructions
    # ------------------------------------------------------------------

    def _detect_shape(self, task: Task) -> str:
        """Detect the geometry type from task description and params."""
        desc = task.description.lower()
        params = task.params or {}

        if any(w in desc for w in ("cylinder", "circle", "disc", "tube", "pipe")):
            return "circle"
        if any(k in params for k in ("diameter", "radius")):
            return "circle"
        if any(w in desc for w in ("hex", "polygon")):
            return "polygon"
        if "across_flats" in params or "sides" in params:
            return "polygon"
        return "rectangle"

    def _parse_mm(self, value: str) -> float:
        """Parse a dimension string like '40mm' or '40 mm' to a float."""
        match = re.match(r'(\d+(?:\.\d+)?)', str(value))
        return float(match.group(1)) if match else 0.0

    def _get_pad_value(self, params: dict) -> str:
        """Extract the pad/extrude depth from params."""
        for key in ("height", "depth", "thickness"):
            if key in params:
                val = self._parse_mm(params[key])
                if val > 0:
                    return f"{val:g} mm"
        return "10 mm"

    def _get_constraint_values(self, shape: str, params: dict) -> dict:
        """Extract constraint values based on shape type and params."""
        if shape == "circle":
            diameter = 0
            for key in ("diameter", "dia"):
                if key in params:
                    diameter = self._parse_mm(params[key])
            if not diameter:
                for key in ("radius", "rad"):
                    if key in params:
                        diameter = self._parse_mm(params[key]) * 2
            radius = diameter / 2 if diameter else 20
            return {"radius": f"{radius:g} mm", "diameter": f"{diameter:g} mm"}

        elif shape == "polygon":
            across_flats = 0
            if "across_flats" in params:
                across_flats = self._parse_mm(params["across_flats"])
            sides = 6  # default hexagon
            if "sides" in params:
                sides = int(self._parse_mm(params["sides"]))
            return {"across_flats": f"{across_flats:g} mm", "sides": str(sides)}

        else:  # rectangle
            width = height = 0
            for key in ("length", "width", "x"):
                if key in params and not width:
                    width = self._parse_mm(params[key])
            for key in ("width", "breadth", "y"):
                if key in params and not height:
                    val = self._parse_mm(params[key])
                    if val != width:
                        height = val
            if not height:
                # Fallback: use second dimension found
                dims = [self._parse_mm(v) for v in params.values()
                        if re.match(r'\d', str(v))]
                if len(dims) >= 2:
                    width, height = dims[0], dims[1]
            return {
                "width": f"{width:g} mm" if width else "50 mm",
                "height": f"{height:g} mm" if height else "30 mm",
            }

    def _build_geometry_step(self, shape: str, params: dict) -> str:
        """Build step 6 (draw geometry + constrain) for the detected shape."""
        cv = self._get_constraint_values(shape, params)

        if shape == "circle":
            return (
                "6. Draw a circle and constrain its size:\n"
                "   a. Activate the circle tool via the MENU:\n"
                "      Click \"Sketch\" in the MENU BAR at the top of the window.\n"
                "      Hover over \"Sketcher geometries\" (a submenu arrow appears).\n"
                "      In the submenu, click \"Circle\" (it may be called \"Create circle by center\").\n"
                "      If the submenu doesn't appear, try clicking \"Sketcher geometries\" instead.\n"
                "   b. Click the CENTER of the circle at the ORIGIN POINT in the viewport.\n"
                "      The origin is where the red X-axis and green Y-axis lines cross.\n"
                "      Placing the center at the origin is ideal for circular profiles.\n"
                "   c. Click a SECOND point away from the center to set an approximate radius.\n"
                "      Click roughly 50-80 pixels away from the center — the exact size\n"
                "      does not matter, we will constrain it in the next step.\n"
                "   d. Press key_combination(\"escape\") to exit the circle tool.\n"
                "   e. Now constrain the radius:\n"
                "      Click on the CIRCLE EDGE (the curved line itself, NOT the center point).\n"
                "      Then activate the constraint via the MENU:\n"
                "      Click \"Sketch\" in the MENU BAR → hover \"Sketcher constraints\" →\n"
                "      click \"Constrain radius / diameter\" (or just \"Constrain radius\"\n"
                "      in some FreeCAD versions).\n"
                "      A dialog appears with a number input field.\n"
                f"      Type the RADIUS value with units: \"{cv['radius']}\"\n"
                f"      (This is the radius — half of the {cv['diameter']} diameter).\n"
                "      Click the \"OK\" button in the dialog.\n"
                f"   Verify: the circle should resize to exactly {cv['diameter']} diameter.\n\n"
            )

        elif shape == "polygon":
            return (
                "6. Draw a regular polygon and constrain its size:\n"
                "   a. Activate the polygon tool via the MENU:\n"
                "      Click \"Sketch\" in the MENU BAR at the top of the window.\n"
                "      Hover over \"Sketcher geometries\" (a submenu arrow appears).\n"
                "      In the submenu, click \"Regular polygon\".\n"
                "   b. A panel may appear in the Tasks area (left side) asking for the\n"
                f"      number of sides. Set it to {cv['sides']} (for a hexagon).\n"
                "   c. Click the CENTER at the ORIGIN POINT in the viewport.\n"
                "   d. Click a SECOND point to set the initial size (~50 pixels away).\n"
                "   e. Press key_combination(\"escape\") to exit the polygon tool.\n"
                "   f. Constrain the across-flats dimension:\n"
                "      Click on one FLAT EDGE of the polygon (not a vertex).\n"
                "      Then: \"Sketch\" menu → \"Sketcher constraints\" → \"Constrain distance\".\n"
                f"      Type \"{cv['across_flats']}\" in the dialog, then click OK.\n"
                "   Verify: the polygon should resize to the specified dimensions.\n\n"
            )

        else:  # rectangle
            return (
                "6. Draw the rectangle (TWO clicks, then add constraints):\n"
                "   a. Activate the rectangle tool via the MENU:\n"
                "      Click the \"Sketch\" text in the MENU BAR at the top of the window.\n"
                "      In the dropdown, hover over \"Sketcher geometries\" (a submenu arrow appears).\n"
                "      In the submenu that opens to the right, click \"Rectangle\".\n"
                "      If the submenu does not appear, try clicking \"Sketcher geometries\" instead.\n"
                "   b. Click the FIRST corner in the upper-left area of the viewport.\n"
                "      Look at the screenshot — place the click ABOVE and LEFT of the center\n"
                "      origin where the red and green axis lines cross. Stay away from those lines.\n"
                "   c. Click the SECOND corner, offset down-right from the first click.\n"
                "      This creates an approximate rectangle. Exact size does not matter yet.\n"
                "   d. Press key_combination(\"escape\") to exit the rectangle tool.\n"
                "   e. Now add a WIDTH constraint:\n"
                "      Click on one HORIZONTAL edge of the rectangle (click at the midpoint\n"
                "      of the line, not near a corner).\n"
                "      Then activate the distance constraint via the MENU:\n"
                "      Click \"Sketch\" in the MENU BAR → hover over \"Sketcher constraints\" →\n"
                "      click \"Constrain distance\" in the submenu.\n"
                "      A dimension dialog appears with a number input field.\n"
                "      IMPORTANT — UNIT HANDLING: Always type the number WITH the unit.\n"
                f"      Type \"{cv['width']}\" (with the space before mm).\n"
                "      FreeCAD may display a different default unit (like µm), so always\n"
                "      include \" mm\" after the number to ensure millimeters.\n"
                "      After typing, click the \"OK\" button in the dialog (do NOT press Enter).\n"
                "   f. Add a HEIGHT constraint:\n"
                "      Click on one VERTICAL edge of the rectangle.\n"
                "      Then activate the distance constraint via the MENU again:\n"
                "      Click \"Sketch\" → hover \"Sketcher constraints\" → click \"Constrain distance\".\n"
                f"      Type \"{cv['height']}\" with unit, then click OK.\n"
                "   Verify: the rectangle should resize to the exact dimensions.\n\n"
            )

    # ------------------------------------------------------------------
    # Multi-feature task detection & decomposition
    # ------------------------------------------------------------------

    def _parse_dim_string(self, dim_str: str) -> dict:
        """Parse a dimension string like '60x40x5mm' into {w, h, d}."""
        nums = re.findall(r'(\d+(?:\.\d+)?)', str(dim_str))
        result = {}
        if len(nums) >= 1:
            result['w'] = float(nums[0])
        if len(nums) >= 2:
            result['h'] = float(nums[1])
        if len(nums) >= 3:
            result['d'] = float(nums[2])
        return result

    def _is_multi_feature(self, task: Task) -> bool:
        """Detect if a task requires multiple Part Design features.

        Multi-feature indicators:
        - Multiple dimension groups (e.g. base_plate + vertical_wall)
        - Keywords like bracket, fillet, chamfer, pocket, hole
        - Multiple XxYxZ patterns in description
        """
        desc = task.description.lower()
        params = task.params or {}

        # Multiple XxYxZ dimension patterns in description
        dim_patterns = re.findall(r'\d+x\d+(?:x\d+)?', desc)
        if len(dim_patterns) >= 2:
            return True

        # Compound param keys (base_plate, vertical_wall, etc.)
        compound_keys = sum(1 for k, v in params.items()
                           if re.search(r'\d+x\d+', str(v)))
        if compound_keys >= 2:
            return True

        # Multi-feature operation keywords
        multi_kw = ("bracket", "fillet", "chamfer", "pocket", "hole",
                    "groove", "slot", "notch", "boss", "rib",
                    "step", "counterbore", "countersink")
        if any(kw in desc for kw in multi_kw):
            return True

        return False

    def _decompose_task(self, task: Task) -> list[dict]:
        """Decompose a multi-feature task into sequential operations.

        Each returned dict has:
          - title: human label for logging
          - prompt: full prompt for one agentic_loop() call

        The model sees each step independently with a fresh context,
        but FreeCAD state carries over (the 3D model accumulates features).
        """
        desc = task.description.lower()
        params = task.params or {}

        if "l-bracket" in desc or "l bracket" in desc or "l-shape" in desc:
            return self._decompose_l_bracket(params, task.description)

        if "t-bracket" in desc or "t bracket" in desc or "t-shape" in desc:
            return self._decompose_t_bracket(params, task.description)

        # Generic: try to decompose based on param structure
        return self._decompose_generic(params, task.description)

    def _decompose_l_bracket(self, params: dict, description: str) -> list[dict]:
        """Decompose an L-bracket into base plate + wall + fillets."""
        base_dims = None
        wall_dims = None
        fillet_r = 3.0  # default

        # ── Strategy 1: Extract NxNxN patterns from the task DESCRIPTION ──
        # This is the most reliable source since the planner may rename params
        # inconsistently (e.g. base_length/base_width/base_thickness vs base_dimensions).
        dim_matches = re.findall(r'(\d+)x(\d+)x(\d+)', description)
        if len(dim_matches) >= 2:
            d1 = [float(x) for x in dim_matches[0]]
            d2 = [float(x) for x in dim_matches[1]]
            base_dims = {'w': d1[0], 'h': d1[1], 'd': d1[2]}
            wall_dims = {'w': d2[0], 'h': d2[1], 'd': d2[2]}

        # ── Strategy 2: Compound param values (e.g. base_dimensions: '60x40x5mm') ──
        if not base_dims or not wall_dims:
            for key, val in params.items():
                val_str = str(val)
                key_lower = key.lower()
                # Only match values containing 'x' (compound dims like 60x40x5mm)
                if 'x' in val_str and re.search(r'\d+x\d+', val_str):
                    if any(k in key_lower for k in ("base", "plate", "bottom", "floor")):
                        base_dims = base_dims or self._parse_dim_string(val_str)
                    elif any(k in key_lower for k in ("wall", "vertical", "upright", "side")):
                        wall_dims = wall_dims or self._parse_dim_string(val_str)

        # ── Strategy 3: Individual params (e.g. base_length: 60mm, base_width: 40mm) ──
        if not base_dims:
            bd = {}
            for key, val in params.items():
                key_lower = key.lower()
                if not any(k in key_lower for k in ("base", "plate", "bottom", "floor")):
                    continue
                parsed = self._parse_mm(str(val))
                if not parsed:
                    continue
                if any(s in key_lower for s in ("length", "len", "long")):
                    bd['w'] = parsed
                elif any(s in key_lower for s in ("width", "wid", "breadth")):
                    bd['h'] = parsed
                elif any(s in key_lower for s in ("thick", "depth", "height")):
                    bd['d'] = parsed
            if bd:
                base_dims = bd

        if not wall_dims:
            wd = {}
            for key, val in params.items():
                key_lower = key.lower()
                if not any(k in key_lower for k in ("wall", "vertical", "upright", "side")):
                    continue
                parsed = self._parse_mm(str(val))
                if not parsed:
                    continue
                if any(s in key_lower for s in ("width", "wid", "breadth", "length", "len")):
                    wd['w'] = parsed
                elif any(s in key_lower for s in ("height", "tall", "high")):
                    wd['h'] = parsed
                elif any(s in key_lower for s in ("thick", "depth")):
                    wd['d'] = parsed
            if wd:
                wall_dims = wd

        # ── Extract fillet radius from params ──
        for key, val in params.items():
            key_lower = key.lower()
            if any(k in key_lower for k in ("fillet", "round")):
                parsed = self._parse_mm(str(val))
                if parsed > 0:
                    fillet_r = parsed
        # Also try extracting from description
        fillet_match = re.search(r'(\d+(?:\.\d+)?)\s*mm\s*fillet', description.lower())
        if fillet_match:
            fillet_r = float(fillet_match.group(1))

        # ── Defaults ──
        if not base_dims:
            base_dims = {'w': 60, 'h': 40, 'd': 5}
        if not wall_dims:
            wall_dims = {'w': 40, 'h': 30, 'd': 5}

        base_w = base_dims.get('w', 60)
        base_h = base_dims.get('h', 40)
        base_d = base_dims.get('d', 5)
        wall_w = wall_dims.get('w', 40)
        wall_h = wall_dims.get('h', 30)
        wall_d = wall_dims.get('d', 5)

        print(f"[CAD Agent] L-bracket: base={base_w}x{base_h}x{base_d}, "
              f"wall={wall_w}x{wall_h}x{wall_d}, fillet={fillet_r}")

        reference = self._build_reference_from_tutorials()

        steps = [
            # ── Step 1: Setup + base plate sketch + pad ──
            {
                "title": f"Base plate: {base_w}x{base_h}mm sketch, pad {base_d}mm",
                "prompt": (
                    f"## Task: Create the BASE PLATE of an L-bracket\n"
                    f"This is step 1 of 3. You are creating a {base_w}x{base_h}x{base_d}mm base plate.\n\n"
                    f"{reference}\n"
                    "## Execution Plan\n"
                    "Follow these steps IN ORDER. After each step, study the screenshot to confirm.\n\n"

                    "1. Minimize the terminal: right-click the terminal in the TASKBAR and click\n"
                    "   \"Minimize\", or click the minimize button (—) in the title bar.\n\n"

                    "2. Check if FreeCAD is open.\n"
                    "   If YES: click on its window in the taskbar. If it has existing work,\n"
                    "     create a NEW document: File menu → New.\n"
                    "   If NO: open it via Applications menu → Graphics → FreeCAD.\n"
                    "     Use wait_5_seconds to let it load.\n\n"

                    "3. Ensure Part Design workbench is active.\n"
                    "   Look at the menu bar — do you see \"Part Design\" as a menu item?\n"
                    "   If NO: find the workbench dropdown in the toolbar and select \"Part Design\".\n\n"

                    "4. Create a Body if none exists:\n"
                    "   If model tree already shows \"Body\" and \"Origin\": skip to step 5.\n"
                    "   Otherwise: Part Design menu → Create body.\n\n"

                    "5. Create a sketch on XY plane:\n"
                    "   Click \"Body\" in the model tree, then: Part Design menu → Create sketch.\n"
                    "   Select XY_Plane and click OK.\n\n"

                    "6. Draw a rectangle and constrain it:\n"
                    "   a. Sketch menu → Sketcher geometries → Rectangle.\n"
                    "   b. Click FIRST corner in the upper-left area (away from origin).\n"
                    "   c. Click SECOND corner offset down-right.\n"
                    "   d. Press Escape to exit the rectangle tool.\n"
                    "   e. Click one HORIZONTAL edge, then:\n"
                    "      Sketch menu → Sketcher constraints → Constrain distance.\n"
                    f"      Type \"{base_w} mm\" and click OK.\n"
                    "   f. Click one VERTICAL edge, then:\n"
                    "      Sketch menu → Sketcher constraints → Constrain distance.\n"
                    f"      Type \"{base_h} mm\" and click OK.\n\n"

                    "7. Close the sketch: Sketch menu → Close sketch.\n\n"

                    "8. Pad the sketch:\n"
                    "   Part Design menu → Pad.\n"
                    f"   Set Length to \"{base_d} mm\", click OK.\n"
                    "   Then: View menu → Standard views → Fit All.\n\n"

                    "9. Call task_complete(summary=\"Base plate created\").\n\n"

                    "CRITICAL RULES:\n"
                    "- Use MENU BAR for ALL operations, never click tiny toolbar icons.\n"
                    "- NEVER use Delete key — use Edit menu → Undo or Ctrl+Z.\n"
                    "- Draw rectangle AWAY from the origin center.\n"
                    "- Always type dimensions WITH \" mm\" unit.\n"
                    "- Close sketch via Sketch menu → Close sketch (NOT Escape).\n"
                ),
            },

            # ── Step 2: Vertical wall sketch on top face + pad ──
            {
                "title": f"Vertical wall: sketch on top face, pad {wall_h}mm",
                "prompt": (
                    f"## Task: Add the VERTICAL WALL to the L-bracket\n"
                    f"This is step 2 of 3. The base plate already exists.\n"
                    f"You need to add a {wall_w}x{wall_d}mm wall that rises {wall_h}mm from one edge.\n\n"
                    f"{reference}\n"
                    "## Execution Plan\n"
                    "The base plate (the rectangular solid) is already visible in FreeCAD.\n"
                    "You need to create a NEW sketch on the TOP face of the base plate.\n\n"

                    "1. First, look at the 3D viewport. You should see the base plate solid.\n"
                    "   If you cannot see it clearly, use: View menu → Standard views → Top.\n"
                    "   Then: View menu → Standard views → Fit All.\n\n"

                    "2. Select the TOP FACE of the base plate:\n"
                    "   Click directly on the TOP FACE of the solid in the 3D viewport.\n"
                    "   The face should highlight (change color) when selected.\n"
                    "   TIP: If you have trouble selecting the face, try:\n"
                    "   - View menu → Standard views → Top (to look straight down)\n"
                    "   - Then click on the flat rectangular surface\n\n"

                    "3. Create a new sketch on the selected face:\n"
                    "   With the top face selected, go to: Part Design menu → Create sketch.\n"
                    "   FreeCAD should automatically use the selected face as the sketch plane.\n"
                    "   If a plane dialog appears, select the face reference and click OK.\n\n"

                    "4. Draw the wall profile rectangle:\n"
                    "   The wall sits along ONE EDGE of the base plate.\n"
                    "   a. Sketch menu → Sketcher geometries → Rectangle.\n"
                    "   b. Click FIRST corner near one edge of the base plate outline.\n"
                    "      Position it at one end of the base plate.\n"
                    "   c. Click SECOND corner to create a narrow rectangle along that edge.\n"
                    f"      The rectangle should be roughly {wall_w}mm long and {wall_d}mm wide.\n"
                    "   d. Press Escape to exit the rectangle tool.\n\n"

                    "5. Constrain the wall rectangle:\n"
                    "   a. Click one HORIZONTAL edge (the long side), then:\n"
                    "      Sketch menu → Sketcher constraints → Constrain distance.\n"
                    f"      Type \"{wall_w} mm\" and click OK.\n"
                    "   b. Click one VERTICAL edge (the short side), then:\n"
                    "      Sketch menu → Sketcher constraints → Constrain distance.\n"
                    f"      Type \"{wall_d} mm\" and click OK.\n\n"

                    "6. Close the sketch: Sketch menu → Close sketch.\n\n"

                    "7. Pad the wall upward:\n"
                    "   Part Design menu → Pad.\n"
                    f"   Set Length to \"{wall_h} mm\", click OK.\n"
                    "   Then: View menu → Standard views → Fit All.\n"
                    "   You should now see the L-bracket shape: base plate with wall rising from one edge.\n\n"

                    "8. Call task_complete(summary=\"Vertical wall added\").\n\n"

                    "CRITICAL RULES:\n"
                    "- Use MENU BAR for ALL operations, never click tiny toolbar icons.\n"
                    "- NEVER use Delete key — use Edit menu → Undo or Ctrl+Z.\n"
                    "- Always type dimensions WITH \" mm\" unit.\n"
                    "- Close sketch via Sketch menu → Close sketch (NOT Escape).\n"
                    "- The wall rectangle must be positioned ALONG ONE EDGE of the base.\n"
                ),
            },

            # ── Step 3: Fillet at junction ──
            {
                "title": f"Apply {fillet_r}mm fillet at junction",
                "prompt": (
                    f"## Task: Apply FILLETS to the L-bracket junction\n"
                    f"This is step 3 of 3. The L-bracket (base plate + vertical wall) already exists.\n"
                    f"You need to apply {fillet_r}mm fillets at the junction edges where the wall meets the base.\n\n"
                    f"{reference}\n"
                    "## Execution Plan\n"
                    "The L-bracket is visible in FreeCAD. You need to select the junction\n"
                    "edges and apply a fillet operation.\n\n"

                    "1. First, get a good view of the L-bracket:\n"
                    "   View menu → Standard views → Home (or Isometric/Front).\n"
                    "   Then: View menu → Standard views → Fit All.\n"
                    "   You should see the L-shape clearly with the base and wall.\n\n"

                    "2. Select the junction edge(s):\n"
                    "   The junction is the INNER edge(s) where the vertical wall meets the base plate.\n"
                    "   Click on one of these EDGES (the line where base and wall meet on the INSIDE).\n"
                    "   The edge should highlight when selected.\n"
                    "   TIP: You may need to rotate the view to see the inner edges clearly.\n"
                    "   Use middle-mouse-button drag or: View menu → Standard views to change angle.\n\n"

                    "3. Apply the Fillet:\n"
                    "   With the edge selected, go to: Part Design menu → Fillet.\n"
                    "   A dialog appears in the Tasks panel with a Radius input field.\n"
                    f"   Set the Radius to \"{fillet_r} mm\".\n"
                    "   Click OK to apply the fillet.\n"
                    "   You should see the sharp edge replaced by a smooth rounded surface.\n\n"

                    "4. Verify and finish:\n"
                    "   View menu → Standard views → Fit All.\n"
                    "   Check that the fillet is applied correctly at the junction.\n\n"

                    "5. Call task_complete(summary=\"Fillets applied to L-bracket junction\").\n\n"

                    "CRITICAL RULES:\n"
                    "- Use MENU BAR for ALL operations.\n"
                    "- Select EDGES, not faces, for the fillet operation.\n"
                    "- The fillet is on the INSIDE junction, not the outside.\n"
                    "- If fillet fails, try selecting a different edge at the junction.\n"
                    "- Always type dimensions WITH \" mm\" unit.\n"
                ),
            },
        ]

        return steps

    def _decompose_t_bracket(self, params: dict, description: str) -> list[dict]:
        """Decompose a T-bracket into base + vertical member + fillets."""
        # Similar to L-bracket but wall is centered on base
        # For now, delegate to generic
        return self._decompose_generic(params, description)

    def _decompose_generic(self, params: dict, description: str) -> list[dict]:
        """Generic decomposition: extract features from params and build steps."""
        # Find dimension groups in params (values matching NxNxN or NxN)
        features = []
        fillet_r = None

        for key, val in params.items():
            val_str = str(val)
            key_lower = key.lower()
            dims = self._parse_dim_string(val_str)
            if dims.get('w') and dims.get('h'):
                features.append({'name': key, 'dims': dims})
            elif any(k in key_lower for k in ("fillet", "chamfer", "radius", "round")):
                parsed = self._parse_mm(val_str)
                if parsed > 0:
                    fillet_r = parsed

        if not features:
            # Can't decompose — fall back to single-feature
            return []

        reference = self._build_reference_from_tutorials()
        steps = []

        for i, feat in enumerate(features):
            d = feat['dims']
            w = d.get('w', 50)
            h = d.get('h', 30)
            depth = d.get('d', 10)
            name = feat['name'].replace('_', ' ').title()
            is_first = (i == 0)

            setup_block = ""
            if is_first:
                setup_block = (
                    "1. Minimize the terminal (right-click taskbar → Minimize).\n\n"
                    "2. Open FreeCAD if not already open (Applications → Graphics → FreeCAD).\n"
                    "   If it has existing work, create a new document: File → New.\n\n"
                    "3. Ensure Part Design workbench is active (check menu bar).\n\n"
                    "4. Create a Body if needed: Part Design menu → Create body.\n\n"
                    "5. Create sketch on XY plane: Part Design menu → Create sketch → XY_Plane → OK.\n\n"
                )
            else:
                setup_block = (
                    "1. Select the TOP FACE of the existing solid in the 3D viewport.\n"
                    "   Click directly on the face — it should highlight.\n"
                    "   TIP: Use View menu → Standard views → Top to look straight down.\n\n"
                    "2. Create a new sketch on that face: Part Design menu → Create sketch.\n\n"
                )

            step_offset = 6 if is_first else 3
            steps.append({
                "title": f"{name}: {w}x{h}mm sketch, pad {depth}mm",
                "prompt": (
                    f"## Task: Create feature '{name}' ({w}x{h}x{depth}mm)\n"
                    f"This is feature {i+1} of {len(features)}.\n"
                    f"{'This is the first feature — start from scratch.' if is_first else 'Previous features already exist in the model.'}\n\n"
                    f"{reference}\n"
                    "## Execution Plan\n\n"
                    f"{setup_block}"
                    f"{step_offset}. Draw a rectangle and constrain it:\n"
                    "   a. Sketch menu → Sketcher geometries → Rectangle.\n"
                    "   b. Click FIRST corner, then SECOND corner.\n"
                    "   c. Press Escape to exit tool.\n"
                    "   d. Click horizontal edge → Sketch menu → Sketcher constraints → Constrain distance.\n"
                    f"      Type \"{w} mm\" → OK.\n"
                    "   e. Click vertical edge → Sketch menu → Sketcher constraints → Constrain distance.\n"
                    f"      Type \"{h} mm\" → OK.\n\n"
                    f"{step_offset+1}. Close sketch: Sketch menu → Close sketch.\n\n"
                    f"{step_offset+2}. Pad: Part Design menu → Pad. Length = \"{depth} mm\". OK.\n"
                    "   View menu → Standard views → Fit All.\n\n"
                    f"{step_offset+3}. Call task_complete(summary=\"{name} created\").\n\n"
                    "CRITICAL: Use MENU BAR for everything. Type \" mm\" with dimensions. Never use Delete key.\n"
                ),
            })

        # Add fillet step if specified
        if fillet_r:
            steps.append({
                "title": f"Apply {fillet_r}mm fillets",
                "prompt": (
                    f"## Task: Apply {fillet_r}mm fillets to junction edges\n"
                    f"{reference}\n"
                    "## Execution Plan\n"
                    "1. View menu → Standard views → Home/Isometric → Fit All.\n"
                    "2. Click on the INNER junction EDGE where features meet.\n"
                    "3. Part Design menu → Fillet.\n"
                    f"4. Set Radius to \"{fillet_r} mm\", click OK.\n"
                    "5. Call task_complete(summary=\"Fillets applied\").\n"
                ),
            })

        return steps

    def _execute_multi_feature(self, task: Task, steps: list[dict]):
        """Execute a decomposed multi-feature task step by step.

        Each step runs as an independent agentic_loop() call with its own
        context and turn budget. FreeCAD state carries over between steps
        because the desktop persists.

        If a step crashes (API error, etc.), remaining steps are skipped
        because they depend on the previous step's FreeCAD state.
        """
        total = len(steps)
        print(f"[CAD Agent] Multi-feature task: {total} steps")

        for i, step in enumerate(steps):
            print(f"[CAD Agent] Step {i+1}/{total}: {step['title']}")
            try:
                self.loop.agentic_loop(step["prompt"], self.executor)
                print(f"[CAD Agent] Step {i+1}/{total} complete")
            except Exception as e:
                print(f"[CAD Agent] Step {i+1}/{total} FAILED: {e}")
                print(f"[CAD Agent] Aborting remaining {total - i - 1} steps")
                raise

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def execute(self, task: Task) -> Task:
        """Execute a CAD design task.

        The agent will:
        1. Clean up FreeCAD environment (recovery files)
        2. Check if a YAML skill exists for the task
        3. If yes — decompose using the skill steps
        4. Check if the task is multi-feature (bracket, fillet, etc.)
        5. If yes — decompose into sequential operations
        6. Otherwise — build a single prompt and let the agentic loop handle it
        """
        task.status = TaskStatus.WORKING
        print(f"\n[CAD Agent] Starting task: {task.description}")
        self._prepare_freecad_environment()

        try:
            # Check for a matching skill file
            skill = self._find_skill(task)

            if skill:
                self._execute_skill(task, skill)
            elif self._is_multi_feature(task):
                steps = self._decompose_task(task)
                if steps:
                    self._execute_multi_feature(task, steps)
                else:
                    # Decomposition failed, fall back to freeform
                    self._execute_freeform(task)
            else:
                self._execute_freeform(task)

            task.complete(result="Design completed successfully")
            print(f"[CAD Agent] Task completed: {task.id}")

        except Exception as e:
            task.fail(error=str(e))
            print(f"[CAD Agent] Task failed: {e}")

        return task

    def _find_skill(self, task: Task) -> dict | None:
        """Try to find a YAML skill that matches the task."""
        from core.models import list_skills

        # 1. Check if params specify a part/skill name directly
        for key in ("part", "skill"):
            name = task.params.get(key)
            if name:
                skill = load_skill(name)
                if skill:
                    print(f"[CAD Agent] Found skill via param '{key}': {name}")
                    return skill

        # 2. Check if any available skill name appears in the task description
        description_lower = task.description.lower()
        for skill_name in list_skills():
            # Match underscored name and spaced name (bicycle_stem / bicycle stem)
            if skill_name in description_lower or skill_name.replace("_", " ") in description_lower:
                skill = load_skill(skill_name)
                if skill:
                    print(f"[CAD Agent] Found skill via description match: {skill_name}")
                    return skill

        return None

    def _execute_skill(self, task: Task, skill: dict):
        """Execute a task using a YAML skill definition."""
        steps = skill.get("steps", [])
        self.state = ProcedureState(
            skill_name=skill["name"],
            total_steps=len(steps),
        )

        print(f"[CAD Agent] Running skill '{skill['name']}' ({len(steps)} steps)")

        for i, step in enumerate(steps):
            self.state.current_step = i
            step_label = step.get("title", step.get("skill", str(step)[:80]))
            print(f"[CAD Agent] {self.state.progress}: {step_label}")

            # Build a prompt for this specific step
            prompt = self._build_step_prompt(step, task.params, i, len(steps))
            self.loop.agentic_loop(prompt, self.executor)
            self.state.advance()

        self.state = None

    def _execute_freeform(self, task: Task):
        """Execute a task with no matching skill — pure prompt-driven.

        Tutorial skills (type: tutorial) are always loaded and injected as
        reference material so the model knows how FreeCAD works even for
        tasks that don't match a specific skill by name.
        """
        prompt = self._build_prompt(task)
        print(f"[CAD Agent] No exact skill match, running freeform design with tutorial reference")
        self.loop.agentic_loop(prompt, self.executor)

    # ------------------------------------------------------------------
    # Tutorial reference builder
    # ------------------------------------------------------------------

    def _build_reference_from_tutorials(self) -> str:
        """Build a compact FreeCAD reference section from tutorial-type skills.

        Only extracts tips and troubleshooting — NOT full workflow steps.
        The execution plan already provides the step-by-step workflow, so
        injecting tutorial steps would create bloat and contradictions.
        """
        tutorials = load_tutorial_skills()
        if not tutorials:
            return ""

        # Deduplicate tips and troubleshooting across tutorials
        all_tips = []
        all_trouble = []
        seen_tips = set()
        seen_trouble = set()

        for skill in tutorials:
            for tip in skill.get("tips", []):
                key = tip[:60]  # Dedup by first 60 chars
                if key not in seen_tips:
                    seen_tips.add(key)
                    all_tips.append(tip)

            for item in skill.get("troubleshooting", []):
                key = item.get("problem", "")[:60]
                if key not in seen_trouble:
                    seen_trouble.add(key)
                    all_trouble.append(item)

        if not all_tips and not all_trouble:
            return ""

        parts = ["\n## FreeCAD Tips & Troubleshooting\n"]

        if all_tips:
            for tip in all_tips:
                parts.append(f"- {tip}")
            parts.append("")

        if all_trouble:
            parts.append("### Common Problems")
            for item in all_trouble:
                parts.append(f"- {item.get('problem', '')} → {item.get('solution', '')}")
            parts.append("")

        reference = "\n".join(parts)
        print(f"[CAD Agent] Loaded tutorial reference ({len(reference)} chars)")
        return reference

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_prompt(self, task: Task) -> str:
        """Build a task prompt for the agentic loop (freeform mode).

        Dynamically adapts step 6 (geometry) and step 8 (pad value) based on
        the detected shape type (rectangle, circle, polygon).

        NOTE: CAD_SYSTEM_INSTRUCTION is the loop's system_instruction,
        so we only include the task-specific details here.
        """
        parts = [f"## Current Task\n{task.description}\n"]

        # Add measurements if provided
        if task.params:
            parts.append("## Specifications")
            for key, value in task.params.items():
                label = key.replace("_", " ").title()
                parts.append(f"- {label}: {value}")
            parts.append("")

        # Inject tutorial reference material (tips, troubleshooting, workflow)
        reference = self._build_reference_from_tutorials()
        if reference:
            parts.append(reference)

        # Detect shape type and build geometry-specific instructions
        shape = self._detect_shape(task)
        geometry_step = self._build_geometry_step(shape, task.params or {})
        pad_value = self._get_pad_value(task.params or {})
        print(f"[CAD Agent] Detected shape: {shape}, pad: {pad_value}")

        parts.append(
            "## Execution Plan\n"
            "Follow these steps IN ORDER. After each step, study the screenshot to confirm it worked.\n"
            "If a step fails, read the PREREQUISITE CHECK before retrying.\n\n"

            "1. Minimize the terminal: right-click the terminal in the TASKBAR and click\n"
            "   \"Minimize\", or click the minimize button (—) in the terminal's title bar.\n\n"

            "2. Check if FreeCAD is open.\n"
            "   If YES: click on its window in the taskbar to bring it to focus.\n"
            "     IMPORTANT: If FreeCAD already has a document open with existing work\n"
            "     (you see shapes in the viewport or items in the model tree besides\n"
            "     the default empty state), create a NEW document: click \"File\" in the\n"
            "     MENU BAR → click \"New\". This gives you a clean start.\n"
            "     Do NOT try to modify or interact with existing geometry.\n"
            "   If NO: open it via the Applications menu → Graphics → FreeCAD.\n"
            "     Then use wait_5_seconds to let it load.\n\n"

            "3. Check if the Part Design workbench is active.\n"
            "   PREREQUISITE CHECK: Look at the menu bar at the very top of the window.\n"
            "   Do you see \"Part Design\" as one of the menu items (between other menus)?\n"
            "   - If YES: the workbench is active, proceed to step 4.\n"
            "   - If NO: you need to switch the workbench. Look for a DROPDOWN widget in\n"
            "     the toolbar area (below the menu bar) that shows the current workbench name\n"
            "     (it might say \"Start\" or something else). Click on that dropdown and select\n"
            "     \"Part Design\" from the list. Then verify the menu bar now shows \"Part Design\".\n\n"

            "4. Check if a Body already exists in the model tree (left panel).\n"
            "   - If the model tree already shows \"Body\" and \"Origin\": skip to step 5.\n"
            "   - If NOT: click the \"Part Design\" text in the MENU BAR (top of window),\n"
            "     then click \"Create body\" in the dropdown menu.\n"
            "     Verify: \"Body\" and \"Origin\" appear in the model tree.\n\n"

            "5. Create a new sketch on the XY plane:\n"
            "   PREREQUISITE CHECK: Is \"Body\" selected/highlighted in the model tree?\n"
            "   If not, click on \"Body\" in the model tree first.\n"
            "   Then: click the \"Part Design\" text in the MENU BAR at the top of the window.\n"
            "   In the dropdown, look for \"Create sketch\" (NOT \"New Sketch\" — FreeCAD 1.0\n"
            "   uses the name \"Create sketch\"). Click it.\n"
            "   ALTERNATIVE: If you cannot find it in the Part Design menu, look in the\n"
            "   Tasks panel (left side) under \"Helper tools\" for \"Create sketch\".\n"
            "   When the plane selector dialog appears, click \"XY_Plane\" then click OK.\n"
            "   Verify: you should see the sketcher grid with red/green axis lines.\n"
            "   NOTE: While inside the sketcher, the menu bar will show a \"Sketch\" menu.\n"
            "   Use this menu for ALL sketcher operations (geometry, constraints, close).\n\n"

            # ── Step 6: geometry-specific (rectangle, circle, or polygon) ──
            + geometry_step +

            "7. Close the sketch:\n"
            "   Do NOT press Escape to close the sketch — Escape only cancels the active tool.\n"
            "   Instead: click the \"Sketch\" text in the MENU BAR, then click \"Close sketch\".\n"
            "   ALTERNATIVE: click the \"Close\" button in the Tasks panel (left side).\n"
            "   Verify: the menu bar should now show \"Part Design\" menus (not \"Sketch\" menus).\n"
            "   You should see the sketch outline in the 3D viewport.\n\n"

            "8. Pad (extrude) the sketch:\n"
            "   Click \"Part Design\" in the MENU BAR at the top, then click \"Pad\" in the dropdown.\n"
            "   A dialog will appear in the Tasks panel (left side) with a Length input field.\n"
            f"   Click the Length field, clear it, type \"{pad_value}\" (WITH the unit).\n"
            "   Click OK to apply the pad.\n"
            "   Then zoom to fit: click \"View\" in the MENU BAR → click \"Standard views\" →\n"
            "   click \"Fit All\" to see the full 3D solid.\n"
            "   Verify: you should see a 3D solid in the viewport.\n\n"

            "9. Call task_complete() with a summary of what was built.\n\n"

            "CRITICAL RULES:\n"
            "- NEVER use the Delete key. Use Edit menu → Undo or key_combination(\"ctrl+z\").\n"
            "- Use the MENU BAR for ALL FreeCAD operations:\n"
            "  * Sketch menu → Sketcher geometries (for Rectangle, Line, Circle, etc.)\n"
            "  * Sketch menu → Sketcher constraints (for Constrain distance, Constrain radius, etc.)\n"
            "  * Sketch menu → Close sketch\n"
            "  * Part Design menu → Pad, Pocket, Create sketch, Create body\n"
            "  * View menu → Standard views → Fit All\n"
            "  * File menu → New, Save, Save As, Export\n"
            "  * Edit menu → Undo, Redo\n"
            "- The ONLY keyboard actions: Escape (cancel tool), Ctrl+Z (undo), typing in dialogs.\n"
            "- Do NOT use keyboard shortcuts for geometry tools or constraints — use menus.\n"
            "- Close sketch via Sketch menu → Close sketch (NOT by pressing Escape).\n"
            "- If you trigger a wrong tool: Escape, then Undo multiple times.\n"
            "- Draw shapes AWAY from the origin center to avoid axis selection problems\n"
            "  (EXCEPTION: circles and polygons should be centered AT the origin).\n"
            "- If a step fails 3 times, call task_complete() with what went wrong."
        )
        return "\n".join(parts)

    def _build_step_prompt(self, step: dict, params: dict,
                           step_idx: int, total_steps: int) -> str:
        """Build a prompt for a single skill step.

        Handles three formats:
        1. Rich steps (title/description/substeps) — from detailed YAML skills
        2. Sub-skill references (skill key) — delegates to another skill
        3. Simple actions (shortcut/type/key/click/wait) — direct executor calls

        NOTE: CAD_SYSTEM_INSTRUCTION is the loop's system_instruction.
        """
        parts = []

        if "title" in step:
            # Rich step from a detailed YAML skill
            parts.append(
                f"## Skill Step {step.get('step_number', step_idx + 1)}"
                f" of {total_steps}: {step['title']}"
            )
            parts.append(
                "\nYou are executing a guided skill. Follow the substeps below "
                "IN ORDER. Look at the screenshot to find the relevant UI elements "
                "and click on them. Do NOT skip substeps."
            )
            parts.append(f"\n{step.get('description', '')}")

            substeps = step.get("substeps", [])
            if substeps:
                parts.append("\n### Substeps — execute these in order:")
                for i, s in enumerate(substeps, 1):
                    parts.append(f"  {i}. {s}")

            if step.get("commands"):
                parts.append(f"\n### Relevant Commands/Keys: {step['commands']}")

            if step.get("settings"):
                parts.append(f"\n### Expected Settings: {step['settings']}")

            if step.get("gotchas"):
                parts.append(f"\n### Watch out: {step['gotchas']}")

            parts.append(
                "\nWhen you have completed ALL substeps above, stop calling "
                "functions and just say 'Step complete' so we can move to the "
                "next step."
            )

            # Resolve any {{param}} templates in the description
            resolved_text = "\n".join(parts)
            for param_name, param_value in params.items():
                resolved_text = resolved_text.replace(f"{{{{{param_name}}}}}", str(param_value))
            return resolved_text

        elif "skill" in step:
            # Sub-skill reference
            sub_params = step.get("params", {})
            resolved = self._resolve_params(sub_params, params)
            parts.append(f"\n## Current Step\nExecute: {step['skill']}")
            if resolved:
                parts.append("Parameters:")
                for k, v in resolved.items():
                    parts.append(f"  - {k}: {v}")

        else:
            # Simple direct action
            for action_type in ("shortcut", "type", "key", "click", "wait"):
                if action_type in step:
                    parts.append(f"\n## Current Step\nAction: {action_type} -> {step[action_type]}")
                    break

        return "\n".join(parts)

    def _resolve_params(self, step_params: dict, task_params: dict) -> dict:
        """Replace {{param}} placeholders with actual values from task params."""
        resolved = {}
        for key, value in step_params.items():
            if isinstance(value, str) and "{{" in value:
                # Simple template: {{length}} -> task_params["length"]
                for param_name, param_value in task_params.items():
                    value = value.replace(f"{{{{{param_name}}}}}", str(param_value))
            resolved[key] = value
        return resolved
