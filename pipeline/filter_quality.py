# =============================================================================
# Quality Filtering — score labeled actions with Gemini and filter low quality
# =============================================================================
# Replaces TongUI's Qwen2.5-VL scoring with Gemini.
#
# Usage:
#   from pipeline.filter_quality import filter_actions
#   filtered = filter_actions(labeled_actions, client, min_score=3)

import json
import time
from pathlib import Path

from google.genai import Client, types

from core.settings import DEFAULT_MODEL


QUALITY_PROMPT = """Rate this FreeCAD tutorial action on a 0-5 quality scale.

Action: {thought}
Type: {action_type}
Target: {action_target}

Screenshot BEFORE the action:
[First image below]

Screenshot AFTER the action:
[Second image below]

Scoring criteria:
5 = Clear action with visible UI change. Demonstrates a specific FreeCAD operation (menu click, tool activation, geometry creation).
4 = Good action, minor ambiguity in what exactly changed.
3 = Action is identifiable but screenshots are unclear or change is subtle.
2 = Vague action, hard to tell what happened.
1 = Just scrolling, window resizing, or viewport rotation — not a meaningful operation.
0 = Corrupt frame, duplicate, or completely unrelated to FreeCAD.

Respond with ONLY a JSON object (no markdown): {{"score": N, "reason": "brief explanation"}}
"""


def filter_actions(
    labeled_actions: list[dict],
    client: Client,
    min_score: int = 3,
    output_path: Path = None,
    api_delay: float = 1.0,
) -> list[dict]:
    """Score each labeled action with Gemini and filter by quality.

    Args:
        labeled_actions: From label_actions() — list of action dicts.
        client: google.genai.Client
        min_score: Minimum score to keep (0-5).
        output_path: Optional path to save scored results.
        api_delay: Seconds between API calls.

    Returns:
        Filtered list with only actions scoring >= min_score.
        Each action gets 'quality_score' and 'quality_reason' fields added.
    """
    # Check for cached scores
    if output_path and output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            cached = json.load(f)
        filtered = [a for a in cached if a.get("quality_score", 0) >= min_score]
        print(f"[filter] Using cached: {len(filtered)}/{len(cached)} passed (min_score={min_score})")
        return filtered

    scored = []

    for i, action in enumerate(labeled_actions):
        print(f"[filter] Scoring action {i + 1}/{len(labeled_actions)}: "
              f"{action.get('action', {}).get('target', '?')}")

        # Load screenshots
        before_path = Path(action.get("before_frame", ""))
        after_path = Path(action.get("after_frame", ""))

        if not before_path.exists() or not after_path.exists():
            print(f"[filter]   Skipping — missing screenshots")
            action["quality_score"] = 0
            action["quality_reason"] = "missing screenshots"
            scored.append(action)
            continue

        before_bytes = before_path.read_bytes()
        after_bytes = after_path.read_bytes()

        prompt = QUALITY_PROMPT.format(
            thought=action.get("thought", "unknown"),
            action_type=action.get("action", {}).get("type", "unknown"),
            action_target=action.get("action", {}).get("target", "unknown"),
        )

        try:
            response = client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=[
                    types.Content(role="user", parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(mime_type="image/png", data=before_bytes),
                        types.Part.from_bytes(mime_type="image/png", data=after_bytes),
                    ]),
                ],
            )

            score_data = _parse_score(response.text)
            action["quality_score"] = score_data.get("score", 0)
            action["quality_reason"] = score_data.get("reason", "")
            print(f"[filter]   -> Score: {action['quality_score']}/5 — {action['quality_reason']}")

        except Exception as e:
            print(f"[filter]   -> API error: {e}")
            action["quality_score"] = 0
            action["quality_reason"] = f"API error: {e}"

        scored.append(action)
        time.sleep(api_delay)

    # Save all scored results
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(scored, f, indent=2, default=str)

    # Filter
    filtered = [a for a in scored if a.get("quality_score", 0) >= min_score]
    print(f"[filter] {len(filtered)}/{len(scored)} actions passed (min_score={min_score})")
    return filtered


def _parse_score(text: str) -> dict:
    """Parse Gemini's score response."""
    if not text:
        return {"score": 0, "reason": "empty response"}

    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        clean = "\n".join(lines)

    try:
        data = json.loads(clean)
        return {
            "score": int(data.get("score", 0)),
            "reason": str(data.get("reason", "")),
        }
    except (json.JSONDecodeError, ValueError):
        # Try to extract JSON from text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
                return {
                    "score": int(data.get("score", 0)),
                    "reason": str(data.get("reason", "")),
                }
            except (json.JSONDecodeError, ValueError):
                pass
        return {"score": 0, "reason": "could not parse response"}
