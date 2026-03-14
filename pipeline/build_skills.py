# =============================================================================
# Build Skills — assemble filtered actions into demonstration YAML + PNGs
# =============================================================================
# Takes labeled, quality-filtered actions and packages them as demonstration
# skills that the agent can use at runtime.
#
# Usage:
#   from pipeline.build_skills import build_skill, update_index
#   skill_path = build_skill(video_id, title, filtered_actions, keyframe_dir)
#   update_index()

import re
import shutil
from pathlib import Path

import yaml


DEMOS_DIR = Path(__file__).parent.parent / "skills" / "freecad" / "demos"


def build_skill(
    video_id: str,
    title: str,
    labeled_actions: list[dict],
    output_dir: Path = None,
) -> Path:
    """Assemble a demonstration skill from labeled actions.

    1. Create output directory: skills/freecad/demos/{skill_name}/
    2. Copy keyframe PNGs as step_001.png, step_002.png, ...
    3. Write skill.yaml with metadata + steps

    Args:
        video_id: YouTube video ID.
        title: Video title.
        labeled_actions: Filtered actions from filter_quality.
        output_dir: Override output location (default: DEMOS_DIR/{skill_name}/).

    Returns:
        Path to the created skill.yaml file.
    """
    if not labeled_actions:
        raise ValueError("No actions to build skill from")

    skill_name = _snake_case(title)
    skill_dir = output_dir or (DEMOS_DIR / skill_name)
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing skill with same video_id
    skill_path = skill_dir / "skill.yaml"
    if skill_path.exists():
        with open(skill_path) as f:
            existing = yaml.safe_load(f)
        if existing and existing.get("source", {}).get("video_id") == video_id:
            print(f"[build] Skill already exists for video {video_id}, skipping")
            return skill_path

    # Copy keyframe PNGs as step_NNN.png
    steps = []
    for i, action in enumerate(labeled_actions):
        step_num = i + 1
        png_name = f"step_{step_num:03d}.png"

        # Copy the "after" frame (shows the result of the action)
        after_path = Path(action.get("after_frame", ""))
        if after_path.exists():
            shutil.copy2(after_path, skill_dir / png_name)
        elif Path(action.get("before_frame", "")).exists():
            # Fallback to "before" if "after" is missing
            shutil.copy2(action["before_frame"], skill_dir / png_name)

        steps.append({
            "index": step_num,
            "screenshot": png_name,
            "narration": _get_narration(action),
            "thought": action.get("thought", ""),
            "action": _normalize_action(action.get("action", {})),
            "verify": action.get("verify", ""),
        })

    # Extract tags from actions
    tags = _generate_tags(labeled_actions)

    # Build description from first/last action thoughts
    description = _generate_description(title, labeled_actions)

    # Build tips and troubleshooting from action patterns
    tips = _extract_tips(labeled_actions)

    # Write skill.yaml
    skill_data = {
        "name": skill_name,
        "type": "demonstration",
        "source": {
            "video_id": video_id,
            "title": title,
        },
        "description": description,
        "tags": tags,
        "steps": steps,
    }
    if tips:
        skill_data["tips"] = tips

    with open(skill_path, "w", encoding="utf-8") as f:
        yaml.dump(skill_data, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False, width=120)

    print(f"[build] Created skill: {skill_name} ({len(steps)} steps, {len(tags)} tags)")
    return skill_path


def update_index(demos_dir: Path = None):
    """Rebuild the demonstration index from all skill.yaml files.

    The index is a flat YAML listing all available demonstrations with
    their descriptions and tags — used by the retrieval system.
    """
    demos_dir = demos_dir or DEMOS_DIR
    if not demos_dir.exists():
        print("[build] No demos directory found")
        return

    index_entries = []
    for skill_dir in sorted(demos_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "skill.yaml"
        if not skill_path.exists():
            continue

        with open(skill_path, encoding="utf-8") as f:
            skill = yaml.safe_load(f)

        if not skill:
            continue

        index_entries.append({
            "name": skill.get("name", skill_dir.name),
            "description": skill.get("description", ""),
            "tags": skill.get("tags", []),
            "path": str(skill_path.relative_to(demos_dir)),
            "step_count": len(skill.get("steps", [])),
            "source_title": skill.get("source", {}).get("title", ""),
        })

    index_path = demos_dir / "index.yaml"
    with open(index_path, "w", encoding="utf-8") as f:
        yaml.dump({"skills": index_entries}, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False, width=120)

    print(f"[build] Updated index: {len(index_entries)} demonstrations")


def _snake_case(title: str) -> str:
    """Convert a video title to a snake_case skill name."""
    # Remove common prefixes/suffixes
    clean = title.lower()
    for prefix in ("freecad 1.0 -", "freecad -", "freecad 1.0", "freecad"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]

    # Keep only alphanumeric and spaces
    clean = re.sub(r"[^a-z0-9\s]", "", clean).strip()
    # Collapse whitespace to single underscore
    clean = re.sub(r"\s+", "_", clean)
    # Truncate to reasonable length
    return clean[:60].rstrip("_")


def _generate_tags(actions: list[dict]) -> list[str]:
    """Extract tags from action targets and types."""
    tag_keywords = {
        "sketch", "circle", "rectangle", "line", "arc", "polygon",
        "pad", "pocket", "fillet", "chamfer", "revolution", "mirror",
        "pattern", "groove", "thickness", "shell", "body", "constraint",
        "distance", "radius", "diameter", "horizontal", "vertical",
        "export", "stl", "step", "part_design", "sketcher",
        "cylinder", "cube", "tube", "hole", "slot", "boss",
    }

    found_tags = set()
    for action in actions:
        # Check target
        target = action.get("action", {}).get("target", "").lower()
        thought = action.get("thought", "").lower()
        menu_path = action.get("action", {}).get("menu_path", "").lower()

        text = f"{target} {thought} {menu_path}"
        for tag in tag_keywords:
            if tag in text:
                found_tags.add(tag)

    return sorted(found_tags)


def _generate_description(title: str, actions: list[dict]) -> str:
    """Generate a description from the video title and action summary."""
    action_types = set()
    for a in actions:
        action_type = a.get("action", {}).get("type", "")
        target = a.get("action", {}).get("target", "")
        if action_type and target:
            action_types.add(f"{action_type} on {target}")

    summary = ", ".join(list(action_types)[:5])
    return f"Demonstrates: {title}. Key operations: {summary}."


def _normalize_action(action: dict) -> dict:
    """Ensure action dict has all expected fields."""
    return {
        "type": action.get("type", "unknown"),
        "target": action.get("target", ""),
        "menu_path": action.get("menu_path", ""),
        "value": action.get("value", ""),
        "position": action.get("position", [0.0, 0.0]),
    }


def _get_narration(action: dict) -> str:
    """Extract narration text from an action's metadata."""
    # The narration may be stored in the transcript overlap
    # For now, use the thought as a proxy
    return action.get("thought", "")


def _extract_tips(actions: list[dict]) -> list[str]:
    """Extract tips from action patterns (menu paths, common sequences)."""
    tips = set()
    for action in actions:
        menu_path = action.get("action", {}).get("menu_path", "")
        if menu_path:
            tips.add(f"Menu path: {menu_path}")

    # Deduplicate and limit
    return sorted(tips)[:10]
