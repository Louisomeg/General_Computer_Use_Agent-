# =============================================================================
# Pipeline Orchestrator — run the full visual skill learning pipeline
# =============================================================================
# Usage:
#   python -m pipeline.run_pipeline --url "https://youtube.com/watch?v=..."
#   python -m pipeline.run_pipeline --url "VIDEO_ID"
#   python -m pipeline.run_pipeline --dir pipeline/downloads/VIDEO_ID
#   python -m pipeline.run_pipeline --rebuild-index
#   python -m pipeline.run_pipeline --url "..." --stages keyframes,label,filter,build

import argparse
import sys
from pathlib import Path

from google import genai

from pipeline.crawl import download_video, extract_video_id
from pipeline.transcribe import get_transcript
from pipeline.extract_keyframes import extract_keyframes
from pipeline.label_actions import label_actions
from pipeline.filter_quality import filter_actions
from pipeline.build_skills import build_skill, update_index


DEFAULT_DOWNLOAD_DIR = Path(__file__).parent / "downloads"
ALL_STAGES = ("crawl", "transcribe", "keyframes", "label", "filter", "build")


def run_pipeline(
    url: str = None,
    video_dir: Path = None,
    stages: tuple = ALL_STAGES,
    threshold: int = 15000,
    min_score: int = 3,
    api_delay: float = 1.0,
) -> Path | None:
    """Run the full pipeline end-to-end.

    Args:
        url: YouTube URL or video ID (required if 'crawl' in stages).
        video_dir: Existing download directory (skips crawl).
        stages: Tuple of stages to run.
        threshold: MOG2 keyframe threshold.
        min_score: Minimum quality score (0-5).
        api_delay: Seconds between API calls.

    Returns:
        Path to generated skill.yaml, or None if pipeline fails.
    """
    client = genai.Client()
    video_info = None

    # Stage 1: Download
    if "crawl" in stages:
        if not url:
            print("[pipeline] ERROR: --url required for crawl stage")
            return None
        video_info = download_video(url, DEFAULT_DOWNLOAD_DIR)
        video_dir = video_info["video_path"].parent
    elif video_dir is None:
        if url:
            video_id = extract_video_id(url)
            video_dir = DEFAULT_DOWNLOAD_DIR / video_id
        else:
            print("[pipeline] ERROR: --url or --dir required")
            return None

    if not video_dir.exists():
        print(f"[pipeline] ERROR: directory not found: {video_dir}")
        return None

    # Get video info if we skipped crawl
    if video_info is None:
        from pipeline.crawl import _build_result
        try:
            video_id = video_dir.name
            video_info = _build_result(video_id, video_dir)
        except FileNotFoundError as e:
            print(f"[pipeline] ERROR: {e}")
            return None

    video_path = video_info["video_path"]
    video_id = video_info["video_id"]
    title = video_info["title"]
    keyframe_dir = video_dir / "keyframes"
    labeled_path = video_dir / "labeled_actions.json"
    scored_path = video_dir / "scored_actions.json"

    print(f"\n{'='*60}")
    print(f"Processing: {title}")
    print(f"Video ID:   {video_id}")
    print(f"Stages:     {', '.join(stages)}")
    print(f"{'='*60}\n")

    # Stage 2: Transcribe
    transcript = []
    if "transcribe" in stages or "label" in stages:
        transcript = get_transcript(video_dir)
        if not transcript:
            print("[pipeline] WARNING: No transcript available. "
                  "Action labeling will proceed without narration context.")

    # Stage 3: Extract keyframes
    keyframes = []
    if "keyframes" in stages:
        keyframes = extract_keyframes(video_path, keyframe_dir, threshold=threshold)
        if not keyframes:
            print("[pipeline] ERROR: No keyframes extracted")
            return None
    elif "label" in stages or "filter" in stages or "build" in stages:
        # Load cached keyframes
        import json
        manifest = keyframe_dir / "keyframes.json"
        if manifest.exists():
            with open(manifest) as f:
                keyframes = json.load(f)

    # Stage 4: Label actions
    labeled = []
    if "label" in stages:
        if not keyframes:
            print("[pipeline] ERROR: No keyframes for labeling")
            return None
        labeled = label_actions(keyframes, transcript, client, labeled_path,
                                api_delay=api_delay)
    elif "filter" in stages or "build" in stages:
        # Load cached labels
        import json
        if labeled_path.exists():
            with open(labeled_path) as f:
                labeled = json.load(f)

    # Stage 5: Filter quality
    filtered = []
    if "filter" in stages:
        if not labeled:
            print("[pipeline] ERROR: No labeled actions for filtering")
            return None
        filtered = filter_actions(labeled, client, min_score=min_score,
                                  output_path=scored_path, api_delay=api_delay)
    elif "build" in stages:
        # Load cached scores or use unfiltered
        import json
        if scored_path.exists():
            with open(scored_path) as f:
                scored = json.load(f)
            filtered = [a for a in scored if a.get("quality_score", 0) >= min_score]
        else:
            filtered = labeled  # Use unfiltered if no scores exist

    # Stage 6: Build skill
    if "build" in stages:
        if not filtered:
            print("[pipeline] ERROR: No actions to build skill from")
            return None
        skill_path = build_skill(video_id, title, filtered)
        update_index()
        print(f"\n[pipeline] Done! Skill created at: {skill_path}")
        return skill_path

    print("\n[pipeline] Pipeline stages complete")
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Visual Skill Learning Pipeline — process FreeCAD tutorials "
                    "into demonstration skills with screenshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Process a full YouTube video:
    python -m pipeline.run_pipeline --url "https://youtube.com/watch?v=..."

  Process only specific stages:
    python -m pipeline.run_pipeline --url "VIDEO_ID" --stages keyframes,label

  Process an already-downloaded video:
    python -m pipeline.run_pipeline --dir pipeline/downloads/VIDEO_ID

  Rebuild the demo index:
    python -m pipeline.run_pipeline --rebuild-index
        """,
    )
    parser.add_argument("--url", help="YouTube URL or video ID")
    parser.add_argument("--dir", type=Path, help="Existing video download directory")
    parser.add_argument("--stages", default=",".join(ALL_STAGES),
                        help=f"Comma-separated stages (default: all). "
                             f"Options: {','.join(ALL_STAGES)}")
    parser.add_argument("--threshold", type=int, default=15000,
                        help="MOG2 keyframe threshold (default: 15000)")
    parser.add_argument("--min-score", type=int, default=3,
                        help="Minimum quality score 0-5 (default: 3)")
    parser.add_argument("--api-delay", type=float, default=1.0,
                        help="Seconds between Gemini API calls (default: 1.0)")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="Rebuild the demo index and exit")
    args = parser.parse_args()

    if args.rebuild_index:
        update_index()
        return

    if not args.url and not args.dir:
        parser.print_help()
        sys.exit(1)

    stages = tuple(s.strip() for s in args.stages.split(","))
    for s in stages:
        if s not in ALL_STAGES:
            print(f"Unknown stage: {s}. Valid: {', '.join(ALL_STAGES)}")
            sys.exit(1)

    run_pipeline(
        url=args.url,
        video_dir=args.dir,
        stages=stages,
        threshold=args.threshold,
        min_score=args.min_score,
        api_delay=args.api_delay,
    )


if __name__ == "__main__":
    main()
