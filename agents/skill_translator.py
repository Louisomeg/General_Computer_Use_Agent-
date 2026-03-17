# =============================================================================
# Skill Translator Agent — YouTube tutorial → YAML skill file
# =============================================================================
# Takes a YouTube FreeCAD tutorial URL and automatically produces a structured
# YAML skill file (type: knowledge) that teaches the CAD agent how to perform
# the operations demonstrated in the video.
#
# Pipeline:
#   1. Extract transcript from YouTube video
#   2. Load existing skills as schema reference
#   3. LLM extraction call (Gemini text-only) to convert transcript to YAML
#   4. Output YAML skill file for human review
#
# Usage:
#   python -m agents.skill_translator "https://www.youtube.com/watch?v=VIDEO_ID"
#   # or from code:
#   translator = SkillTranslatorAgent(client)
#   yaml_content = translator.translate("https://www.youtube.com/watch?v=VIDEO_ID")

import re
import sys
from pathlib import Path

import yaml
from google import genai

from core.models import load_knowledge_skills, SKILLS_DIR
from core.settings import DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Extraction prompt — tells the LLM how to convert a transcript to YAML
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a FreeCAD skill extraction assistant. Given a tutorial video transcript,
extract the operations performed and structure them into our YAML skill format.

## Target YAML Format

Each skill file has this structure:
```yaml
name: <snake_case_name>
type: knowledge
category: <category: setup | sketcher | part_design | assembly | other>
description: >
  One-line description of what this skill file covers.

operations:
  - name: <operation_name>
    description: <what this operation does>
    when_to_use: "<when an agent should use this operation>"
    prerequisite: "<what must be true before this operation>"
    actions:
      - what: "<goal of this action>"
        how: "<exact FreeCAD menu path or click instructions>"
        type_value: "<exact text to type in dialogs, with units>"
        verify: "<what the screen should show after>"
        gotcha: "<common mistake to avoid>"
        fallback: "<alternative approach if primary fails>"
        skip_if: "<condition where this action can be skipped>"
    tips:
      - "<helpful tip for this operation>"

tips:
  - "<general tips for the whole category>"

troubleshooting:
  - problem: "<description of common problem>"
    solution: "<how to fix it>"
```

## Existing Operations (for reference — avoid duplicates)
{existing_operations}

## Translation Rules

1. MENU PATHS, NOT TOOLBAR ICONS:
   - "Click the Pad button" → how: "Part Design menu → Pad"
   - "Click the sketch icon" → how: "Part Design menu → Create sketch"
   - Always use: "MenuName menu → Submenu → Item" format

2. DIMENSIONS WITH UNITS:
   - Always add " mm" to dimensions in type_value fields
   - "Set length to 30" → type_value: "30 mm"
   - FreeCAD may default to micrometers — always specify mm

3. CLOSING SKETCHES:
   - "Close the sketch" → how: "Sketch menu → Close sketch"
   - NEVER use "Press Escape" for closing sketches (Escape only cancels the active tool)

4. GOTCHAS AND TIPS:
   - Note any warnings, mistakes, or "be careful" moments from the narrator
   - Translate "if this doesn't work, try..." into fallback fields
   - Common issues become troubleshooting entries

5. SKIP DUPLICATES:
   - If an operation matches an existing one (listed above), note it but don't recreate it
   - Instead, add any NEW tips or gotchas to the existing operation's tips list
   - Only create new entries for operations NOT in the existing list

6. VISUAL POSITIONING:
   - "Click in the viewport" → specify WHERE (upper-left, at origin, etc.)
   - "Click the face" → specify WHICH face (top face, side face, etc.)

## Tutorial Transcript
{transcript}

