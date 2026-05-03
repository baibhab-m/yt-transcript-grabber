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

## Avoiding YouTube's IP block (RECOMMENDED for batches >20 videos)

YouTube heavily rate-limits anonymous requests in 2025-26. If your batch comes back with all rows showing `status=ip-blocked`, you need to give the app your YouTube login cookies. One-time setup, takes about a minute:

1. In your browser (Chrome, Brave, Edge, or Firefox), install **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)**. It's open source ([source](https://github.com/kairi003/Get-cookies.txt-LOCALLY)).
2. Visit youtube.com and make sure you're logged in.
3. Click the extension icon, then click **Export** (with youtube.com as the active tab).
4. A `youtube.com_cookies.txt` file downloads.
5. Move it to the same folder as `app.py` and rename it to `cookies.txt`.
6. Restart the app. You should see `Cookies file loaded from: ...cookies.txt` in the terminal.

The app will now make requests as your logged-in self, which YouTube treats much more leniently. Cookies last for months. The `cookies.txt` is git-ignored so it never gets committed.

## Caveats

- **Some videos have no captions at all.** Those rows will come back with `status=no-captions`. There's nothing the tool can do, the captions just don't exist on YouTube.
- **Don't run this from a cloud server.** YouTube blocks AWS/GCP/Azure IPs almost immediately, no amount of cookies will fix that. Local laptops are fine.
- **If everything still fails with `ip-blocked` even with cookies set up**, your home IP has been temporarily 429-throttled by YouTube's transcript endpoint specifically. This is a per-IP throttle, not per-account, so cookies/VPN-into-cloud don't fix it. The fastest workarounds:
  1. **Phone hotspot** — connect your laptop to a phone hotspot (cellular IP), run the batch, switch back. ~5 min setup.
  2. **Consumer VPN** (ProtonVPN free tier or similar) — switch to a residential-looking exit. Cloudflare WARP, AWS, GCP, Azure are already blocked.
  3. **Wait 1–24 hours** — 429s are transient. Try again the next day.
- **Status column meanings:**
  - `ok` - transcript and metadata both fetched
  - `metadata-only` - transcript fetched, metadata blocked (still useful)
  - `no-captions` - the video genuinely has no captions
  - `ip-blocked` - YouTube refused both endpoints (try a different IP, see above)
  - `invalid-link` - couldn't extract a video ID from that row

## License

MIT.
