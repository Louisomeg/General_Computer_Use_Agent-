# =============================================================================
# CAD Agent — FreeCAD design agent
# =============================================================================
# Drives FreeCAD through an agentic loop with vision-based interaction.
#
# Usage:
#   from agents.registry import get_agent
#   from core.models import Task
#
#   agent = get_agent("cad", client=client, executor=executor)
#   task = Task(description="Create an M10x30 hex bolt", params={...})
#   result = agent.execute(task)

import subprocess

from google.genai import Client, types

from agents.registry import register
from core.agentic_loop import AgenticLoop
from core.custom_tools import get_custom_declarations
from core.executor import Executor
from core.models import Task, TaskStatus, load_tutorial_skills
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
#   - XFCE desktop navigation (taskbar, app menu)
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

## KEYBOARD SHORTCUTS (use these instead of navigating menus!)
- Rectangle:          press key_combination("g"), then press key_combination("r")
- Constrain distance: press key_combination("k"), then press key_combination("d")
- Close/Leave sketch: press key_combination("escape") when no tool is active
- Undo:               press key_combination("ctrl+z")
These are MUCH more reliable than clicking through menus.

## CORRECT MENU PATHS (from official FreeCAD docs — only when no shortcut exists)
- Create body:   "Part Design" menu -> "Create body"
- Create sketch: "Sketch" menu -> "Create sketch" (NOT Part Design menu!)
- Pad:           "Part Design" menu -> "Create an additive feature" -> "Pad"
- Pocket:        "Part Design" menu -> "Create a subtractive feature" -> "Pocket"

## How FreeCAD's Rectangle Tool Works (IMPORTANT)
USE THE SHORTCUT: press key_combination("g"), then press key_combination("r")
(This is faster and more reliable than navigating Sketch -> Sketcher geometries -> Rectangle)

The rectangle tool uses a TWO-CLICK workflow:
1. Activate via shortcut: key_combination("g"), then key_combination("r")
2. Click the FIRST corner point in the viewport
3. Click the SECOND corner point (the opposite diagonal corner)
4. The rectangle is created between those two points
5. Press key_combination("escape") to exit the rectangle tool

NEVER draw a SECOND rectangle on the same sketch. One rectangle per sketch.
If the first rectangle looks wrong, key_combination("ctrl+z") to undo and redraw.

IMPORTANT: Draw the rectangle AWAY from the center origin. Place both clicks in
the upper-left area of the viewport.

## How to Constrain a Rectangle (CRITICAL — follow this EXACTLY)
After drawing the rectangle, you MUST set BOTH width AND height. Do them one at a time:

CONSTRAIN THE WIDTH (horizontal edge):
  1. Click on a HORIZONTAL edge of the rectangle (it turns green when selected)
  2. ONLY AFTER the edge is green: press key_combination("k"), then key_combination("d")
  3. A dialog labeled "Insert length" appears with an input field
  4. Triple-click the input field to select all, then type the value WITH units (e.g. "196.0 mm")
  5. Click the OK button in the dialog (do NOT press Enter — click OK)
  6. VERIFY: A dimension annotation (number with arrows) should appear near the edge

CONSTRAIN THE HEIGHT (vertical edge):
  DO NOT close the sketch! You must also constrain the vertical edge.
  1. Click on a VERTICAL edge of the rectangle (it turns green when selected)
  2. ONLY AFTER the edge is green: press key_combination("k"), then key_combination("d")
  3. A dialog labeled "Insert length" appears
  4. Triple-click the input field, type the value WITH units (e.g. "130.0 mm")
  5. Click the OK button
  6. VERIFY: A second dimension annotation should appear near the vertical edge

CRITICAL RULES:
- Select the edge FIRST (green), THEN press K D. Never invoke constraint without selection.
- Constrain BOTH edges. Do NOT close the sketch until both dimension annotations are visible.
- After each constraint, LOOK for the dimension annotation. If missing, Ctrl+Z and retry.
- Always include " mm" after the number.

## How FreeCAD's Circle Tool Works (IMPORTANT)
The circle tool uses a TWO-CLICK workflow:
1. Activate the tool via: "Sketch" menu → "Sketcher geometries" → "Circle"
2. Click the CENTER point in the viewport (click at the origin for centered parts)
3. Move the mouse OUTWARD and click a second point to set the approximate radius
4. The circle is now created. Press key_combination("escape") to exit the tool.
Do NOT type values into the Tasks panel radius field — always use the two-click method.

AFTER the circle is drawn, set its exact size:
- Click on the CIRCLE EDGE (the curved line, NOT the center point)
- Activate constraint: "Sketch" menu → "Sketcher constraints" → "Constrain radius"
  (or "Constrain radius / diameter" — the exact menu name varies)
- A dialog appears — type the RADIUS value with units, e.g. "20 mm"
- Click OK to confirm

For TUBES (concentric circles):
1. Draw the OUTER circle (two clicks: center, then radius point). Press Escape.
2. The circle is still selected — IMMEDIATELY constrain its radius now:
   Sketch -> Sketcher constraints -> Constrain radius -> type value (e.g. "20 mm") -> OK.
3. Activate circle tool again: Sketch -> Sketcher geometries -> Circle.
4. Draw the INNER circle at the SAME center point. Press Escape.
5. The circle is still selected — IMMEDIATELY constrain its radius now.
IMPORTANT: Always constrain a circle RIGHT AFTER drawing it, while it is still
selected. Do NOT try to re-select circles by clicking in the viewport.
If you must re-select, click the element in the model tree (left panel).

