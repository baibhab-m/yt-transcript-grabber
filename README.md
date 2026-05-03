# YouTube Transcript Grabber

Drop a CSV of YouTube links, get back a CSV with the channel, video title, and full transcript filled in for each row. Runs entirely on your laptop.

![flow](https://img.shields.io/badge/runs-locally-A8C8B8) ![python](https://img.shields.io/badge/python-3.10%2B-FFE5B4) ![license](https://img.shields.io/badge/license-MIT-C9C3DD)

## What it looks like

A small local web page in your browser with two tabs:

### Tab 1: Upload CSV
1. Drop a CSV (or click to pick one).
2. It auto-detects the column with YouTube links. Override if needed.
3. Click **Get transcripts**. Watch the progress bar.
4. Click **Download CSV**. Output has your original columns plus `video_id`, `channel`, `title`, `transcript`, and `status`.

### Tab 2: Browse a channel
1. Paste a channel URL or just `@handle` (e.g. `@hubermanlab`).
2. Click **Load videos**. You get a grid of thumbnails with title, duration, and view count.
3. Click cards to select. Use the search box to filter, or **Select all**.
4. Click **Get transcripts for selected**. Same downloadable CSV at the end.

Nothing leaves your machine except the YouTube requests themselves.

## Install and run (the easy way: Claude Code)

If you have Claude Code installed, open a terminal and just say:

```
clone https://github.com/baibhab-m/yt-transcript-grabber and run it
```

Claude Code will clone, install dependencies, and launch the local server for you.

## Install and run (manual, no Claude Code)

You need Python 3.10 or newer. [Download it here](https://www.python.org/downloads/) if you don't have it (tick "Add Python to PATH" during install).

```bash
git clone https://github.com/baibhab-m/yt-transcript-grabber.git
cd yt-transcript-grabber
pip install -r requirements.txt
python app.py
```

A browser tab opens automatically at `http://127.0.0.1:5173`.

**On Windows**, you can also just double-click `run.bat`.

## CSV format

Any CSV is fine. There just needs to be a column where the values are YouTube URLs or video IDs. Examples that all work:

| topic | youtube_link | notes |
|---|---|---|
| AI | https://www.youtube.com/watch?v=vif8NQcjVf0 | Jensen interview |
| Productivity | https://youtu.be/Pmd6knanPKw | Huberman |
| Origin of life | tOtdJcco3YM | Bare video ID also works |

A `sample_input.csv` is included you can use to test.

## What you get back

The same CSV with these columns appended:

- `video_id` - the 11-char YouTube ID
- `channel` - the uploader's channel name
- `title` - the video title
- `transcript` - the full plain-text transcript
- `status` - `ok` if successful, otherwise a short reason (e.g. `no-transcript`, `invalid-link`)

## How it works

Two-layer fallback:

1. **Primary**: [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) hits YouTube's transcript JSON endpoint. Fast, no API key, free.
2. **Fallback**: If that fails (transcripts disabled, blocked, etc.), [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) downloads the auto-generated VTT subtitle file and we strip it to plain text.

Concurrent fetcher with 4 worker threads + 0.3-0.9s jitter. On a normal home internet connection this handles a few hundred videos comfortably without rate limits.

## Caveats

- **Some videos have no captions at all.** Those rows will come back with `status=no-transcript`. There's nothing the tool can do, the captions just don't exist on YouTube.
- **Don't run this from a cloud server.** YouTube blocks AWS/GCP/Azure IPs almost immediately. Local laptops are fine.
- **Very large batches** (thousands of videos at once) may trigger YouTube rate-limiting on your IP. Stick to a few hundred at a time and you're safe.

## License

MIT.
