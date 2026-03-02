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

## CAD Design Workflow
After minimizing the terminal, follow these steps:
1. Look at the screenshot — is FreeCAD already open?
   If YES: click on its window in the taskbar to bring it to focus.
   If NO: use open_application("FreeCAD"), then wait_5_seconds.
2. Create a new document: use freecad_shortcut("file_new"), then wait_5_seconds.
   Verify a new "Unnamed" document appears in the model tree.
3. Switch to Part Design workbench — look at the workbench dropdown (usually top-center
   toolbar area) and click it, then select "Part Design" from the list.
4. Create a Part Design Body — open the "Part Design" menu in the menu bar, then
   click "Create body" (usually the first item). You should see "Body" and "Origin"
   appear in the model tree (left panel).
5. Work through the design step by step — create sketches, add constraints,
   pad/pocket features, fillets, chamfers as needed.
6. After each major operation, check the viewport to verify the result.
7. When finished, call task_complete(summary="description of what was built").

## Completion
When you have finished the design, call task_complete() with a summary of what you built.
If you encounter repeated errors (3+ failures on the same action), call task_complete()
describing what went wrong and what was accomplished so far.
Do NOT keep performing actions after the main task is done.

## Key FreeCAD Rules
- Always create a Body before any Part Design operations.
- Close a sketch before padding or pocketing it.
- When sketching, add constraints to fully define the geometry.
- For Pad, Pocket, Fillet, Chamfer — find them in the Part Design menu or toolbar
  by looking at the screenshot and clicking. Only use shortcuts if no button is visible.
- For sketcher geometry (line, rectangle, circle) — use freecad_shortcut
  (e.g. sketcher_line, sketcher_rectangle, sketcher_circle) since these are
  two-key sequences that are faster than finding toolbar buttons.

## Rectangle Auto-Constraints — IMPORTANT
When you draw a rectangle with sketcher_rectangle, FreeCAD automatically adds
positional constraints (fixing the corner coordinates). These will appear in the
Constraints list but are NORMAL — do NOT try to delete them.
Instead, just add your dimensional constraints on top:
1. Select a horizontal edge → freecad_shortcut("sketcher_constrain_distance") → type the width
2. Select a vertical edge → freecad_shortcut("sketcher_constrain_distance") → type the height
The auto-constraints will turn green once the sketch is fully constrained.
If constraints turn red (over-constrained), use freecad_shortcut("edit_undo") to undo
your last constraint and try a different approach. Do NOT try to delete individual
constraints by selecting them and pressing Delete — that rarely works in FreeCAD's UI.

## When Working with Measurements
- All dimensions should match what was specified in the task.
- Use constraint tools: freecad_shortcut("sketcher_constrain_distance") for distance (K+D),
  freecad_shortcut("sketcher_constrain_radius") for radius (K+R).
- When a dimension dialog appears, look at the input field in the screenshot,
  click on it, type the NUMERIC VALUE ONLY (e.g. "30" not "30mm"), then press Enter.

