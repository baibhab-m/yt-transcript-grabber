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
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file, abort

from yt_dlp import YoutubeDL
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
)

# ---------- config ----------
GREETING_NAME = "Yashvardhan"
MAX_WORKERS = 4
JITTER_RANGE = (0.3, 0.9)
PREFERRED_LANGS = ["en", "en-US", "en-GB"]
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

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
    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                    "extract_flat": False}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}",
                                download=False)
    return {
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
    }


def fetch_transcript(vid: str) -> str:
    api = YouTubeTranscriptApi()
    fetched = api.fetch(vid, languages=PREFERRED_LANGS)
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
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": ["en.*"], "subtitlesformat": "vtt",
            "outtmpl": str(tmpdir / "%(id)s.%(ext)s")}
    with YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={vid}"])
    vtts = sorted(tmpdir.glob(f"{vid}*.vtt"))
    if not vtts:
        raise RuntimeError("no captions available")
    text = vtt_to_text(vtts[0].read_text(encoding="utf-8", errors="ignore"))
    for f in vtts:
        try: f.unlink()
        except OSError: pass
    return text


def process_one(vid: str, tmpdir: Path) -> dict:
    out = {"video_id": vid, "channel": "", "title": "", "transcript": "", "status": "ok"}
    time.sleep(random.uniform(*JITTER_RANGE))
    try:
        m = get_metadata(vid)
        out["channel"], out["title"] = m["channel"], m["title"]
    except Exception as e:
        out["status"] = f"metadata-error: {type(e).__name__}"

    try:
        out["transcript"] = fetch_transcript(vid)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e1:
        try:
            out["transcript"] = fetch_transcript_fallback(vid, tmpdir)
        except Exception as e2:
            out["status"] = f"no-transcript: {type(e1).__name__}/{type(e2).__name__}"
    except Exception as e:
        try:
            out["transcript"] = fetch_transcript_fallback(vid, tmpdir)
        except Exception as e2:
            out["status"] = f"error: {type(e).__name__}/{type(e2).__name__}"
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
                    "link_col": link_col}
    threading.Thread(target=run_job, args=(job_id, df, link_col),
                     daemon=True).start()
    return jsonify({"job_id": job_id, "total": len(df), "link_col": link_col})


@app.route("/status/<job_id>")
def status(job_id):
    job = JOBS.get(job_id)
    if not job: abort(404)
    return jsonify({"status": job["status"], "done": job["done"],
                    "total": job["total"], "log": job["log"][-20:],
                    "link_col": job.get("link_col")})


@app.route("/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job or not job.get("output"): abort(404)
    return send_file(job["output"], as_attachment=True,
                     download_name="transcripts_output.csv",
                     mimetype="text/csv")


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
    print(f"  Hello {GREETING_NAME}! Open the URL above in your browser if it didn't open automatically.\n")
    open_browser(url)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
