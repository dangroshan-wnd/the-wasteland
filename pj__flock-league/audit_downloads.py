#!/usr/bin/env python3
"""Audit downloaded Flock League videos, metadata, captions, and media integrity."""

import argparse
import json
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHANNEL_URL = "https://www.youtube.com/@FlockLeague/videos"
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_UPLOADS_DIR = PROJECT_DIR / "uploads"
DEFAULT_REPORT_PATH = PROJECT_DIR / "reports" / "download-audit.json"
VIDEO_EXTENSIONS = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
VIDEO_ID_PATTERN = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
ENGLISH_CAPTION_PATTERN = re.compile(r"\.en(?:-[A-Za-z0-9]+)?\.vtt$", re.IGNORECASE)
PARTIAL_SUFFIXES = (".part", ".ytdl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uploads", type=Path, default=DEFAULT_UPLOADS_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--check-channel",
        action="store_true",
        help="Compare local IDs with the current channel listing (uses the network).",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=("chrome", "edge", "firefox"),
        help="Use browser cookies for the optional channel check.",
    )
    parser.add_argument("--ffprobe", help="Path to ffprobe; defaults to PATH lookup.")
    return parser.parse_args()


def video_id_from_name(path: Path) -> str | None:
    match = VIDEO_ID_PATTERN.search(path.name)
    return match.group(1) if match else None


def load_archive(uploads_dir: Path) -> tuple[set[str], list[str]]:
    archive_path = uploads_dir / ".download-archive.txt"
    if not archive_path.exists():
        return set(), ["Download archive is missing."]

    video_ids: set[str] = set()
    issues: list[str] = []
    for line_number, line in enumerate(
        archive_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        fields = line.split()
        if len(fields) >= 2 and re.fullmatch(r"[A-Za-z0-9_-]{11}", fields[-1]):
            video_ids.add(fields[-1])
        elif line.strip():
            issues.append(f"Unrecognized download archive entry on line {line_number}.")
    return video_ids, issues


def probe_media(path: Path, ffprobe: str) -> dict[str, Any]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"valid": False, "error": str(error)}

    if result.returncode:
        error = result.stderr.strip() or f"ffprobe exited with code {result.returncode}"
        return {"valid": False, "error": error}

    try:
        data = json.loads(result.stdout)
        stream_types = [stream.get("codec_type") for stream in data.get("streams", [])]
        duration = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return {"valid": False, "error": f"Could not parse ffprobe output: {error}"}

    has_video = "video" in stream_types
    has_audio = "audio" in stream_types
    return {
        "valid": has_video and has_audio and duration > 0,
        "duration": duration,
        "has_video": has_video,
        "has_audio": has_audio,
    }


def fetch_channel_ids(browser: str | None) -> tuple[set[str] | None, str | None]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return None, "yt-dlp is not installed; live-channel check skipped."

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "lazy_playlist": False,
    }
    if browser:
        options["cookiesfrombrowser"] = (browser, None, None, None)

    try:
        with YoutubeDL(options) as downloader:
            channel = downloader.extract_info(CHANNEL_URL, download=False)
    except Exception as error:  # yt-dlp has several extractor exception types.
        return None, f"Live-channel check failed: {error}"

    entries = channel.get("entries", []) if channel else []
    ids = {
        entry["id"]
        for entry in entries
        if entry and re.fullmatch(r"[A-Za-z0-9_-]{11}", entry.get("id", ""))
    }
    return ids, None


