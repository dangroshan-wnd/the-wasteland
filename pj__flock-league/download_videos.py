#!/usr/bin/env python3
"""Download all videos from the Flock League YouTube channel."""

import argparse
from pathlib import Path
from shutil import which

from yt_dlp import YoutubeDL


CHANNEL_URL = "https://www.youtube.com/@FlockLeague/videos"
PROJECT_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = PROJECT_DIR / "uploads"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cookies-from-browser",
        choices=("chrome", "edge", "firefox"),
        help="Use logged-in browser cookies when YouTube requests authentication.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    options = {
        # Combining YouTube's best separate video/audio streams requires
        # ffmpeg. Use the best pre-combined stream when it is unavailable.
        "format": "bestvideo*+bestaudio/best" if which("ffmpeg") else "best",
        "merge_output_format": "mp4",
        "outtmpl": str(UPLOADS_DIR / "%(upload_date)s - %(title)s [%(id)s].%(ext)s"),
        "download_archive": str(UPLOADS_DIR / ".download-archive.txt"),
        "writeinfojson": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-orig"],
        "subtitlesformat": "vtt",
        "ignoreerrors": True,
        "continuedl": True,
        "windowsfilenames": True,
        "sleep_interval_requests": 10,
    }
    if args.cookies_from_browser:
        options["cookiesfrombrowser"] = (
            args.cookies_from_browser,
            None,
            None,
            None,
        )

    with YoutubeDL(options) as downloader:
        result = downloader.download([CHANNEL_URL])

    if result:
        raise SystemExit(result)


if __name__ == "__main__":
    main()
