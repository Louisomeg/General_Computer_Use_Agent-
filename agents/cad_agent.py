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


# ---------------------------------------------------------------------------
# Shortcut filters — only include shortcuts the CAD agent actually needs.
# This reduces per-turn tool description overhead from ~10,000 chars to ~2,400.
# Shortcuts not listed here still WORK (the executor has them all), the model
# just won't see them in the function description and won't call them.
# ---------------------------------------------------------------------------

CAD_UBUNTU_SHORTCUTS = {
    "minimize_window", "close_window", "maximize_window",
    "snap_window_left", "snap_window_right",
    "switch_window_forward",
    "copy", "paste", "cut", "select_all", "undo", "redo",
    "save", "save_as",
    "open_terminal",
}

CAD_FREECAD_SHORTCUTS = {
    # File / Edit
    "file_new", "file_save", "file_save_as", "file_export",
    "edit_undo", "edit_redo", "cancel_operation", "toggle_visibility",
    # View
    "view_isometric", "view_front", "view_top", "view_right",
    "view_fit_all", "view_fit_selection",
    "view_orthographic", "view_perspective",
    # Part Design
    "partdesign_pad", "partdesign_pocket",
    # Sketcher Geometry
    "sketcher_line", "sketcher_rectangle", "sketcher_circle",
    "sketcher_arc", "sketcher_polyline", "sketcher_trim",
    "sketcher_external_geometry", "sketcher_construction_mode",
    # Sketcher Constraints
    "sketcher_constrain_horizontal", "sketcher_constrain_vertical",
    "sketcher_constrain_coincident", "sketcher_constrain_equal",
    "sketcher_constrain_perpendicular", "sketcher_constrain_symmetric",
    "sketcher_constrain_distance", "sketcher_constrain_radius",
    "sketcher_constrain_angle",
    "sketcher_close",
}


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
#   - coordinate system (0-999 normalized)
#   - visual-first navigation (look at screenshot, click visible elements)
#   - GNOME desktop navigation (Activities, taskbar, app grid)
#   - 5-step application launch procedure
#   - when to use shortcuts vs GUI clicks
#   - FreeCAD basics (menus, toolbars, panels)
#
# This addendum adds CAD-specific workflow on top of that foundation.
# ---------------------------------------------------------------------------

