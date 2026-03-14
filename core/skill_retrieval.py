# =============================================================================
# Skill Retrieval — find the most relevant demonstration for a task
# =============================================================================
# Simple keyword-based matching. Tokenizes task description, matches against
# demo tags + description, returns the best match.
#
# Usage:
#   from core.skill_retrieval import find_relevant_demo, get_demo_screenshots
#   demo = find_relevant_demo("Create a cylinder with 10mm radius")
#   images = get_demo_screenshots(demo, max_screenshots=3)

import re
from pathlib import Path

from core.models import load_demonstration_index, load_demonstration_skill


# Common words to ignore during matching
_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with",
    "and", "or", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "it", "its", "this",
    "that", "these", "those", "i", "you", "we", "they", "he", "she",
    "create", "make", "build", "design", "model",  # Too generic for CAD
    "mm", "cm", "m", "using", "use", "from",
}


def find_relevant_demo(
    task_description: str,
    task_params: dict = None,
    min_matches: int = 2,
) -> dict | None:
    """Find the most relevant demonstration skill for a task.

    Args:
        task_description: The task description text.
        task_params: Optional task parameters (dimensions, etc.).
        min_matches: Minimum keyword matches required.

    Returns:
        The demonstration skill dict (with '_dir' key), or None.
    """
    index = load_demonstration_index()
    if not index:
        return None

    # Tokenize task
    task_words = _tokenize(task_description)
    if task_params:
        for key in task_params:
            task_words.update(_tokenize(key))

    # Score each demo
    best_score = 0
    best_name = None

    for entry in index:
        score = _score_match(task_words, entry)
        if score > best_score:
            best_score = score
            best_name = entry["name"]

    if best_score < min_matches:
        return None

    demo = load_demonstration_skill(best_name)
    if demo:
        print(f"[retrieval] Matched demo: {best_name} (score={best_score})")
    return demo


def get_demo_screenshots(demo: dict, max_screenshots: int = 3) -> list[bytes]:
    """Load key screenshots from a demonstration skill.

    Strategy: pick evenly-spaced steps for a representative overview.
    - If demo has <= max_screenshots steps, return all.
    - Otherwise, return first, middle, and last step screenshots.

    Args:
        demo: Demonstration skill dict (must have '_dir' key).
        max_screenshots: Maximum screenshots to return.

    Returns:
        List of PNG bytes. May be shorter than max_screenshots if
        some PNGs are missing.
    """
    demo_dir = Path(demo.get("_dir", ""))
    steps = demo.get("steps", [])
    if not steps or not demo_dir.exists():
        return []

    # Select which steps to include
    if len(steps) <= max_screenshots:
        selected = steps
    else:
        # Evenly spaced: first, middle, last
        indices = [0, len(steps) // 2, len(steps) - 1]
        selected = [steps[i] for i in indices]

    # Load PNGs
    images = []
    for step in selected:
        png_path = demo_dir / step.get("screenshot", "")
        if png_path.exists():
            images.append(png_path.read_bytes())

    return images


def format_demo_text(demo: dict, selected_indices: list[int] = None) -> str:
    """Format a demonstration as text context for the prompt.

    Produces a compact summary referencing the demonstration screenshots
    that were injected as images.

    Args:
        demo: Demonstration skill dict.
        selected_indices: Which step indices have screenshots included.
                         If None, uses first/middle/last.

    Returns:
        Formatted text section for the prompt.
    """
    name = demo.get("name", "unknown")
    description = demo.get("description", "")
    steps = demo.get("steps", [])

    if not steps:
        return ""

    # Determine which steps have screenshots
    if selected_indices is None:
        if len(steps) <= 3:
            selected_indices = list(range(len(steps)))
        else:
            selected_indices = [0, len(steps) // 2, len(steps) - 1]

    parts = [
        "\n## Visual Demonstration Reference",
        f"The following screenshots show a similar task: **{name}**",
        f"{description}\n",
        "IMPORTANT: These are REFERENCE screenshots from a tutorial video.",
        "Your current screen will look different. Use the demonstration as a",
        "GUIDE for the workflow order, but always click based on what you see",
        "in YOUR current screenshot.\n",
        "Key steps shown in reference screenshots:",
    ]

    screenshot_num = 1
    for i, step in enumerate(steps):
        if i in selected_indices:
            parts.append(
                f"{screenshot_num}. [Reference Screenshot {screenshot_num}] "
                f"{step.get('thought', step.get('narration', ''))}"
            )
            action = step.get("action", {})
            if action.get("menu_path"):
                parts.append(f"   Menu: {action['menu_path']}")
            elif action.get("target"):
                parts.append(f"   Target: {action['target']}")
            if step.get("verify"):
                parts.append(f"   Verify: {step['verify']}")
            screenshot_num += 1

    parts.append("")
    return "\n".join(parts)


def _tokenize(text: str) -> set[str]:
    """Simple word tokenization + normalization."""
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _score_match(task_words: set[str], demo_entry: dict) -> int:
    """Score how well a demo matches task keywords."""
    demo_words = _tokenize(demo_entry.get("description", ""))
    for tag in demo_entry.get("tags", []):
        demo_words.update(_tokenize(tag))
    # Also match the demo name
    demo_words.update(_tokenize(demo_entry.get("name", "")))

    return len(task_words & demo_words)
