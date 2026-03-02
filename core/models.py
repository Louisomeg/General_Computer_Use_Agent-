# =============================================================================
# Core Models — Task, ProcedureState, Skill Loader
# =============================================================================
# Single file for all shared data structures. Import from anywhere:
#   from core.models import Task, TaskStatus, ProcedureState, load_skill

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml


# ── Task Status ──────────────────────────────────────────────────────────────

class TaskStatus(Enum):
    PENDING = "pending"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    INPUT_REQUIRED = "input_required"


# ── Task ─────────────────────────────────────────────────────────────────────
# What the planner sends to an agent.

@dataclass
class Task:
    description: str
    params: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    artifacts: list = field(default_factory=list)
    error: str = ""

    def complete(self, result: str = "", artifacts: list = None):
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.artifacts = artifacts or self.artifacts

    def fail(self, error: str):
        self.status = TaskStatus.FAILED
        self.error = error


# ── Procedure State ──────────────────────────────────────────────────────────
# Tracks where the agent is in a multi-step skill.

@dataclass
class ProcedureState:
    skill_name: str
    total_steps: int
    current_step: int = 0
    completed: list = field(default_factory=list)
    failed: list = field(default_factory=list)

    def advance(self):
        self.completed.append(self.current_step)
        self.current_step += 1

    def fail_current(self, reason: str = ""):
        self.failed.append((self.current_step, reason))

    @property
    def done(self):
        return self.current_step >= self.total_steps

    @property
    def progress(self):
        return f"Step {self.current_step + 1}/{self.total_steps}"


# ── Skill Loader ─────────────────────────────────────────────────────────────
# Reads YAML skill files from the skills/freecad/ directory.

SKILLS_DIR = Path(__file__).parent.parent / "skills" / "freecad"


def load_skill(name: str) -> dict | None:
    """Load a YAML skill by name. Returns None if not found."""
    # Check flat directory first
    path = SKILLS_DIR / f"{name}.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f)

    # Check subdirectories
    for sub in SKILLS_DIR.iterdir():
        if sub.is_dir():
            path = sub / f"{name}.yaml"
            if path.exists():
                with open(path) as f:
                    return yaml.safe_load(f)

    return None


def list_skills() -> list[str]:
    """List all available skill names."""
    if not SKILLS_DIR.exists():
        return []
    return [p.stem for p in SKILLS_DIR.rglob("*.yaml")]


def load_tutorial_skills() -> list[dict]:
    """Load all skills marked with type: tutorial.

    Tutorial skills contain general workflow knowledge (tips, troubleshooting,
    step-by-step procedures) that applies to ANY FreeCAD task, not just the
    specific part they demonstrate.  The CAD agent injects this knowledge
    as reference material into every task prompt.
    """
    tutorials = []
    if not SKILLS_DIR.exists():
        return tutorials
    for path in SKILLS_DIR.rglob("*.yaml"):
        with open(path) as f:
            skill = yaml.safe_load(f)
            if skill and skill.get("type") == "tutorial":
                tutorials.append(skill)
    return tutorials
