# Flock League video downloader

Downloads every video listed on the Flock League YouTube channel's Videos tab
into `uploads/`.

From the repository root, install the dependency into the existing virtual
environment and run the downloader:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\flock-league\requirements.txt
.\.venv\Scripts\python.exe .\flock-league\download_videos.py
```

New downloads also save YouTube metadata (`.info.json`) and available English
manual or automatic captions (`.vtt`) beside each video.

Install [ffmpeg](https://ffmpeg.org/download.html) and make it available on
`PATH` to let `yt-dlp` combine YouTube's highest-quality video and audio
streams. Without ffmpeg, `yt-dlp` falls back to the best combined stream.

The script is safe to rerun. Partial downloads resume, and completed video IDs
are recorded in `uploads/.download-archive.txt` so they are skipped on later
runs. Run it again whenever you want to fetch newly published videos.

### YouTube authentication and rate limits

If YouTube asks you to sign in to confirm you are not a bot, wait before retrying
and pass cookies from a browser where you are already signed into YouTube:

```powershell
.\.venv\Scripts\python.exe .\flock-league\download_videos.py --cookies-from-browser edge
```

Supported values are `chrome`, `edge`, and `firefox`. Treat browser cookies as
credentials: do not share or commit exported cookie files. The script reads them
directly from the selected browser and does not create a cookie file.

### Backfill metadata for existing downloads

To fetch metadata and captions for videos already present in `uploads/` without
downloading their media again:

```powershell
.\.venv\Scripts\python.exe .\flock-league\backfill_metadata.py
```

The backfill only processes media filenames containing a YouTube ID. If YouTube
requires authentication, add `--cookies-from-browser edge` (or another supported
browser) to the command. Existing sidecars are not overwritten.

### Audit downloads

Run the local audit after downloading or backfilling:

```powershell
.\.venv\Scripts\python.exe .\flock-league\audit_downloads.py
```

The audit matches media, metadata, captions, and download-archive entries by
YouTube ID. When `ffprobe` is available on `PATH`, it also checks that each file
contains audio and video and compares its duration with YouTube metadata. A
machine-readable report is written to `flock-league/reports/download-audit.json`.

To also compare the local collection with the current channel listing without
downloading media:

```powershell
.\.venv\Scripts\python.exe .\flock-league\audit_downloads.py --check-channel
```

If YouTube requires authentication for that optional check, add
`--cookies-from-browser chrome` after fully closing Chrome. The local audit does
not contact YouTube and does not modify anything in `uploads/`.

### Plan transient visual review

Plan scene-change, periodic, and transcript-targeted visual samples for an
episode by its YouTube ID:

```powershell
.\.venv\Scripts\python.exe .\flock-league\extract_frames.py -- -9vcgs-W6YM
```

The `--` separator is needed only when a video ID itself begins with a hyphen.

The command creates images only inside a temporary directory. It records their
timestamps, extraction strategies, and triggering caption evidence in
`artifacts/SEASON_ID/YYYYMMDD__VIDEO_TITLE_SLUG/visual-sampling.json`, then deletes every image. Overlapping
samples are deduplicated while retaining every selection reason. An identical
rerun uses the plan cache; pass `--force` to recompute it.

The episode-analysis stage will consume these temporary samples while reviewing
the corresponding transcript windows. Its durable outputs will be
`episode_notes.json`, `events.json`, and `recap.md`; it will retain zero evidence
frames. Any visual evidence can be regenerated later from its video timestamp.

Useful tuning options include `--periodic-interval`, `--scene-threshold`,
`--max-scene-frames`, `--max-targeted-frames`, and `--width`.

### Analyze an episode

The episode reviewer combines cleaned caption windows with transient visual
samples and uses the OpenAI Responses API to write structured notes, normalized
events, and a Markdown recap. Install the dependencies, add your API key to the
ignored `.env` file in the repository root, and provide the episode's YouTube
ID:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\flock-league\requirements.txt
.\.venv\Scripts\python.exe .\flock-league\analyze_episode.py -- -9vcgs-W6YM
```

The local `.env` entry should be:

```dotenv
OPENAI_API_KEY=your-key-here
```

API model usage is billed to the project associated with the supplied key. The
configurable default is `gpt-5.6-terra` with medium reasoning. Use `--model`,
`--reasoning-effort`, `--window-seconds`, `--max-images-per-window`, and
`--image-detail` to tune quality, latency, and cost.

To validate all local preparation without an API key or model charges:

```powershell
.\.venv\Scripts\python.exe .\flock-league\analyze_episode.py --prepare-only -- -9vcgs-W6YM
```

The reviewer writes `metadata.json`, a deduplicated `transcript.json`, and
`review-plan.json` before making model calls. During a full run it checkpoints
each completed window in `episode_notes.json`, allowing an interrupted run to
resume without repeating completed window calls. When complete, it writes:

```text
artifacts/SEASON_ID/YYYYMMDD__VIDEO_TITLE_SLUG/
├── metadata.json
├── transcript.json
├── review-plan.json
├── visual-sampling.json
├── episode_notes.json
├── events.json
└── recap.md
```

Artifact folder names begin with the `YYYYMMDD` upload date followed by two
underscores and a lowercase title slug. Spaces and punctuation become
underscores, while parentheses are retained (for example,
`20240826__2024_fantasy_football_draft_vlog_(flock_league)`). The YouTube ID
remains the canonical lookup key and is stored with `video_title` in generated
JSON files.