CAD_ADDENDUM = """

## CRITICAL: Terminal Window
When you start, you will see a terminal window on screen running the agent script.
IMMEDIATELY minimize it with system_shortcut("minimize_window") as your FIRST action.
Do NOT try to close, read, or interact with the terminal — just minimize it and move on.
After minimizing, focus EXCLUSIVELY on FreeCAD for the rest of the task.

## Using Keyboard Shortcuts Instead of Clicking
FreeCAD toolbar icons are TINY (~24px) and packed tightly together.
Clicking the wrong icon causes catastrophic operations that are hard to recover from.

RULES:
- Use freecad_shortcut("partdesign_pad") (key P) instead of clicking Pad toolbar icon
- Use freecad_shortcut("partdesign_pocket") (key Q) instead of clicking Pocket icon
- Use freecad_shortcut("sketcher_rectangle") (G+R) for rectangle, etc.
- Use freecad_shortcut("sketcher_constrain_distance") (K+D) to add a distance constraint
- The ONLY safe clicks are large buttons like "OK" / "Close" in the Tasks panel (left side),
  and items in the model tree (left panel).
- For operations with no shortcut (Fillet, Chamfer, New Sketch), use the MENU BAR.
  Click the menu TEXT (e.g. "Part Design" text), then click the dropdown item.

## How FreeCAD's Rectangle Tool Works (IMPORTANT)
The rectangle tool uses a TWO-CLICK workflow:
1. freecad_shortcut("sketcher_rectangle") — activates the tool
2. Click the FIRST corner point in the viewport
3. Click the SECOND corner point (the opposite diagonal corner)
4. The rectangle is now created between those two points
5. Press Escape to exit the rectangle tool

AFTER the rectangle is drawn, add dimension constraints:
- Click on one HORIZONTAL edge of the rectangle (click at the midpoint of the line)
- Use freecad_shortcut("sketcher_constrain_distance") (K then D)
- A dialog appears with a number field — type the dimension value, press Enter
- Repeat for one VERTICAL edge

IMPORTANT: Draw the rectangle AWAY from the center origin (avoid the area where
the red X-axis and green Y-axis lines cross). Place both clicks in the upper-left
area of the viewport so edges don't overlap with axis lines.

## Error Recovery — CRITICAL RULES
- NEVER use the Delete key. It permanently removes the WRONG thing.
- ALWAYS use freecad_shortcut("edit_undo") (Ctrl+Z) to fix mistakes. Press MULTIPLE TIMES.
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

        # Build filtered tool declarations — only shortcuts the CAD agent needs.
        # Reduces per-turn overhead from ~10,000 chars to ~2,400 chars.
        cad_declarations = get_custom_declarations(
            ubuntu_filter=CAD_UBUNTU_SHORTCUTS,
            freecad_filter=CAD_FREECAD_SHORTCUTS,
        )

        self.loop = AgenticLoop(
            client,
            system_instruction=CAD_SYSTEM_INSTRUCTION,   # base + CAD addendum
            max_turns=25,
            extra_declarations=[TASK_COMPLETE_DECLARATION],
            custom_declarations=cad_declarations,
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

            "1. Minimize the terminal: system_shortcut(\"minimize_window\")\n\n"

            "2. Check if FreeCAD is open.\n"
            "   If YES: click on its window in the taskbar to bring it to focus.\n"
            "   If NO: use open_application(\"FreeCAD\"), then wait_5_seconds.\n\n"

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
            "   Then: click the \"Part Design\" text in the MENU BAR, then click \"New Sketch\".\n"
            "   When the plane selector dialog appears, click \"XY_Plane\" then click OK.\n"
            "   Verify: you should see the sketcher grid with red/green axis lines.\n"
            "   Then: freecad_shortcut(\"view_fit_all\") to zoom the view properly.\n\n"

            "6. Draw the rectangle (TWO clicks, then add constraints):\n"
            "   a. freecad_shortcut(\"sketcher_rectangle\") to activate the rectangle tool.\n"
            "   b. Click the FIRST corner in the upper-left area of the viewport (around x=250, y=300).\n"
            "      IMPORTANT: stay AWAY from the center where the red and green axis lines cross.\n"
            "   c. Click the SECOND corner, offset down-right from the first (around x=450, y=500).\n"
            "      This creates an approximate rectangle. Exact size does not matter yet.\n"
            "   d. Press key_combination(\"escape\") to exit the rectangle tool.\n"
            "   e. Now add a WIDTH constraint: click on one HORIZONTAL edge of the rectangle\n"
            "      (click at the midpoint of the line, not near a corner).\n"
            "      Then: freecad_shortcut(\"sketcher_constrain_distance\") (K then D).\n"
            "      A dimension dialog appears — type the width value (e.g. \"30\"), press Enter.\n"
            "   f. Add a HEIGHT constraint: click on one VERTICAL edge of the rectangle.\n"
            "      Then: freecad_shortcut(\"sketcher_constrain_distance\") again.\n"
            "      Type the height value (e.g. \"30\"), press Enter.\n"
            "   Verify: the rectangle should resize to the exact dimensions.\n\n"

            "7. Close the sketch: freecad_shortcut(\"sketcher_close\")\n"
            "   Verify: you should see the rectangle outline in the 3D viewport.\n\n"

            "8. Pad (extrude) the sketch:\n"
            "   Use freecad_shortcut(\"partdesign_pad\") (key P) to start the pad operation.\n"
            "   A dialog will appear with a Length input field.\n"
            "   Click the Length field, clear it, type the depth value (e.g. \"30\").\n"
            "   Click OK to apply the pad.\n"
            "   Then: freecad_shortcut(\"view_fit_all\") to see the full 3D solid.\n"
            "   Verify: you should see a 3D solid in the viewport.\n\n"

            "9. Call task_complete() with a summary of what was built.\n\n"

            "CRITICAL RULES:\n"
            "- NEVER use the Delete key. Use freecad_shortcut(\"edit_undo\") to fix mistakes.\n"
            "- Use KEYBOARD SHORTCUTS for Pad (P), Pocket (Q), sketcher tools (G+R, G+L, etc.)\n"
            "- Use the MENU BAR only for operations that have no shortcut (New Sketch, Fillet, etc.)\n"
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
