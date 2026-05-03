"""
YouTube Transcript Grabber - local web app.

Yashvardhan uploads a CSV with YouTube links in some column. The app
adds video_id / channel / title / transcript / status columns and gives
back a downloadable CSV. All processing runs locally on his laptop.
"""
from __future__ import annotations
import io, os, re, sys, time, uuid, random, threading, webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pandas as pd
import requests
from flask import Flask, render_template, request, jsonify, send_file, abort

from yt_dlp import YoutubeDL
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
)

# ---------- config ----------
GREETING_NAME = "Yashvardhan"
# Conservative defaults: YouTube ramped up bot detection in 2025-26 and 4
# parallel workers with sub-second jitter is enough to get ip-blocked on
# fresh residential IPs. Two workers + 1.5-3.5s jitter behaves like a
# casual human and survives 100+ video batches.
MAX_WORKERS = int(os.environ.get("YT_WORKERS", "1"))
JITTER_RANGE = (3.0, 7.0)
# Path to a Netscape-format cookies.txt file. If present, both youtube-
# transcript-api and yt-dlp use it, which makes YouTube treat us as a
# logged-in user instead of an anonymous scraper. This is the only
# reliable way to fix IpBlocked errors on residential ISPs that YouTube
# has flagged. Default location: cookies.txt next to this file. Override
# with YT_COOKIES_FILE env var.
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
COOKIES_FILE = os.environ.get("YT_COOKIES_FILE",
                              str(APP_DIR / "cookies.txt"))
# How long to back off after an IpBlocked / DownloadError, then try once more.
RETRY_BACKOFF_SEC = 30
PREFERRED_LANGS = ["en", "en-US", "en-GB"]
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _has_cookies() -> bool:
    return bool(COOKIES_FILE) and Path(COOKIES_FILE).is_file() and Path(COOKIES_FILE).stat().st_size > 100


def _build_session() -> requests.Session | None:
    """Build a requests.Session with cookies loaded from COOKIES_FILE."""
    if not _has_cookies():
        return None
    cj = MozillaCookieJar(COOKIES_FILE)
    try:
        cj.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return None
    s = requests.Session()
    s.cookies = cj
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    })
    return s


