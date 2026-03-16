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


# The CAD agent uses ONLY the base SYSTEM_INSTRUCTION from settings.py.
# All CAD-specific instructions come from the planner's action plan (generated
# by Gemini 3.1 Pro) which is passed as the user prompt.  Having a single
# source of truth avoids conflicting instructions that confused the agent.

# Stage budgets for turn tracking — prevents the agent from burning
# all 120 turns on one step (like trying to click a single button).
CAD_STAGE_BUDGETS = [
    {"name": "setup", "budget": 10,
     "description": "Open FreeCAD, create body, enter first sketch"},
    {"name": "base_shape", "budget": 25,
     "description": "Draw base profile, constrain dimensions, close sketch, Pad"},
    {"name": "features", "budget": 50,
     "description": "Add holes, pockets, fillets, chamfers, additional sketches"},
    {"name": "cleanup", "budget": 10,
     "description": "Fit view, verify result, save if needed"},
    {"name": "reserve", "budget": 25,
     "description": "Recovery budget for undo/retry operations"},
]


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
            system_instruction=SYSTEM_INSTRUCTION,
            max_turns=120,
            extra_declarations=[TASK_COMPLETE_DECLARATION],
            custom_declarations=get_custom_declarations(),
            stage_budgets=CAD_STAGE_BUDGETS,
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

        # NOTE: Demo references and tutorial skills are DISABLED to avoid
        # prompt interference.  The detailed action plan from the planner
        # already contains all the FreeCAD knowledge the agent needs.
        # Re-enable these once we confirm the base workflow works.
        #
        # # Demonstration reference (visual examples from processed tutorials)
        # demo_images = []
        # demo_result = self._build_demo_reference(task)
        # if demo_result:
        #     demo_text, demo_images = demo_result
        #     parts.append(demo_text)
        #
        # # Tutorial reference (tips, troubleshooting from YAML skills)
        # reference = self._build_reference_from_tutorials()
        # if reference:
        #     parts.append(reference)

        return "\n".join(parts), []

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
