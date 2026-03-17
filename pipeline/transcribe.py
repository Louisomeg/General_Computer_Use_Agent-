# =============================================================================
# Transcription — parse yt-dlp subtitles or fallback to Whisper ASR
# =============================================================================
# Usage:
#   from pipeline.transcribe import get_transcript
#   segments = get_transcript(Path("pipeline/downloads/VIDEO_ID"))

import re
from pathlib import Path


def get_transcript(video_dir: Path) -> list[dict]:
    """Load transcript from a video directory.

    Strategy:
    1. Look for .vtt subtitles downloaded by yt-dlp
    2. Fall back to Whisper ASR if no subtitles found

    Returns:
        List of {start: float, end: float, text: str} segments.
        Empty list if transcription fails entirely.
    """
    # Try yt-dlp subtitles first
    for pattern in ("*.en.vtt", "*.vtt"):
        vtt_files = list(video_dir.glob(pattern))
        if vtt_files:
            print(f"[transcribe] Using subtitle file: {vtt_files[0].name}")
            return _parse_vtt(vtt_files[0])

    # Fallback: Whisper
    mp4_files = list(video_dir.glob("*.mp4"))
    if not mp4_files:
        print("[transcribe] No video or subtitles found")
        return []

    vtt_path = video_dir / f"{mp4_files[0].stem}.whisper.vtt"
    if vtt_path.exists():
        print(f"[transcribe] Using cached Whisper transcript: {vtt_path.name}")
        return _parse_vtt(vtt_path)

    print("[transcribe] No subtitles found, running Whisper...")
    whisper_vtt = _whisper_transcribe(mp4_files[0], vtt_path)
    if whisper_vtt and whisper_vtt.exists():
        return _parse_vtt(whisper_vtt)

    print("[transcribe] Whisper transcription failed")
    return []


def _parse_vtt(vtt_path) -> list[dict]:
    """Parse a WebVTT file into segments.

    Returns list of {start, end, text} dicts with timestamps in seconds.
    Merges consecutive segments from the same speaker to reduce noise.
    """
    vtt_path = Path(vtt_path)
    content = vtt_path.read_text(encoding="utf-8", errors="replace")

    # VTT timestamp pattern: HH:MM:SS.mmm --> HH:MM:SS.mmm
    timestamp_re = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*"
        r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})"
    )

    segments = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        match = timestamp_re.search(lines[i])
        if match:
            start = _ts_to_seconds(match.group(1), match.group(2),
                                   match.group(3), match.group(4))
            end = _ts_to_seconds(match.group(5), match.group(6),
                                 match.group(7), match.group(8))
            # Collect text lines until blank line or next timestamp
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip() and not timestamp_re.search(lines[i]):
                # Strip VTT tags like <c> </c> and speaker tags
                clean = re.sub(r"<[^>]+>", "", lines[i]).strip()
                if clean:
                    text_lines.append(clean)
                i += 1

            text = " ".join(text_lines)
            if text:
                segments.append({"start": start, "end": end, "text": text})
        else:
            i += 1

    # Merge consecutive segments with identical text (yt-dlp duplicates)
    merged = _merge_duplicates(segments)
    print(f"[transcribe] Parsed {len(merged)} segments from {vtt_path.name}")
    return merged


def _ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    """Convert HH:MM:SS.mmm components to seconds."""
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _merge_duplicates(segments: list[dict]) -> list[dict]:
    """Merge consecutive segments with identical text."""
    if not segments:
        return []
    merged = [segments[0].copy()]
    for seg in segments[1:]:
        if seg["text"] == merged[-1]["text"]:
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(seg.copy())
    return merged


def _whisper_transcribe(video_path: Path, output_path: Path) -> Path | None:
    """Run OpenAI Whisper on a video file, output VTT.

    Uses the 'base' model for speed. Returns path to .vtt file or None.
    """
    try:
        import whisper
    except ImportError:
        print("[transcribe] openai-whisper not installed. "
              "Install with: pip install openai-whisper")
        return None

    try:
        model = whisper.load_model("base")
        result = model.transcribe(str(video_path), word_timestamps=True)

        # Write as VTT
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for segment in result.get("segments", []):
                start = _seconds_to_vtt(segment["start"])
                end = _seconds_to_vtt(segment["end"])
                text = segment["text"].strip()
                if text:
                    f.write(f"{start} --> {end}\n{text}\n\n")

        print(f"[transcribe] Whisper output: {output_path.name}")
        return output_path
    except Exception as e:
        print(f"[transcribe] Whisper error: {e}")
        return None


def _seconds_to_vtt(seconds: float) -> str:
    """Convert seconds to VTT timestamp format HH:MM:SS.mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