def _ydl_opts(extra: dict | None = None) -> dict:
    """Base yt-dlp options. Adds cookies file if available."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    if _has_cookies():
        opts["cookiefile"] = COOKIES_FILE
    if extra:
        opts.update(extra)
    return opts


def _is_blocked_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("ipblocked", "ip blocked", "sign in to confirm",
                                   "http error 429", "too many requests",
                                   "blocked", "rate"))

app = Flask(__name__,
            template_folder=str(APP_DIR / "templates"),
            static_folder=str(APP_DIR / "static"))

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ---------- transcript engine (same as before) ----------

def extract_id(s) -> str | None:
    if s is None: return None
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none"): return None
    if ID_RE.match(s): return s
    try:
        u = urlparse(s)
        if u.netloc.endswith("youtu.be"):
            return (u.path.lstrip("/")[:11]) or None
        if "youtube.com" in u.netloc:
            q = parse_qs(u.query)
            if "v" in q: return q["v"][0][:11]
            parts = [p for p in u.path.split("/") if p]
            if parts and ID_RE.match(parts[-1]): return parts[-1]
    except Exception:
        pass
    return None


def get_metadata(vid: str) -> dict:
    """Fetch only title + channel; skip format probing (it's pointless here
    and trips up yt-dlp when cookies are from mobile YouTube)."""
    with YoutubeDL(_ydl_opts({"extract_flat": False})) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}",
                                download=False, process=False)
    return {
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
    }


def fetch_transcript(vid: str) -> str:
    """Try once, on a blocked-style error sleep and retry once more."""
    session = _build_session()
    api = YouTubeTranscriptApi(http_client=session) if session else YouTubeTranscriptApi()
    try:
        fetched = api.fetch(vid, languages=PREFERRED_LANGS)
    except Exception as e:
        if _is_blocked_error(e):
            time.sleep(RETRY_BACKOFF_SEC)
            fetched = api.fetch(vid, languages=PREFERRED_LANGS)
        else:
            raise
    return " ".join(s.text.strip() for s in fetched.snippets if s.text.strip())


def vtt_to_text(vtt: str) -> str:
    out, last = [], None
    for line in vtt.splitlines():
        l = line.strip()
        if not l or l.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or "-->" in l:
            continue
        l = re.sub(r"<[^>]+>", "", l)
        l = re.sub(r"\{\\an\d+\}|&nbsp;", "", l)
        if l and l != last:
            out.append(l); last = l
    return " ".join(out)


def fetch_transcript_fallback(vid: str, tmpdir: Path) -> str:
    tmpdir.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts({
        "writesubtitles": True, "writeautomaticsub": True,
        "subtitleslangs": ["en.*"], "subtitlesformat": "vtt",
        "outtmpl": str(tmpdir / "%(id)s.%(ext)s"),
    })
    def _try():
        with YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
    try:
        _try()
    except Exception as e:
        if _is_blocked_error(e):
            time.sleep(RETRY_BACKOFF_SEC)
            _try()
        else:
            raise
    vtts = sorted(tmpdir.glob(f"{vid}*.vtt"))
    if not vtts:
        raise RuntimeError("no captions available")
    text = vtt_to_text(vtts[0].read_text(encoding="utf-8", errors="ignore"))
    for f in vtts:
        try: f.unlink()
        except OSError: pass
    return text


def _pick_snippet(text: str) -> str:
    """Return one good sentence from a transcript for the wait-page quote card."""
    if not text: return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    candidates = [s.strip() for s in sentences if 80 <= len(s.strip()) <= 220]
    if not candidates:
        candidates = [s.strip() for s in sentences if 60 <= len(s.strip()) <= 280]
    if not candidates:
        return text[:200].strip() + ("..." if len(text) > 200 else "")
    return random.choice(candidates)


def _classify_error(e1: Exception, e2: Exception | None) -> str:
    """Turn raw exception types into a friendlier status label."""
    n1 = type(e1).__name__
    if n1 in ("TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable"):
        if e2 is None: return "no-captions"
        if _is_blocked_error(e2): return "ip-blocked"
        return f"no-captions ({type(e2).__name__})"
    if _is_blocked_error(e1) and (e2 is None or _is_blocked_error(e2)):
        return "ip-blocked"
    if e2 is None:
        return f"error: {n1}"
    return f"error: {n1}/{type(e2).__name__}"


def process_one(vid: str, tmpdir: Path) -> dict:
    """Transcript first, metadata second.

    If transcript fetching is the only thing the user needs, no point
    burning a metadata request that might trigger a block before we
    even get to the actual transcript. On success we backfill metadata
    best-effort: if it blocks, the row still has the transcript and a
    'metadata-only' status.
    """
    out = {"video_id": vid, "channel": "", "title": "", "transcript": "", "status": "ok"}
    time.sleep(random.uniform(*JITTER_RANGE))

    # 1. Transcript via primary, then yt-dlp fallback on any failure
    e1, e2 = None, None
    try:
        out["transcript"] = fetch_transcript(vid)
    except Exception as exc1:
        e1 = exc1
        try:
            out["transcript"] = fetch_transcript_fallback(vid, tmpdir)
        except Exception as exc2:
            e2 = exc2

    if not out["transcript"]:
        out["status"] = _classify_error(e1, e2)
        return out

    # 2. Metadata best-effort. Don't fail the row if metadata blocks.
    try:
        m = get_metadata(vid)
        out["channel"], out["title"] = m["channel"], m["title"]
    except Exception as e:
        out["status"] = "metadata-only" if _is_blocked_error(e) else f"metadata-error: {type(e).__name__}"
    return out


# ---------- column auto-detection ----------

def autodetect_link_column(df: pd.DataFrame) -> str | None:
    """Return the column most likely to contain YouTube links."""
    best, best_score = None, 0
    for col in df.columns:
        sample = df[col].dropna().head(10).astype(str).tolist()
        if not sample: continue
        score = sum(1 for v in sample if extract_id(v))
        if score > best_score:
            best, best_score = col, score
    return best if best_score > 0 else None


# ---------- background worker ----------

def run_job(job_id: str, df: pd.DataFrame, link_col: str):
    job = JOBS[job_id]
    tmpdir = Path(job["tmpdir"])
    rows = df.to_dict(orient="records")
    total = len(rows)
    job["total"] = total
    job["log"].append(f"Starting {total} videos with {MAX_WORKERS} workers")

    # extract IDs once
    for r in rows:
        r["__vid"] = extract_id(r.get(link_col, ""))

    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {}
        for idx, r in enumerate(rows):
            if r["__vid"]:
                futs[ex.submit(process_one, r["__vid"], tmpdir)] = idx
            else:
                results[idx] = {"video_id": "", "channel": "", "title": "",
                                "transcript": "", "status": "invalid-link"}
                with JOBS_LOCK: job["done"] += 1

        for f in as_completed(futs):
            idx = futs[f]
            try:
                results[idx] = f.result()
            except Exception as e:
                results[idx] = {"video_id": rows[idx].get("__vid", ""),
                                "channel": "", "title": "", "transcript": "",
                                "status": f"crash: {type(e).__name__}"}
            with JOBS_LOCK:
                job["done"] += 1
                r = results[idx]
                tag = "OK" if r["status"] == "ok" else "FAIL"
                label = (r["channel"] + " - " + r["title"][:50]) if r["channel"] else (r["video_id"] or "?")
                job["log"].append(f"[{tag}] {label}")
                # Live stats for the wait page
                txt = r.get("transcript", "")
                if txt:
                    job["words_total"] = job.get("words_total", 0) + len(txt.split())
                    snippet = _pick_snippet(txt)
                    if snippet:
                        job["snippets"].append({
                            "quote": snippet,
                            "channel": r.get("channel") or "",
                            "title": r.get("title") or "",
                            "video_id": r.get("video_id", ""),
                        })

    # build output dataframe: original cols + new cols
    new_cols = ["video_id", "channel", "title", "transcript", "status"]
    for c in new_cols:
        df[c] = [results.get(i, {}).get(c, "") for i in range(len(rows))]

    out_path = tmpdir / "transcripts_output.csv"
    df.to_csv(out_path, index=False, encoding="utf-8")
    with JOBS_LOCK:
        job["status"] = "done"
        job["output"] = str(out_path)
        job["log"].append(f"Saved {out_path.name}")


# ---------- routes ----------

@app.route("/")
def index():
    return render_template("index.html", greeting_name=GREETING_NAME)


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file uploaded"}), 400
    try:
        raw = f.read()
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding="latin-1")
        except Exception:
            return jsonify({"error": f"couldn't parse CSV: {e}"}), 400

    link_col = request.form.get("link_col") or autodetect_link_column(df)
    if not link_col:
        return jsonify({"error": "no column with YouTube links found",
                        "columns": list(df.columns)}), 400

    job_id = uuid.uuid4().hex[:12]
    tmpdir = Path.home() / "Downloads" / "YouTubeTranscripts" / job_id
    tmpdir.mkdir(parents=True, exist_ok=True)

    JOBS[job_id] = {"status": "running", "done": 0, "total": len(df),
                    "tmpdir": str(tmpdir), "log": [], "output": None,
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "link_col": link_col, "words_total": 0, "snippets": []}
    threading.Thread(target=run_job, args=(job_id, df, link_col),
                     daemon=True).start()
    return jsonify({"job_id": job_id, "total": len(df), "link_col": link_col})


@app.route("/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if not job: abort(404)
    return jsonify({"status": job["status"], "done": job["done"],
                    "total": job["total"], "log": job["log"][-20:],
                    "link_col": job.get("link_col"),
                    "words_total": job.get("words_total", 0),
                    "snippets": job.get("snippets", [])[-15:]})


@app.route("/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job or not job.get("output"): abort(404)
    return send_file(job["output"], as_attachment=True,
                     download_name="transcripts_output.csv",
                     mimetype="text/csv")


def _format_duration(secs) -> str:
    if not secs: return ""
    secs = int(secs)
    h, rem = divmod(secs, 3600); m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _format_views(n) -> str:
    if not n: return ""
    n = int(n)
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M views"
    if n >= 1_000:     return f"{n/1_000:.1f}K views"
    return f"{n} views"


@app.route("/channel", methods=["POST"])
def channel():
    """Fetch a channel's video list (flat, fast)."""
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    limit = int(data.get("limit") or 100)
    if not url:
        return jsonify({"error": "no channel URL"}), 400
    # nudge plain handles like @lexfridman or channel handles
    if url.startswith("@"):
        url = f"https://www.youtube.com/{url}/videos"
    elif "youtube.com" not in url and "youtu.be" not in url:
        url = f"https://www.youtube.com/@{url.lstrip('@')}/videos"
    # ensure /videos for channel pages so we get uploads
    if "youtube.com/" in url and "/videos" not in url and "/playlist" not in url and "watch?" not in url:
        url = url.rstrip("/") + "/videos"

    opts = _ydl_opts({"extract_flat": "in_playlist", "playlistend": limit})
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": f"couldn't load channel: {type(e).__name__}: {e}"}), 400

    entries = info.get("entries") or []
    videos = []
    for e in entries:
        if not e: continue
        vid = e.get("id")
        if not vid or len(vid) != 11: continue
        videos.append({
            "video_id": vid,
            "title": e.get("title") or "",
            "duration": _format_duration(e.get("duration")),
            "views": _format_views(e.get("view_count")),
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
        })
    return jsonify({
        "channel_title": info.get("channel") or info.get("uploader") or info.get("title") or "",
        "channel_url": info.get("channel_url") or info.get("webpage_url") or url,
        "count": len(videos),
        "videos": videos,
    })