## Error Recovery — CRITICAL RULES
- NEVER create a new document to start over. Work with the current document.
- If you made a mistake, use freecad_shortcut("edit_undo") (Ctrl+Z) to undo it.
- If an action fails, LOOK at the screenshot again and try a different approach.
- If a dialog or popup appears unexpectedly, close it with Escape or click its X button.
- If you accidentally leave a sketch, double-click "Sketch" in the model tree to re-enter.
- If something isn't working after 3 attempts, call task_complete() with a status report.
- Do NOT blindly repeat the same failed action — always re-examine the screenshot.
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
            max_turns=50,
            extra_declarations=[TASK_COMPLETE_DECLARATION],
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
        """Build a FreeCAD reference section from all tutorial-type skills.

        Tutorial skills contain general FreeCAD workflow knowledge (tips,
        troubleshooting, step-by-step procedures) that is valuable for ANY
        modeling task.  We extract the most useful parts and format them as
        a compact reference section that gets injected into the task prompt.

        For workflow steps we include:
          - Steps 1-4 in full (setup, sketch, variables, pad) — universal
          - Steps 5+ as one-line summaries (task-specific advanced ops)
        """
        tutorials = load_tutorial_skills()
        if not tutorials:
            return ""

        parts = [
            "\n## FreeCAD Reference Guide",
            "(Extracted from tutorial skills — use this knowledge to guide your work)\n",
        ]

        for skill in tutorials:
            # ── Tips ──────────────────────────────────────────────────
            tips = skill.get("tips", [])
            if tips:
                parts.append("### General Tips")
                for tip in tips:
                    parts.append(f"- {tip}")
                parts.append("")

            # ── Troubleshooting ───────────────────────────────────────
            troubleshooting = skill.get("troubleshooting", [])
            if troubleshooting:
                parts.append("### Common Problems & Solutions")
                for item in troubleshooting:
                    parts.append(f"- Problem: {item.get('problem', '')}")
                    parts.append(f"  Solution: {item.get('solution', '')}")
                parts.append("")

            # ── Workflow steps ────────────────────────────────────────
            steps = skill.get("steps", [])
            if steps:
                parts.append("### FreeCAD Workflow Reference")
                parts.append(
                    "These steps show the standard FreeCAD modeling workflow. "
                    "Adapt the techniques to YOUR current task (ignore specific "
                    "dimensions from the tutorial — use the task specs instead).\n"
                )

                for step in steps:
                    step_num = step.get("step_number", "?")
                    title = step.get("title", f"Step {step_num}")

                    # Steps 1-4: full detail (universal workflow)
                    if isinstance(step_num, int) and step_num <= 4:
                        parts.append(f"**Step {step_num}: {title}**")
                        for substep in step.get("substeps", []):
                            parts.append(f"  - {substep}")
                        if step.get("commands"):
                            parts.append(f"  Commands: {step['commands']}")
                        if step.get("gotchas"):
                            parts.append(f"  Watch out: {step['gotchas']}")
                        parts.append("")
                    else:
                        # Steps 5+: one-line summary (advanced/specific ops)
                        desc = step.get("description", "").strip()
                        # Take just the first sentence
                        first_sentence = desc.split(".")[0] + "." if desc else ""
                        parts.append(f"**Step {step_num}: {title}** — {first_sentence}")
                        if step.get("gotchas"):
                            parts.append(f"  Watch out: {step['gotchas']}")

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
            "Follow the CAD Design Workflow from your system instructions:\n"
            "1. Minimize the terminal: system_shortcut(\"minimize_window\")\n"
            "2. Check if FreeCAD is open. If not, use open_application(\"FreeCAD\"), then wait_5_seconds.\n"
            "3. Look at the model tree (left panel). If an empty document already exists\n"
            "   (like \"Unnamed\"), USE IT. Only use freecad_shortcut(\"file_new\") if\n"
            "   there is no existing empty document.\n"
            "4. Create a Body: click the Part Design menu in the menu bar, then click\n"
            "   \"Create body\". If the sketcher dialog asks \"A body is needed\", click Yes.\n"
            "5. Create a new sketch on the XY plane:\n"
            "   - Look for a \"New Sketch\" button in the toolbar or Part Design menu\n"
            "   - When the plane selector appears, select \"XY_Plane\" and click OK\n"
            "6. Draw the 2D profile using sketcher tools (freecad_shortcut)\n"
            "   - For a cube/box: use freecad_shortcut(\"sketcher_rectangle\")\n"
            "   - Click two points in the viewport to draw the rectangle\n"
            "   - FreeCAD will auto-add positional constraints — this is NORMAL, do not delete them\n"
            "7. Add dimension constraints:\n"
            "   - Click on a horizontal edge of the rectangle to select it\n"
            "   - Use freecad_shortcut(\"sketcher_constrain_distance\")\n"
            "   - Type the numeric value (e.g. \"30\") in the dialog and press Enter\n"
            "   - Repeat for a vertical edge\n"
            "8. Close the sketch: freecad_shortcut(\"sketcher_close\")\n"
            "9. Pad the sketch: look in the Part Design menu or toolbar for \"Pad\".\n"
            "   Click it, set the length in the dialog, and click OK.\n"
            "10. Call task_complete() with a summary of what was built\n\n"
            "CRITICAL RULES:\n"
            "- NEVER create a new document to start over. Use freecad_shortcut(\"edit_undo\") if you make a mistake.\n"
            "- Do NOT try to delete auto-constraints from the rectangle. Just add dimensional constraints on top.\n"
            "- If a key_combination fails, try using the equivalent freecad_shortcut instead."
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
