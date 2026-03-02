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
from core.models import Task, TaskStatus, ProcedureState, load_skill
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
2. Create a new document if needed — look for File menu in the menu bar, click it,
   then click "New". Or use the Start page "Create New..." button if visible.
3. Switch to Part Design workbench — look at the workbench dropdown (usually top-center
   toolbar area) and click it, then select "Part Design" from the list.
4. Create a Part Design Body — look in the Part Design menu or toolbar for "Create Body"
   and click it. You should see "Body" and "Origin" appear in the model tree (left panel).
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

## When Working with Measurements
- All dimensions should match what was specified in the task.
- Use constraint tools (K+D for distance, K+R for radius) to set exact values.
- When a dimension dialog appears, look at the input field in the screenshot,
  click on it, type the value, then click OK or press Enter.

## Error Recovery
- If an action fails, LOOK at the screenshot again and try a different approach.
- If something isn't working after 3 attempts, move on to the next step or stop.
- Do NOT blindly repeat the same failed action — always re-examine the screenshot.
- If a dialog or popup appears unexpectedly, close it with Escape or click its X button.
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
        """Execute a task with no matching skill — pure prompt-driven."""
        prompt = self._build_prompt(task)
        print(f"[CAD Agent] No skill found, running freeform design")
        self.loop.agentic_loop(prompt, self.executor)

    def _build_prompt(self, task: Task) -> str:
        """Build a task prompt for the agentic loop (freeform mode).

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

        parts.append(
            "Begin working on this task now. Follow the CAD Design Workflow:\n"
            "1. First minimize the terminal with system_shortcut(\"minimize_window\")\n"
            "2. Then check the screenshot — is FreeCAD open?\n"
            "3. Proceed through the design steps visually.\n"
            "4. When done, call task_complete() with a summary."
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