@app.route("/start_from_ids", methods=["POST"])
def start_from_ids():
    """Kick off a transcript job from a list of video IDs (no CSV upload)."""
    data = request.get_json(force=True, silent=True) or {}
    ids = [v for v in (data.get("video_ids") or []) if isinstance(v, str) and ID_RE.match(v)]
    if not ids:
        return jsonify({"error": "no valid video IDs"}), 400
    df = pd.DataFrame({"youtube_link": [f"https://youtu.be/{v}" for v in ids]})

    job_id = uuid.uuid4().hex[:12]
    tmpdir = Path.home() / "Downloads" / "YouTubeTranscripts" / job_id
    tmpdir.mkdir(parents=True, exist_ok=True)
    JOBS[job_id] = {"status": "running", "done": 0, "total": len(df),
                    "tmpdir": str(tmpdir), "log": [], "output": None,
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "link_col": "youtube_link",
                    "words_total": 0, "snippets": []}
    threading.Thread(target=run_job, args=(job_id, df, "youtube_link"),
                     daemon=True).start()
    return jsonify({"job_id": job_id, "total": len(df)})


@app.route("/columns", methods=["POST"])
def columns():
    """Preview columns of an uploaded CSV without starting a job."""
    f = request.files.get("file")
    if not f: return jsonify({"error": "no file"}), 400
    try:
        raw = f.read()
        df = pd.read_csv(io.BytesIO(raw))
    except Exception:
        df = pd.read_csv(io.BytesIO(raw), encoding="latin-1")
    return jsonify({"columns": list(df.columns),
                    "rows": len(df),
                    "guess": autodetect_link_column(df)})


# ---------- launcher ----------

def open_browser(url: str, delay: float = 1.2):
    def _go():
        time.sleep(delay)
        try: webbrowser.open(url)
        except Exception: pass
    threading.Thread(target=_go, daemon=True).start()


def main():
    port = int(os.environ.get("PORT", "5173"))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  YouTube Transcript Grabber running at {url}")
    print(f"  Hello {GREETING_NAME}! Open the URL above in your browser if it didn't open automatically.")
    if _has_cookies():
        print(f"  Cookies file loaded from: {COOKIES_FILE}")
    else:
        print(f"  No cookies file found at {COOKIES_FILE}.")
        print(f"  Without cookies YouTube may IP-block you on big batches.")
        print(f"  See README for one-time cookie export instructions.\n")
    open_browser(url)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