def audit(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    uploads_dir = args.uploads.resolve()
    if not uploads_dir.is_dir():
        raise SystemExit(f"Uploads directory does not exist: {uploads_dir}")

    media: dict[str, list[Path]] = defaultdict(list)
    metadata: dict[str, list[Path]] = defaultdict(list)
    captions: dict[str, list[Path]] = defaultdict(list)
    unassociated_files: list[str] = []
    playlist_metadata: list[str] = []
    partial_files: list[str] = []
    empty_files: list[str] = []

    for path in sorted(uploads_dir.iterdir()):
        if not path.is_file() or path.name == ".gitignore":
            continue
        if path.stat().st_size == 0:
            empty_files.append(path.name)
        if path.name.lower().endswith(PARTIAL_SUFFIXES):
            partial_files.append(path.name)

        video_id = video_id_from_name(path)
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            if video_id:
                media[video_id].append(path)
            else:
                unassociated_files.append(path.name)
        elif path.name.endswith(".info.json"):
            if video_id:
                metadata[video_id].append(path)
            else:
                playlist_metadata.append(path.name)
        elif path.suffix.lower() == ".vtt":
            if video_id:
                captions[video_id].append(path)
            else:
                unassociated_files.append(path.name)

    archive_ids, archive_issues = load_archive(uploads_dir)
    all_ids = set(media) | set(metadata) | set(captions) | archive_ids
    ffprobe = args.ffprobe or shutil.which("ffprobe")
    episodes: list[dict[str, Any]] = []

    for video_id in sorted(all_ids):
        media_files = media.get(video_id, [])
        metadata_files = metadata.get(video_id, [])
        caption_files = captions.get(video_id, [])
        issues: list[dict[str, str]] = []
        english_captions = [
            path.name for path in caption_files if ENGLISH_CAPTION_PATTERN.search(path.name)
        ]
        episode: dict[str, Any] = {
            "video_id": video_id,
            "video_title": None,
            "media": [path.name for path in media_files],
            "metadata": [path.name for path in metadata_files],
            "captions": [path.name for path in caption_files],
            "english_captions": english_captions,
            "in_download_archive": video_id in archive_ids,
            "needs_transcription": not english_captions,
            "issues": issues,
        }

        if len(media_files) != 1:
            issues.append(
                {
                    "severity": "error",
                    "message": f"Expected one media file; found {len(media_files)}.",
                }
            )
        elif media_files[0].stat().st_size < 1_000_000:
            issues.append(
                {"severity": "warning", "message": "Media file is smaller than 1 MB."}
            )

        metadata_duration: float | None = None
        if len(metadata_files) != 1:
            issues.append(
                {
                    "severity": "error",
                    "message": f"Expected one metadata file; found {len(metadata_files)}.",
                }
            )
        else:
            try:
                metadata_data = json.loads(metadata_files[0].read_text(encoding="utf-8"))
                episode["title"] = metadata_data.get("title")
                episode["video_title"] = metadata_data.get("title")
                episode["upload_date"] = metadata_data.get("upload_date")
                episode["source_url"] = metadata_data.get("webpage_url")
                if metadata_data.get("id") != video_id:
                    issues.append(
                        {
                            "severity": "error",
                            "message": "Metadata ID does not match the filename ID.",
                        }
                    )
                if metadata_data.get("duration") is not None:
                    metadata_duration = float(metadata_data["duration"])
                    episode["metadata_duration"] = metadata_duration
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                issues.append(
                    {"severity": "error", "message": f"Metadata could not be parsed: {error}"}
                )

        if not english_captions:
            issues.append(
                {
                    "severity": "warning",
                    "message": "No English captions found; transcription is required.",
                }
            )
        if video_id not in archive_ids:
            issues.append(
                {"severity": "warning", "message": "Video ID is absent from download archive."}
            )

        if len(media_files) == 1 and ffprobe:
            probe = probe_media(media_files[0], ffprobe)
            episode["media_probe"] = probe
            if not probe["valid"]:
                issues.append({"severity": "error", "message": "Media integrity probe failed."})
            elif metadata_duration is not None:
                difference = abs(probe["duration"] - metadata_duration)
                tolerance = max(2.0, metadata_duration * 0.02)
                if difference > tolerance:
                    issues.append(
                        {
                            "severity": "warning",
                            "message": f"Media duration differs by {difference:.1f} seconds.",
                        }
                    )
        elif len(media_files) == 1:
            episode["media_probe"] = {"valid": None, "skipped": "ffprobe not found"}

        severities = {issue["severity"] for issue in issues}
        episode["status"] = (
            "error" if "error" in severities else "warning" if "warning" in severities else "ok"
        )
        episodes.append(episode)

    channel_ids: set[str] | None = None
    channel_error: str | None = None
    if args.check_channel:
        channel_ids, channel_error = fetch_channel_ids(args.cookies_from_browser)

    media_ids = set(media)
    errors = sum(episode["status"] == "error" for episode in episodes)
    warnings = sum(episode["status"] == "warning" for episode in episodes)
    valid_media = None
    if ffprobe:
        valid_media = sum(
            episode.get("media_probe", {}).get("valid") is True for episode in episodes
        )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "uploads_directory": str(uploads_dir),
        "summary": {
            "episode_ids": len(all_ids),
            "local_videos": len(media_ids),
            "metadata_files": sum(len(files) for files in metadata.values()),
            "episodes_with_english_captions": sum(
                bool(episode["english_captions"]) for episode in episodes
            ),
            "episodes_needing_transcription": sum(
                episode["needs_transcription"] for episode in episodes
            ),
            "download_archive_ids": len(archive_ids),
            "valid_media": valid_media,
            "episodes_with_errors": errors,
            "episodes_with_warnings": warnings,
            "partial_files": len(partial_files),
            "empty_files": len(empty_files),
        },
        "media_probe": {"available": bool(ffprobe), "executable": ffprobe},
        "files": {
            "partial": partial_files,
            "empty": empty_files,
            "unassociated": unassociated_files,
            "playlist_metadata": playlist_metadata,
        },
        "download_archive_issues": archive_issues,
        "comparisons": {
            "archive_missing_local_media": sorted(archive_ids - media_ids),
            "local_media_missing_from_archive": sorted(media_ids - archive_ids),
        },
        "channel_check": {
            "requested": args.check_channel,
            "error": channel_error,
            "channel_video_count": len(channel_ids) if channel_ids is not None else None,
            "channel_missing_local_media": (
                sorted(channel_ids - media_ids) if channel_ids is not None else None
            ),
            "local_media_not_on_channel": (
                sorted(media_ids - channel_ids) if channel_ids is not None else None
            ),
        },
        "episodes": episodes,
    }

    has_global_errors = bool(partial_files or empty_files or archive_issues)
    return report, bool(errors or has_global_errors)


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    summary = report["summary"]
    valid_media = summary["valid_media"]
    valid_media_text = str(valid_media) if valid_media is not None else "not checked"
    print("Flock League download audit")
    print(f"  Local videos:                    {summary['local_videos']}")
    print(f"  Metadata files:                  {summary['metadata_files']}")
    print(f"  Episodes with English captions:  {summary['episodes_with_english_captions']}")
    print(f"  Need transcription:              {summary['episodes_needing_transcription']}")
    print(f"  Valid media:                      {valid_media_text}")
    print(f"  Episodes with errors:             {summary['episodes_with_errors']}")
    print(f"  Episodes with warnings:           {summary['episodes_with_warnings']}")
    print(f"  Partial files:                    {summary['partial_files']}")
    print(f"  Empty files:                      {summary['empty_files']}")

    channel = report["channel_check"]
    if channel["requested"]:
        if channel["error"]:
            print(f"  Channel check:                    failed ({channel['error']})")
        else:
            print(f"  Current channel videos:           {channel['channel_video_count']}")
            print(
                "  Channel videos missing locally:   "
                f"{len(channel['channel_missing_local_media'])}"
            )

    if not report["media_probe"]["available"]:
        print("\nWarning: ffprobe was not found; media integrity checks were skipped.")

    problem_episodes = [episode for episode in report["episodes"] if episode["issues"]]
    if problem_episodes:
        print("\nEpisode issues:")
        for episode in problem_episodes:
            for issue in episode["issues"]:
                print(
                    f"  [{issue['severity'].upper()}] {episode['video_id']}: "
                    f"{issue['message']}"
                )

    print(f"\nReport written to: {report_path}")


def main() -> None:
    args = parse_args()
    report, has_errors = audit(args)
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print_summary(report, report_path)
    if has_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
