# =============================================================================
# Action Labeling — use Gemini Vision to identify GUI actions between keyframes
# =============================================================================
# Replaces TongUI's UI-TARS stage with Gemini.
# Sends consecutive keyframe pairs + narration context to Gemini and asks
# "what action happened between these two screenshots?"
#
# Usage:
#   from pipeline.label_actions import label_actions
#   actions = label_actions(keyframes, transcript, client, output_path)

import json
import time
from pathlib import Path

from google.genai import Client, types

from core.settings import DEFAULT_MODEL


ACTION_LABELING_PROMPT = """You are analyzing a FreeCAD tutorial video. Given two consecutive screenshots from the tutorial, identify the GUI action that was performed between them.

Screenshot 1 (BEFORE the action):
[First image below]

Screenshot 2 (AFTER the action):
[Second image below]

{narration_section}

FreeCAD UI reference:
- Menu bar at top: File, Edit, View, Sketch, Part Design, etc.
- Model tree on the left panel
- 3D viewport in the center
- Tasks/Properties panel on the lower-left
- Python console at the bottom

Respond with ONLY a valid JSON object (no markdown, no code fences):
{{
  "thought": "What the user is trying to accomplish with this action",
  "action": {{
    "type": "click|type|scroll|drag|hotkey|menu_navigation",
    "target": "Description of the UI element acted on",
    "menu_path": "Full menu path if menu navigation, e.g. 'Sketch > Sketcher geometries > Circle'. Empty string otherwise.",
    "value": "Text typed or key pressed, if applicable. Empty string otherwise.",
    "position": [0.0, 0.0]
  }},
  "result": "What visibly changed in the UI after the action",
  "verify": "How to confirm the action succeeded"
}}

Position should be normalized 0.0-1.0 coordinates (x, y) of where the click/action happened.
If the action type is "menu_navigation", fill in menu_path and set position to the final menu item's approximate location.
If no meaningful action can be identified, set type to "unknown".
"""


def label_actions(
    keyframes: list[dict],
    transcript: list[dict],
    client: Client,
    output_path: Path,
    api_delay: float = 1.0,
) -> list[dict]:
    """Label actions between consecutive keyframe pairs using Gemini.

    For each pair (frame_i, frame_i+1):
    1. Load both PNGs as bytes
    2. Find narration text overlapping the timestamp range
    3. Send to Gemini with structured prompt
    4. Parse JSON response

    Args:
        keyframes: From extract_keyframes() — [{frame_number, timestamp, path}]
        transcript: From get_transcript() — [{start, end, text}]
        client: google.genai.Client
        output_path: Where to save labeled actions JSON
        api_delay: Seconds between API calls (rate limiting)

    Returns:
        List of labeled actions with structure:
        [{index, before_frame, after_frame, timestamp, thought, action, result, verify}]
    """
    # Check for cached results
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            cached = json.load(f)
        print(f"[label] Using cached: {len(cached)} labeled actions")
        return cached

    if len(keyframes) < 2:
        print("[label] Need at least 2 keyframes for action labeling")
        return []

    labeled_actions = []

    for i in range(len(keyframes) - 1):
        before = keyframes[i]
        after = keyframes[i + 1]

        print(f"[label] Labeling action {i + 1}/{len(keyframes) - 1}: "
              f"frame {before['frame_number']} -> {after['frame_number']}")

        # Load screenshots
        before_path = Path(before["path"])
        after_path = Path(after["path"])
        if not before_path.exists() or not after_path.exists():
            print(f"[label]   Skipping — missing screenshot files")
            continue

        before_bytes = before_path.read_bytes()
        after_bytes = after_path.read_bytes()

        # Find relevant narration
        narration = _find_narration(
            transcript, before["timestamp"], after["timestamp"]
        )

        # Build prompt
        narration_section = ""
        if narration:
            narration_section = f"Narrator context: \"{narration}\""
        else:
            narration_section = "No narration available for this segment."

        prompt_text = ACTION_LABELING_PROMPT.format(narration_section=narration_section)

        # Send to Gemini
        try:
            response = client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=[
                    types.Content(role="user", parts=[
                        types.Part.from_text(text=prompt_text),
                        types.Part.from_bytes(mime_type="image/png", data=before_bytes),
                        types.Part.from_bytes(mime_type="image/png", data=after_bytes),
                    ]),
                ],
            )

            action_data = _parse_response(response.text)
            if action_data:
                labeled_actions.append({
                    "index": i + 1,
                    "before_frame": str(before_path),
                    "after_frame": str(after_path),
                    "timestamp": before["timestamp"],
                    "end_timestamp": after["timestamp"],
                    **action_data,
                })
                print(f"[label]   -> {action_data.get('action', {}).get('type', '?')}: "
                      f"{action_data.get('action', {}).get('target', '?')}")
            else:
                print(f"[label]   -> Could not parse response")

        except Exception as e:
            print(f"[label]   -> API error: {e}")

        # Rate limiting
        time.sleep(api_delay)

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(labeled_actions, f, indent=2, default=str)

    print(f"[label] Labeled {len(labeled_actions)} actions, saved to {output_path}")
    return labeled_actions


def _find_narration(
    transcript: list[dict], start_ts: float, end_ts: float
) -> str:
    """Find transcript text overlapping the given timestamp range."""
    if not transcript:
        return ""

    matching = []
    for seg in transcript:
        # Check for overlap
        if seg["end"] >= start_ts and seg["start"] <= end_ts:
            matching.append(seg["text"])

    return " ".join(matching).strip()


def _parse_response(text: str) -> dict | None:
    """Parse Gemini's JSON response into a structured action dict."""
    if not text:
        return None

    # Strip markdown code fences if present
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        # Remove first and last lines (``` markers)
        lines = [l for l in lines if not l.strip().startswith("```")]
        clean = "\n".join(lines)

    try:
        data = json.loads(clean)
        # Validate required fields
        if "thought" in data and "action" in data:
            return data
        return None
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
                if "thought" in data and "action" in data:
                    return data
            except json.JSONDecodeError:
                pass
        return None
