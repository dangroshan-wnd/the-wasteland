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

### 4. Analyze transcripts and selected frames

Extract frames at scene changes and near relevant transcript passages so that
scores, standings, trades, and rosters shown on screen are not missed. Analyze
selected frames rather than every video frame.

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
│   └── VIDEO_ID/
│       ├── metadata.json
│       ├── transcript.json
│       ├── transcript.vtt
│       ├── frames/
│       ├── events.json
│       ├── recap.md
│       └── processing.json
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
