# Flock League video downloader

Downloads every video listed on the Flock League YouTube channel's Videos tab
into `uploads/`.

From the repository root, install the dependency into the existing virtual
environment and run the downloader:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\flock-league\requirements.txt
.\.venv\Scripts\python.exe .\flock-league\download_videos.py
```

Install [ffmpeg](https://ffmpeg.org/download.html) and make it available on
`PATH` to let `yt-dlp` combine YouTube's highest-quality video and audio
streams. Without ffmpeg, `yt-dlp` falls back to the best combined stream.

The script is safe to rerun. Partial downloads resume, and completed video IDs
are recorded in `uploads/.download-archive.txt` so they are skipped on later
runs. Run it again whenever you want to fetch newly published videos.

## Analysis pipeline plan

The downloaded episodes will eventually feed an evidence-first analysis
pipeline. Written recaps and league history should be derived from timestamped
source material rather than relying on an agent to remember facts between
episodes.

### 1. Capture and backfill source metadata

After the current media download has finished:

- Update `download_videos.py` so future downloads also save each video's
  `.info.json` metadata, English manual captions, and English automatic captions
  when manual captions are unavailable.
- Add a separate `backfill_metadata.py` script that retrieves those sidecars for
  videos already in `uploads/` without downloading the media again.
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

1. Finish the current video download.
2. Add metadata and caption capture for future downloads.
3. Backfill metadata and captions without redownloading media.
4. Verify all local files are matched to metadata by YouTube ID.
5. Process one representative episode into a timestamped transcript,
   `events.json`, and `recap.md`.
6. Review the event schema and extraction quality before processing the full
   archive chronologically.
