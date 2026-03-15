# =============================================================================
# Video Download — fetch YouTube videos + subtitles via yt-dlp
# =============================================================================
# Usage:
#   from pipeline.crawl import download_video
#   info = download_video("https://youtube.com/watch?v=...", Path("pipeline/downloads"))

import json
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_DOWNLOAD_DIR = Path(__file__).parent / "downloads"


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats or plain IDs."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Cannot extract video ID from: {url}")


def download_video(url: str, output_dir: Path = None) -> dict:
    """Download a YouTube video + auto-subtitles with yt-dlp.

    Args:
        url: YouTube URL or video ID.
        output_dir: Base download directory. Each video gets a subdirectory.

    Returns:
        dict with keys: video_id, video_path, subtitle_path (or None), title

    Idempotent: skips download if MP4 already exists.
    """
    output_dir = output_dir or DEFAULT_DOWNLOAD_DIR
    video_id = extract_video_id(url)
    video_dir = output_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing download
    mp4_files = list(video_dir.glob("*.mp4"))
    if mp4_files:
        print(f"[crawl] Video already downloaded: {mp4_files[0].name}")
        return _build_result(video_id, video_dir)

    # Download with yt-dlp (use Python module invocation for cross-platform compat)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--format", "bestvideo[height<=720][vcodec^=avc1]+bestaudio/bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "--write-auto-sub",
        "--sub-lang", "en",
        "--write-info-json",
        "--output", str(video_dir / "%(id)s.%(ext)s"),
        "--no-playlist",
        "--max-filesize", "500M",
        url if url.startswith("http") else f"https://www.youtube.com/watch?v={url}",
    ]

    print(f"[crawl] Downloading video {video_id}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr[:500]}")

    print(f"[crawl] Download complete: {video_id}")
    return _build_result(video_id, video_dir)


def _build_result(video_id: str, video_dir: Path) -> dict:
    """Build result dict from downloaded files."""
    # Find the MP4
    mp4_files = list(video_dir.glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError(f"No MP4 found in {video_dir}")
    video_path = mp4_files[0]

    # Find subtitles (.vtt or .srt)
    sub_path = None
    for ext in ("*.en.vtt", "*.vtt", "*.en.srt", "*.srt"):
        subs = list(video_dir.glob(ext))
        if subs:
            sub_path = subs[0]
            break

    # Get title from info JSON
    title = video_id
    info_files = list(video_dir.glob("*.info.json"))
    if info_files:
        try:
            with open(info_files[0], encoding="utf-8") as f:
                info = json.load(f)
            title = info.get("title", video_id)
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            pass

    return {
        "video_id": video_id,
        "video_path": video_path,
        "subtitle_path": sub_path,
        "title": title,
    }


def list_downloaded(output_dir: Path = None) -> list[dict]:
    """List all already-downloaded videos."""
    output_dir = output_dir or DEFAULT_DOWNLOAD_DIR
    if not output_dir.exists():
        return []
    results = []
    for subdir in sorted(output_dir.iterdir()):
        if subdir.is_dir():
            try:
                results.append(_build_result(subdir.name, subdir))
            except FileNotFoundError:
                continue
    return results
