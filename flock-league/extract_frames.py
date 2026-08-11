#!/usr/bin/env python3
"""Plan transient visual samples for an episode without retaining image files."""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_VERSION = 3
PROJECT_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = PROJECT_DIR / "uploads"
ARTIFACTS_DIR = PROJECT_DIR / "artifacts"
EPISODES_CONFIG_PATH = PROJECT_DIR / "config" / "episodes.toml"
VIDEO_EXTENSIONS = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
VIDEO_ID_PATTERN = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
VTT_TIMING_PATTERN = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3})"
)
SHOWINFO_TIME_PATTERN = re.compile(r"\bpts_time:(-?\d+(?:\.\d+)?)")
TAG_PATTERN = re.compile(r"<[^>]+>")
KEYWORD_PATTERNS = {
    "matchup": re.compile(r"\bmatch(?:up|ups)?\b", re.IGNORECASE),
    "result": re.compile(
        r"\b(?:beat|beats|beaten|defeat(?:ed|s)?|won|lost|winner|loser|win|loss)\b",
        re.IGNORECASE,
    ),
    "score": re.compile(r"\b(?:score|scores|scored|scoring)\b", re.IGNORECASE),
    "points": re.compile(r"\bpoints?\b", re.IGNORECASE),
    "trade": re.compile(r"\btrad(?:e|es|ed|ing)\b", re.IGNORECASE),
    "injury": re.compile(r"\b(?:injury|injuries|injured|hurt)\b", re.IGNORECASE),
    "availability": re.compile(
        r"\b(?:questionable|doubtful|injured reserve|placed on ir|ruled out)\b",
        re.IGNORECASE,
    ),
    "roster": re.compile(r"\b(?:roster|lineup|bench|starter|starting)\b", re.IGNORECASE),
    "waiver": re.compile(r"\bwaiver(?:s)?\b", re.IGNORECASE),
    "standings": re.compile(r"\bstandings?\b", re.IGNORECASE),
    "record": re.compile(r"\brecords?\b", re.IGNORECASE),
    "week": re.compile(
        r"\bweek\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        re.IGNORECASE,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", help="The 11-character YouTube video ID to process.")
    parser.add_argument(
        "--periodic-interval",
        type=float,
        default=30.0,
        help="Seconds between periodic frames (default: 30).",
    )
    parser.add_argument(
        "--scene-threshold",
        type=float,
        default=0.35,
        help="FFmpeg scene-change score threshold from 0 to 1 (default: 0.35).",
    )
    parser.add_argument(
        "--max-scene-frames",
        type=int,
        default=120,
        help="Maximum evenly sampled scene-change frames (default: 120).",
    )
    parser.add_argument(
        "--max-targeted-frames",
        type=int,
        default=90,
        help="Maximum transcript-targeted frames (default: 90).",
    )
    parser.add_argument(
        "--width", type=int, default=1280, help="Maximum frame width (default: 1280)."
    )
    parser.add_argument("--ffmpeg", help="Path to ffmpeg; defaults to PATH lookup.")
    parser.add_argument("--output", type=Path, help="Override the sampling-plan JSON path.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute the plan even when the inputs and settings are unchanged.",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id):
        parser.error("video_id must be an 11-character YouTube ID")
    if args.periodic_interval <= 0:
        parser.error("--periodic-interval must be greater than zero")
    if not 0 < args.scene_threshold < 1:
        parser.error("--scene-threshold must be between zero and one")
    if args.max_scene_frames < 0 or args.max_targeted_frames < 0:
        parser.error("frame limits cannot be negative")
    if args.width < 2:
        parser.error("--width must be at least 2")
    return args


def artifact_directory(video_id: str, season_id: str) -> Path:
    """Return the canonical season-scoped artifact directory for an episode."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", season_id):
        raise SystemExit(f"Invalid season id for artifact path: {season_id!r}")
    return ARTIFACTS_DIR / season_id / video_id


def configured_episode_season(video_id: str) -> str:
    """Look up an episode's season for the standalone sampling command."""
    try:
        config = tomllib.loads(EPISODES_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(
            f"Could not read episode season mapping {EPISODES_CONFIG_PATH}: {error}"
        ) from error
    episode = (config.get("episodes") or {}).get(video_id)
    season_id = episode.get("season") if isinstance(episode, dict) else None
    if not isinstance(season_id, str) or not season_id:
        raise SystemExit(
            f"Episode {video_id} has no season in {EPISODES_CONFIG_PATH}. "
            "Add its mapping or pass --output explicitly."
        )
    return season_id


def find_ffmpeg(explicit_path: str | None) -> str:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"ffmpeg does not exist: {path}")
        return str(path)

    executable = shutil.which("ffmpeg")
    if executable:
        return executable

    # WinGet updates PATH for new terminals. This also supports the terminal
    # which performed the installation and has not yet been restarted.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        package_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        try:
            matches = sorted(
                package_root.glob(
                    "Gyan.FFmpeg_Microsoft.Winget.Source_*/ffmpeg-*/bin/ffmpeg.exe"
                ),
                reverse=True,
            )
        except OSError:
            matches = []
        if matches:
            return str(matches[0])

    raise SystemExit("ffmpeg was not found. Open a new terminal or pass --ffmpeg PATH.")


def find_episode_files(video_id: str) -> tuple[Path, Path, Path | None, dict[str, Any]]:
    matching = [
        path for path in UPLOADS_DIR.iterdir() if path.is_file() and video_id in path.name
    ]
    media = [path for path in matching if path.suffix.lower() in VIDEO_EXTENSIONS]
    metadata = [path for path in matching if path.name.endswith(".info.json")]
    captions = [path for path in matching if path.suffix.lower() == ".vtt"]
    if len(media) != 1:
        raise SystemExit(f"Expected one media file for {video_id}; found {len(media)}.")
    if len(metadata) != 1:
        raise SystemExit(f"Expected one metadata file for {video_id}; found {len(metadata)}.")

    try:
        metadata_data = json.loads(metadata[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Could not read metadata for {video_id}: {error}") from error
    if metadata_data.get("id") != video_id:
        raise SystemExit("Metadata ID does not match the requested video ID.")

    caption = choose_caption(captions, metadata_data)
    return media[0], metadata[0], caption, metadata_data


def choose_caption(captions: list[Path], metadata: dict[str, Any]) -> Path | None:
    english = [
        path
        for path in captions
        if re.search(r"\.en(?:-[A-Za-z0-9]+)?\.vtt$", path.name, re.IGNORECASE)
    ]
    if not english:
        return None

    manual_languages = {
        language
        for language in (metadata.get("subtitles") or {})
        if language.lower().startswith("en")
    }
    for language in sorted(manual_languages):
        for path in english:
            if path.name.lower().endswith(f".{language.lower()}.vtt"):
                return path

    for preferred_suffix in (".en-orig.vtt", ".en.vtt"):
        for path in english:
            if path.name.lower().endswith(preferred_suffix):
                return path
    return sorted(english)[0]


def parse_vtt_timestamp(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_caption_text(lines: list[str]) -> str:
    cleaned_lines: list[str] = []
    for line in lines:
        cleaned = html.unescape(TAG_PATTERN.sub("", line)).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and (not cleaned_lines or cleaned != cleaned_lines[-1]):
            cleaned_lines.append(cleaned)
    return " ".join(cleaned_lines)


def parse_vtt(path: Path) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        match = VTT_TIMING_PATTERN.search(lines[index])
        if not match:
            index += 1
            continue
        start = parse_vtt_timestamp(match.group("start"))
        end = parse_vtt_timestamp(match.group("end"))
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index])
            index += 1
        text = clean_caption_text(text_lines)
        if text:
            cues.append({"start": start, "end": end, "text": text})
    return cues


def keyword_targets(
    cues: list[dict[str, Any]], duration: float, maximum: int
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for cue in cues:
        keywords = sorted(
            name for name, pattern in KEYWORD_PATTERNS.items() if pattern.search(cue["text"])
        )
        if not keywords:
            continue
        center = (cue["start"] + cue["end"]) / 2
        evidence = {
            "start": round(cue["start"], 3),
            "end": round(cue["end"], 3),
            "text": cue["text"][:500],
            "keywords": keywords,
        }
        if groups and center - groups[-1]["center"] < 5:
            groups[-1]["keywords"].update(keywords)
            groups[-1]["evidence"].append(evidence)
        else:
            groups.append(
                {"center": center, "keywords": set(keywords), "evidence": [evidence]}
            )

    targets: list[dict[str, Any]] = []
    for group in groups:
        for offset in (-2.0, 0.0, 2.0):
            timestamp = min(max(group["center"] + offset, 0), max(duration - 0.05, 0))
            targets.append(
                {
                    "timestamp": timestamp,
                    "keywords": sorted(group["keywords"]),
                    "evidence": group["evidence"],
                }
            )

    if len(targets) > maximum:
        targets = sorted(
            targets, key=lambda target: (-len(target["keywords"]), target["timestamp"])
        )[:maximum]
    return sorted(targets, key=lambda target: target["timestamp"])


def run_filtered_extraction(
    ffmpeg: str, media: Path, output_pattern: Path, video_filter: str
) -> tuple[list[Path], list[float]]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "info",
        "-i",
        str(media),
        "-vf",
        video_filter,
        "-fps_mode",
        "vfr",
        "-q:v",
        "3",
        "-an",
        "-y",
        str(output_pattern),
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "ffmpeg frame extraction failed")
    paths = sorted(output_pattern.parent.glob(output_pattern.name.replace("%06d", "*")))
    timestamps = [float(value) for value in SHOWINFO_TIME_PATTERN.findall(result.stderr)]
    if len(paths) != len(timestamps):
        raise RuntimeError(
            f"FFmpeg produced {len(paths)} frames but reported {len(timestamps)} timestamps."
        )
    return paths, timestamps


def evenly_limit(items: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    if maximum == 0:
        return []
    if len(items) <= maximum:
        return items
    if maximum == 1:
        return [items[len(items) // 2]]
    indexes = {
        round(index * (len(items) - 1) / (maximum - 1)) for index in range(maximum)
    }
    return [items[index] for index in sorted(indexes)]


def extract_target_frame(
    ffmpeg: str, media: Path, output: Path, timestamp: float, width: int
) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(media),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2:force_original_aspect_ratio=decrease",
        "-q:v",
        "3",
        "-an",
        "-y",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode or not output.exists():
        raise RuntimeError(result.stderr.strip() or f"No frame produced at {timestamp:.3f}")


def deduplicate_frames(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {"periodic": 1, "scene": 2, "targeted": 3}
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["timestamp"]):
        if selected and candidate["timestamp"] - selected[-1]["timestamp"] <= 0.75:
            existing = selected[-1]
            existing_priority = max(priority[name] for name in existing["strategies"])
            candidate_priority = max(priority[name] for name in candidate["strategies"])
            existing["strategies"].update(candidate["strategies"])
            existing["target_evidence"].extend(candidate.get("target_evidence", []))
            if candidate_priority > existing_priority:
                existing["path"] = candidate["path"]
                existing["timestamp"] = candidate["timestamp"]
        else:
            selected.append(
                {
                    **candidate,
                    "strategies": set(candidate["strategies"]),
                    "target_evidence": list(candidate.get("target_evidence", [])),
                }
            )
    return selected


def create_temporary_samples(
    *,
    ffmpeg: str,
    media: Path,
    caption: Path | None,
    duration: float,
    temp_dir: Path,
    periodic_interval: float = 30.0,
    scene_threshold: float = 0.35,
    max_scene_frames: int = 120,
    max_targeted_frames: int = 90,
    width: int = 1280,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Create temporary samples for a caller that consumes them before returning."""
    cues = parse_vtt(caption) if caption else []
    targets = keyword_targets(cues, duration, max_targeted_frames)
    candidates: list[dict[str, Any]] = []
    raw_counts: dict[str, int] = {}
    scale = f"scale={width}:-2:force_original_aspect_ratio=decrease"

    scene_filter = f"select='gt(scene,{scene_threshold})',{scale},showinfo"
    scene_paths, scene_times = run_filtered_extraction(
        ffmpeg, media, temp_dir / "scene_%06d.jpg", scene_filter
    )
    scenes = [
        {"path": path, "timestamp": timestamp, "strategies": {"scene"}}
        for path, timestamp in zip(scene_paths, scene_times)
    ]
    raw_counts["scene"] = len(scenes)
    candidates.extend(evenly_limit(scenes, max_scene_frames))

    periodic_filter = (
        f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{periodic_interval})',"
        f"{scale},showinfo"
    )
    periodic_paths, periodic_times = run_filtered_extraction(
        ffmpeg, media, temp_dir / "periodic_%06d.jpg", periodic_filter
    )
    raw_counts["periodic"] = len(periodic_paths)
    candidates.extend(
        {"path": path, "timestamp": timestamp, "strategies": {"periodic"}}
        for path, timestamp in zip(periodic_paths, periodic_times)
    )

    target_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for index, target in enumerate(targets, start=1):
            path = temp_dir / f"target_{index:06d}.jpg"
            future = executor.submit(
                extract_target_frame,
                ffmpeg,
                media,
                path,
                target["timestamp"],
                width,
            )
            futures[future] = (path, target)
        for future in as_completed(futures):
            path, target = futures[future]
            future.result()
            target_results.append(
                {
                    "path": path,
                    "timestamp": target["timestamp"],
                    "strategies": {"targeted"},
                    "target_evidence": target["evidence"],
                }
            )
    raw_counts["targeted"] = len(target_results)
    candidates.extend(target_results)
    return deduplicate_frames(candidates), raw_counts


def input_fingerprint(
    media: Path, metadata: Path, caption: Path | None, settings: dict[str, Any]
) -> str:
    inputs = []
    for path in (media, metadata, caption):
        if path:
            stat = path.stat()
            inputs.append({"name": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    payload = {"version": SCRIPT_VERSION, "inputs": inputs, "settings": settings}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def timestamp_display(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def main() -> None:
    args = parse_args()
    ffmpeg = find_ffmpeg(args.ffmpeg)
    media, metadata, caption, metadata_data = find_episode_files(args.video_id)
    duration = float(metadata_data.get("duration") or 0)
    if duration <= 0:
        raise SystemExit("Episode metadata does not contain a valid duration.")

    output_path = (
        args.output
        or artifact_directory(
            args.video_id, configured_episode_season(args.video_id)
        )
        / "visual-sampling.json"
    ).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings = {
        "periodic_interval": args.periodic_interval,
        "scene_threshold": args.scene_threshold,
        "max_scene_frames": args.max_scene_frames,
        "max_targeted_frames": args.max_targeted_frames,
        "width": args.width,
    }
    fingerprint = input_fingerprint(media, metadata, caption, settings)
    if not args.force and output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if existing.get("fingerprint") == fingerprint:
                print(
                    f"Visual sampling plan is up to date for {args.video_id}: "
                    f"{len(existing['samples'])} samples."
                )
                return
        except (OSError, KeyError, json.JSONDecodeError):
            pass

    with tempfile.TemporaryDirectory(
        prefix="visual-sampling-", dir=output_path.parent
    ) as temp:
        temp_dir = Path(temp)
        selected, raw_counts = create_temporary_samples(
            ffmpeg=ffmpeg,
            media=media,
            caption=caption,
            duration=duration,
            temp_dir=temp_dir,
            periodic_interval=args.periodic_interval,
            scene_threshold=args.scene_threshold,
            max_scene_frames=args.max_scene_frames,
            max_targeted_frames=args.max_targeted_frames,
            width=args.width,
        )
        manifest_samples = []
        for frame in selected:
            manifest_samples.append(
                {
                    "timestamp_seconds": round(frame["timestamp"], 3),
                    "timestamp": timestamp_display(frame["timestamp"]),
                    "strategies": sorted(frame["strategies"]),
                    "target_evidence": frame["target_evidence"],
                }
            )

    manifest = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "video": {
            "id": args.video_id,
            "title": metadata_data.get("title"),
            "duration": duration,
            "media": media.name,
            "metadata": metadata.name,
            "caption": caption.name if caption else None,
        },
        "settings": settings,
        "raw_frame_counts": raw_counts,
        "selected_sample_count": len(manifest_samples),
        "retained_image_count": 0,
        "samples": manifest_samples,
    }
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Planned visual review for {args.video_id} ({metadata_data.get('title')}).")
    print(
        f"  Scene: {raw_counts['scene']} found, "
        f"{min(raw_counts['scene'], args.max_scene_frames)} retained before deduplication"
    )
    print(f"  Periodic: {raw_counts['periodic']}")
    print(f"  Transcript-targeted: {raw_counts['targeted']}")
    print(f"  Final deduplicated samples: {len(manifest_samples)}")
    print("  Retained image files: 0")
    print(f"  Sampling plan: {output_path}")


if __name__ == "__main__":
    main()
