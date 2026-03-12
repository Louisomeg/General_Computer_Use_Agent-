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
            max_turns=25,
            extra_declarations=[TASK_COMPLETE_DECLARATION],
            custom_declarations=get_custom_declarations(),
        )
        self.state = None  # active ProcedureState, if running a skill

    @property
    def card(self) -> dict:
        return AGENT_CARD

    def execute(self, task: Task) -> Task:
        """Execute a CAD design task.

        The agent will:
        1. Check if a YAML skill exists for the task
        2. If yes — decompose using the skill steps
        3. If no — build a detailed prompt and let the agentic loop handle it
        """
        task.status = TaskStatus.WORKING
        print(f"\n[CAD Agent] Starting task: {task.description}")

        try:
            # Check for a matching skill file
            skill = self._find_skill(task)

            if skill:
                self._execute_skill(task, skill)
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

        Includes:
        1. Task description and specifications
        2. Tutorial reference material (tips, troubleshooting, workflow)
        3. Step-by-step execution plan
        4. Critical rules

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
            "      IMPORTANT — UNIT HANDLING: Always type the number WITH the unit, e.g.\n"
            "      type \"30 mm\" (with the space before mm), NOT just \"30\".\n"
            "      FreeCAD may display a different default unit (like µm), so always\n"
            "      include \" mm\" after the number to ensure millimeters.\n"
            "      After typing, click the \"OK\" button in the dialog (do NOT press Enter).\n"
            "   f. Add a HEIGHT constraint:\n"
            "      Click on one VERTICAL edge of the rectangle.\n"
            "      Then activate the distance constraint via the MENU again:\n"
            "      Click \"Sketch\" → hover \"Sketcher constraints\" → click \"Constrain distance\".\n"
            "      Type the height value with unit (e.g. \"30 mm\"), then click OK.\n"
            "   Verify: the rectangle should resize to the exact dimensions.\n\n"

            "7. Close the sketch:\n"
            "   Do NOT press Escape to close the sketch — Escape only cancels the active tool.\n"
            "   Instead: click the \"Sketch\" text in the MENU BAR, then click \"Close sketch\".\n"
            "   ALTERNATIVE: click the \"Close\" button in the Tasks panel (left side).\n"
            "   Verify: the menu bar should now show \"Part Design\" menus (not \"Sketch\" menus).\n"
            "   You should see the rectangle outline in the 3D viewport.\n\n"

            "8. Pad (extrude) the sketch:\n"
            "   Click \"Part Design\" in the MENU BAR at the top, then click \"Pad\" in the dropdown.\n"
            "   A dialog will appear in the Tasks panel (left side) with a Length input field.\n"
            "   Click the Length field, clear it, type the depth value WITH unit (e.g. \"30 mm\").\n"
            "   Click OK to apply the pad.\n"
            "   Then zoom to fit: click \"View\" in the MENU BAR → click \"Standard views\" →\n"
            "   click \"Fit All\" to see the full 3D solid.\n"
            "   Verify: you should see a 3D solid in the viewport.\n\n"

            "9. Call task_complete() with a summary of what was built.\n\n"

            "CRITICAL RULES:\n"
            "- NEVER use the Delete key. Use Edit menu → Undo or key_combination(\"ctrl+z\").\n"
            "- Use the MENU BAR for ALL FreeCAD operations:\n"
            "  * Sketch menu → Sketcher geometries (for Rectangle, Line, Circle, etc.)\n"
            "  * Sketch menu → Sketcher constraints (for Constrain distance, etc.)\n"
            "  * Sketch menu → Close sketch\n"
            "  * Part Design menu → Pad, Pocket, Create sketch, Create body\n"
            "  * View menu → Standard views → Fit All\n"
            "  * File menu → New, Save, Save As, Export\n"
            "  * Edit menu → Undo, Redo\n"
            "- The ONLY keyboard actions: Escape (cancel tool), Ctrl+Z (undo), typing in dialogs.\n"
            "- Do NOT use keyboard shortcuts for geometry tools or constraints — use menus.\n"
            "- Close sketch via Sketch menu → Close sketch (NOT by pressing Escape).\n"
            "- If you trigger a wrong tool: Escape, then Undo multiple times.\n"
            "- Draw shapes AWAY from the origin center to avoid axis selection problems.\n"
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