## Output
Write ONLY the YAML content (no markdown code fences, no explanation).
If the tutorial covers operations that already exist, output a section called
"enrichments" at the top with new tips/gotchas for those operations.
For genuinely new operations, output the full YAML skill file.
"""


class SkillTranslatorAgent:
    """Translates YouTube FreeCAD tutorials into structured YAML skill files."""

    def __init__(self, client: genai.Client):
        self.client = client

    def translate(self, youtube_url: str, output_path: str = None) -> str:
        """Main entry point: YouTube URL → YAML skill content.

        Args:
            youtube_url: Full YouTube URL or video ID
            output_path: Optional path to write YAML file (default: stdout)

        Returns:
            The generated YAML content as a string
        """
        print(f"[Skill Translator] Processing: {youtube_url}")

        # Step 1: Get transcript
        transcript = self._get_transcript(youtube_url)
        if not transcript:
            print("[Skill Translator] ERROR: Could not get transcript")
            return ""

        print(f"[Skill Translator] Transcript: {len(transcript)} entries, "
              f"{sum(len(e['text']) for e in transcript)} chars")

        # Step 2: Load existing skills as schema reference
        existing_ops = self._get_existing_operations()
        print(f"[Skill Translator] Existing operations: {len(existing_ops)}")

        # Step 3: LLM extraction
        yaml_content = self._extract_skill(transcript, existing_ops)
        if not yaml_content:
            print("[Skill Translator] ERROR: LLM extraction returned empty")
            return ""

        # Step 4: Validate
        is_valid = self._validate_yaml(yaml_content)
        if not is_valid:
            print("[Skill Translator] WARNING: Generated YAML has issues — review carefully")

        # Step 5: Output — split multi-document YAML into separate files
        if output_path:
            self._write_output(yaml_content, output_path)
        else:
            print(f"[Skill Translator] Generated YAML ({len(yaml_content)} chars):")
            print(yaml_content)

        return yaml_content

    def _write_output(self, yaml_content: str, output_path: str) -> None:
        """Write YAML output, splitting multi-document output into separate files.

        If the LLM produces multiple YAML documents (separated by ---), each
        skill document gets its own file. Enrichments go to a separate file.
        Single-document output goes to the specified path as-is.
        """
        try:
            documents = list(yaml.safe_load_all(yaml_content))
        except yaml.YAMLError:
            # If parsing fails, just write raw content
            Path(output_path).write_text(yaml_content, encoding="utf-8")
            print(f"[Skill Translator] Written raw to: {output_path}")
            return

        if len(documents) <= 1:
            # Single document — write as-is
            Path(output_path).write_text(yaml_content, encoding="utf-8")
            print(f"[Skill Translator] Written to: {output_path}")
            return

        # Multi-document — split into separate files
        output_dir = Path(output_path).parent
        written = []

        for doc in documents:
            if not isinstance(doc, dict):
                continue

            if "enrichments" in doc and "name" not in doc:
                # Enrichments file
                fname = output_dir / "enrichments_from_tutorial.yaml"
                fname.write_text(
                    yaml.dump(doc, default_flow_style=False, allow_unicode=True,
                              sort_keys=False, width=120),
                    encoding="utf-8",
                )
                written.append(str(fname))
            elif "name" in doc:
                # Skill document — use name as filename
                name = doc["name"]
                fname = output_dir / f"{name}.yaml"
                fname.write_text(
                    yaml.dump(doc, default_flow_style=False, allow_unicode=True,
                              sort_keys=False, width=120),
                    encoding="utf-8",
                )
                written.append(str(fname))

        # Write the combined output only if no individual files were created
        if not written:
            Path(output_path).write_text(yaml_content, encoding="utf-8")
            written.append(output_path)

        for f in written:
            print(f"[Skill Translator] Written: {f}")

    # ------------------------------------------------------------------
    # Transcript extraction
    # ------------------------------------------------------------------

    def _get_transcript(self, youtube_url: str) -> list[dict]:
        """Extract transcript from YouTube video.

        Uses youtube-transcript-api package (v1.2+).
        Returns list of {text, start, duration} entries.
        """
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            print("[Skill Translator] ERROR: youtube-transcript-api not installed.")
            print("  Install it: pip install youtube-transcript-api")
            return []

        video_id = self._extract_video_id(youtube_url)
        if not video_id:
            print(f"[Skill Translator] ERROR: Could not extract video ID from: {youtube_url}")
            return []

        api = YouTubeTranscriptApi()
        try:
            fetched = api.fetch(video_id)
            return fetched.to_raw_data()
        except Exception as e:
            print(f"[Skill Translator] ERROR: Could not get transcript: {e}")
            # Try with auto-generated captions
            try:
                fetched = api.fetch(
                    video_id, languages=['en', 'en-US', 'en-GB']
                )
                return fetched.to_raw_data()
            except Exception as e2:
                print(f"[Skill Translator] ERROR: Auto-captions also failed: {e2}")
                return []

    def _extract_video_id(self, url: str) -> str:
        """Extract YouTube video ID from various URL formats."""
        # Already a video ID (11 chars, alphanumeric + dash/underscore)
        if re.match(r'^[A-Za-z0-9_-]{11}$', url):
            return url

        # Standard URL: youtube.com/watch?v=VIDEO_ID
        match = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', url)
        if match:
            return match.group(1)

        # Short URL: youtu.be/VIDEO_ID
        match = re.search(r'youtu\.be/([A-Za-z0-9_-]{11})', url)
        if match:
            return match.group(1)

        # Embed URL: youtube.com/embed/VIDEO_ID
        match = re.search(r'embed/([A-Za-z0-9_-]{11})', url)
        if match:
            return match.group(1)

        return ""

    # ------------------------------------------------------------------
    # Existing skills reference
    # ------------------------------------------------------------------

    def _get_existing_operations(self) -> str:
        """Load existing knowledge skills and format as a reference list."""
        skills = load_knowledge_skills()
        if not skills:
            return "(no existing operations)"

        ops = []
        for skill in skills:
            category = skill.get("category", "unknown")
            for op in skill.get("operations", []):
                name = op.get("name", "?")
                desc = op.get("description", "")
                ops.append(f"- [{category}] {name}: {desc}")

        return "\n".join(ops)

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _extract_skill(self, transcript: list[dict], existing_ops: str) -> str:
        """Use Gemini to extract operations from transcript into YAML format."""
        # Format transcript with timestamps
        transcript_text = "\n".join(
            f"[{entry['start']:.0f}s] {entry['text']}"
            for entry in transcript
        )

        # Truncate if too long (Gemini has context limits)
        max_chars = 80000
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars] + "\n... (truncated)"

        prompt = EXTRACTION_PROMPT.format(
            existing_operations=existing_ops,
            transcript=transcript_text,
        )

        try:
            response = self.client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                # Remove first and last lines (fences)
                lines = raw.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw = "\n".join(lines)

            return raw

        except Exception as e:
            print(f"[Skill Translator] LLM extraction failed: {e}")
            return ""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_yaml(self, yaml_content: str) -> bool:
        """Basic validation of the generated YAML.

        Handles both single-document and multi-document YAML (separated by ---).
        Multi-document output is common when the LLM produces enrichments for
        existing operations plus new skill documents.
        """
        try:
            documents = list(yaml.safe_load_all(yaml_content))
        except yaml.YAMLError as e:
            print(f"[Skill Translator] YAML parse error: {e}")
            return False

        if not documents:
            print("[Skill Translator] YAML is empty")
            return False

        total_ops = 0
        total_enrichments = 0
        all_valid = True

        for doc_idx, data in enumerate(documents):
            if not isinstance(data, dict):
                print(f"[Skill Translator] Document {doc_idx} is not a dict")
                all_valid = False
                continue

            # Enrichments-only document (no name required)
            if "enrichments" in data and "name" not in data:
                n = len(data["enrichments"])
                total_enrichments += n
                print(f"[Skill Translator] Document {doc_idx}: {n} enrichments")
                continue

            # Skill document — check required fields
            if "name" not in data:
                print(f"[Skill Translator] Document {doc_idx} missing 'name' field")
                all_valid = False
                continue

            if data.get("type") != "knowledge":
                print(f"[Skill Translator] Document {doc_idx} ({data['name']}): "
                      f"type is '{data.get('type')}', expected 'knowledge'")

            operations = data.get("operations", [])
            if not operations:
                print(f"[Skill Translator] Document {doc_idx} ({data['name']}): no operations")
                continue

            # Check each operation has required fields
            for i, op in enumerate(operations):
                if "name" not in op:
                    print(f"[Skill Translator] Document {doc_idx}, "
                          f"operation {i} missing 'name'")
                    all_valid = False
                    continue
                if "actions" not in op or not op["actions"]:
                    print(f"[Skill Translator] Operation '{op.get('name')}' has no actions")
                    all_valid = False
                    continue

                # Check actions have required fields
                for j, action in enumerate(op["actions"]):
                    if "what" not in action or "how" not in action:
                        print(f"[Skill Translator] Operation '{op['name']}' action {j} "
                              f"missing 'what' or 'how'")
                        all_valid = False

                total_ops += 1

        print(f"[Skill Translator] Validation: {len(documents)} documents, "
              f"{total_ops} operations, {total_enrichments} enrichments")
        return all_valid


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Command-line entry point for skill translation."""
    if len(sys.argv) < 2:
        print("Usage: python -m agents.skill_translator <youtube_url> [output_file.yaml]")
        print("  youtube_url: YouTube video URL or video ID")
        print("  output_file: Optional path to write YAML (default: stdout)")
        sys.exit(1)

    youtube_url = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    # Initialize Gemini client
    client = genai.Client()

    translator = SkillTranslatorAgent(client)
    result = translator.translate(youtube_url, output_path)

    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