Images exist only inside the active temporary directory. Base64 image data is
sent directly to the model and is not written to any artifact. Successful,
failed, and interrupted runs retain zero image files.

### Add season and episode guidance

The guidance bundle is split into focused files:

- `config/defaults.toml` contains instructions that apply to every analysis.
- `config/seasons/season-N.toml` contains one season's date range, owners, and
  season-wide instructions.
- `config/episodes.toml` contains one `[episodes."VIDEO_ID"]` block for every
  downloaded episode, including its title, upload date, season, and editable
  `instructions` value.
- `config/review-guidance.toml` is the bundle manifest and normally does not need
  editing.

Episode mappings take precedence over date matching. The reviewer sends only the
resolved defaults, season, and episode sections to the model. A change to the
applicable guidance changes that episode's analysis fingerprint so the next run
uses the new instructions.

Use triple-quoted strings for multiline guidance:

```toml
instructions = """
First instruction.
Second instruction.
"""
```

Freeform `instructions` guide the review, while actions that Python must enforce
use structured episode controls. For example:

```toml
visual_timestamps = ["00:29:42"]

[episodes."VIDEO_ID".recap]
exclude_event_types = ["draft"]

[[episodes."VIDEO_ID".outputs]]
id = "draft_results"
path = "draft_results.json"
scope = "season" # or "episode"
format = "json"  # or "markdown"
instructions = """Describe the required output content here."""
```

Configured timestamps are always sampled and take priority over automatic
samples. Supplemental paths are selected by trusted TOML—not by episode
content—and are restricted to the configured episode or season artifact
directory. The completed `episode_notes.json` records an instruction-compliance
report and the supplemental files written by the run.

## Analysis pipeline plan

The downloaded episodes will eventually feed an evidence-first analysis
pipeline. Written recaps and league history should be derived from timestamped
source material rather than relying on an agent to remember facts between
episodes.

### 1. Capture and backfill source metadata

The initial metadata support is implemented:

- `download_videos.py` saves each video's `.info.json` metadata and available
  English manual or automatic captions.
- `backfill_metadata.py` retrieves those sidecars for videos already in
  `uploads/` without downloading the media again.
- Use the YouTube video ID as the canonical episode identifier. It is already
  included in each downloaded filename.

Expected files for an episode:

```text
uploads/
├── 20260801 - Episode Title [abc123].mp4
├── 20260801 - Episode Title [abc123].info.json
└── 20260801 - Episode Title [abc123].en.vtt
```

Do not enable comments or thumbnail downloads initially. The info JSON should
provide the title, description, upload date, duration, chapters, URL, and video
ID needed to build the episode catalog.

### 2. Catalog episodes

Create an entry for each episode containing its YouTube ID, source URL, title,
upload date, duration, local filename, processing status, and file fingerprint.
Season and fantasy week should be extracted separately because upload order may
not match league chronology.

### 3. Produce timestamped transcripts

Prefer human-created YouTube captions, then automatic YouTube captions, and
finally local speech-to-text when captions are missing or unusable. Preserve
timestamped segments instead of storing only a single block of text.

### 4. Analyze transcripts and transient visual samples

Review temporary images from scene changes, periodic coverage, and relevant
transcript passages so that scores, standings, trades, and rosters shown on
screen are not missed. Delete the images after recording timestamped notes.

Each episode should produce:

- A readable Markdown recap.
- Structured events such as matchup results, trades, injuries, injury updates,
  roster moves, standings updates, draft picks, and waiver claims.
- Timestamped transcript or frame evidence for every extracted fact.
- Confidence and status fields that distinguish confirmed events from rumors,
  predictions, and later corrections.

### 5. Normalize league entities

Maintain a small league configuration containing members, aliases, fantasy team
names by season, and commonly mis-transcribed player names. Unknown or ambiguous
names should remain unresolved for review rather than being guessed.

### 6. Build derived league state

Use deterministic code to apply accepted events chronologically and build
matchup history, standings, trade history, and injury timelines. Store the
queryable state in SQLite while retaining the per-episode evidence files as the
durable source of truth. Corrections should supersede earlier claims instead of
silently overwriting them.

### Proposed layout

```text
flock-league/
├── uploads/
├── config/
│   ├── league.yaml
│   └── extraction-schema.json
├── artifacts/
│   └── season_1/
│       └── YYYYMMDD__VIDEO_TITLE_SLUG/
│           ├── metadata.json
│           ├── transcript.json
│           ├── transcript.vtt
│           ├── visual-sampling.json
│           ├── episode_notes.json
│           ├── events.json
│           ├── recap.md
│           └── processing.json
├── data/
│   └── league.sqlite
└── reports/
    ├── episodes/
    ├── weekly-results.md
    ├── trades.md
    └── injuries.md
```

Processing should be resumable and versioned so an episode is only reprocessed
when its input, extraction schema, prompt, or model changes.

### Initial implementation milestones

1. Backfill metadata and captions without redownloading media.
2. Verify all local files are matched to metadata by YouTube ID.
3. Process one representative episode into a timestamped transcript,
   `events.json`, and `recap.md`.
4. Review the event schema and extraction quality before processing the full
   archive chronologically.