## How to Create a Pocket (Cut Material Away) — IMPORTANT
Pocket removes material from a solid (like hollowing out a box):
1. First, you need an existing padded solid
2. Click on the FACE where you want to cut from (e.g., the TOP face of a box)
   - For boxes: click the LARGE FLAT TOP face (NOT a thin side face)
   - The face will highlight green/blue when selected
3. "Sketch" menu (NOT Part Design!) -> "Create sketch" — creates sketch ON selected face
4. Draw ONE rectangle: press key_combination("g"), then key_combination("r")
   - Click TWO OPPOSITE corners INSIDE the face
   - Press key_combination("escape") to exit rectangle tool
   - NEVER draw a second rectangle. If wrong, key_combination("ctrl+z") to undo.
5. Constrain BOTH edges using shortcuts:
   - Click HORIZONTAL edge (green) -> press K then D -> type inner width -> click OK
   - Click VERTICAL edge (green) -> press K then D -> type inner depth -> click OK
   - DO NOT close sketch until BOTH dimension annotations are visible.
6. Close sketch: press key_combination("escape")
7. "Part Design" menu -> "Create a subtractive feature" -> "Pocket"
8. Set the depth in the Tasks panel -> Click OK

## How to Add a Fillet (Rounded Edges) — OPTIONAL
1. Click on the edge you want to round (it highlights green)
2. "Part Design" menu -> "Fillet"
3. Set the radius in the Tasks panel
4. Click OK

## Closing the Sketch
Press key_combination("escape") when no tool is active to leave the sketch.
ALTERNATIVE: Click "Sketch" menu -> "Close sketch".

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
    """FreeCAD design agent that drives the desktop via an agentic loop."""

    def __init__(self, client: Client, executor: Executor):
        self.client = client
        self.executor = executor

        self.loop = AgenticLoop(
            client,
            system_instruction=CAD_SYSTEM_INSTRUCTION,
            max_turns=120,
            extra_declarations=[TASK_COMPLETE_DECLARATION],
            custom_declarations=get_custom_declarations(),
        )

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

    def execute(self, task: Task) -> Task:
        """Execute a CAD design task.

        Clean FreeCAD state, then run one continuous agentic loop.
        The model gets the task description + dimensions + tutorial reference
        and drives FreeCAD using its vision to complete the design.
        """
        task.status = TaskStatus.WORKING
        print(f"\n[CAD Agent] Starting task: {task.description}")
        self._prepare_freecad_environment()

        try:
            self._execute_freeform(task)
            task.complete(result="Design completed successfully")
            print(f"[CAD Agent] Task completed: {task.id}")
        except Exception as e:
            task.fail(error=str(e))
            print(f"[CAD Agent] Task failed: {e}")

        return task

    def _execute_freeform(self, task: Task):
        """Execute a task: pass the prompt + demo images to the agentic loop."""
        prompt, images = self._build_prompt(task)
        status = self.loop.agentic_loop(prompt, self.executor, images=images)
        if status in ("api_error", "empty_responses", "max_turns", "no_actions"):
            raise RuntimeError(f"Freeform execution failed with status: {status}")

    def _build_prompt(self, task: Task) -> tuple[str, list[bytes]]:
        """Build prompt text + optional demonstration images.

        The system instruction already teaches FreeCAD navigation.
        The tutorial skills provide general CAD knowledge as reference.
        The model is a vision agent — let it reason and adapt.

        Returns:
            (prompt_text, demo_images) where demo_images may be empty.
        """
        parts = [f"## Task\n{task.description}\n"]

        if task.params:
            parts.append("## Dimensions")
            for key, value in task.params.items():
                label = key.replace("_", " ").title()
                parts.append(f"- {label}: {value}")
            parts.append("")

        # Demonstration reference (visual examples from processed tutorials)
        demo_images = []
        demo_result = self._build_demo_reference(task)
        if demo_result:
            demo_text, demo_images = demo_result
            parts.append(demo_text)

        # Tutorial reference (tips, troubleshooting from YAML skills)
        reference = self._build_reference_from_tutorials()
        if reference:
            parts.append(reference)

        return "\n".join(parts), demo_images

    def _build_demo_reference(self, task: Task) -> tuple[str, list[bytes]] | None:
        """Find and format a relevant demonstration for the task.

        Returns (text_description, [screenshot_bytes]) or None.
        """
        from core.skill_retrieval import find_relevant_demo, get_demo_screenshots, format_demo_text

        demo = find_relevant_demo(task.description, task.params)
        if not demo:
            return None

        images = get_demo_screenshots(demo, max_screenshots=3)
        if not images:
            return None

        text = format_demo_text(demo)
        print(f"[CAD Agent] Loaded demonstration: {demo.get('name')} "
              f"({len(images)} screenshots)")
        return text, images

    def _build_reference_from_tutorials(self) -> str:
        """Build a compact FreeCAD reference section from tutorial-type skills.

        Only extracts tips and troubleshooting — NOT full workflow steps.
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
                parts.append(f"- {item.get('problem', '')} -> {item.get('solution', '')}")
            parts.append("")

        reference = "\n".join(parts)
        print(f"[CAD Agent] Loaded tutorial reference ({len(reference)} chars)")
        return reference
