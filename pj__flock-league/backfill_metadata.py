#!/usr/bin/env python3
"""Fetch metadata and captions for Flock League videos already downloaded."""

import argparse
import re
from pathlib import Path

from yt_dlp import YoutubeDL


PROJECT_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = PROJECT_DIR / "uploads"
VIDEO_EXTENSIONS = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
VIDEO_ID_PATTERN = re.compile(r"\[([A-Za-z0-9_-]{11})\]$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cookies-from-browser",
        choices=("chrome", "edge", "firefox"),
        help="Use logged-in browser cookies when YouTube requests authentication.",
    )
    return parser.parse_args()


def downloaded_video_ids() -> list[str]:
    video_ids: list[str] = []
    for path in sorted(UPLOADS_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        match = VIDEO_ID_PATTERN.search(path.stem)
        if match:
            video_ids.append(match.group(1))
        else:
            print(f"Skipping file without a YouTube ID in its name: {path.name}")
    return video_ids


def main() -> None:
    args = parse_args()
    if not UPLOADS_DIR.exists():
        raise SystemExit(f"Uploads directory does not exist: {UPLOADS_DIR}")

    video_ids = downloaded_video_ids()
    if not video_ids:
        raise SystemExit("No downloaded videos with YouTube IDs were found.")

    options = {
        "skip_download": True,
        "outtmpl": str(UPLOADS_DIR / "%(upload_date)s - %(title)s [%(id)s].%(ext)s"),
        "writeinfojson": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-orig"],
        "subtitlesformat": "vtt",
        "ignoreerrors": True,
        "windowsfilenames": True,
        "overwrites": False,
        "sleep_interval_requests": 1,
    }
    if args.cookies_from_browser:
        options["cookiesfrombrowser"] = (
            args.cookies_from_browser,
            None,
            None,
            None,
        )

    urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids]
    print(f"Backfilling metadata and captions for {len(urls)} downloaded videos.")
    with YoutubeDL(options) as downloader:
        result = downloader.download(urls)

    if result:
        raise SystemExit(result)


if __name__ == "__main__":
    main()
