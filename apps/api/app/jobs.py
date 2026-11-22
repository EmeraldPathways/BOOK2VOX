"""Persistent local generation jobs. One GPU worker; resumable segment output."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field

WAKE = threading.Event()
GPU_LOCK = threading.Lock()


def _core():
    """Load the API module only after both modules can finish importing."""
    from . import main

    return main


def connect():
    db = sqlite3.connect(_core().STORE / "jobs.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL, chapter INTEGER NOT NULL,
            status TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0, error TEXT,
            exaggeration REAL NOT NULL, cfg_weight REAL NOT NULL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            speed REAL NOT NULL DEFAULT 1.0
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        if "voice_id" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN voice_id TEXT")
        if "speed" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN speed REAL NOT NULL DEFAULT 1.0")
        db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
    WAKE.set()
    threading.Thread(target=run_worker, daemon=True, name="book2vox-gpu-worker").start()

def segment(text: str, limit: int = 450) -> list[str]:
    # Prefer sentence boundaries; split long sentences at whitespace, never drop text.
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    output: list[str] = []
    current = ""
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        for word in words:
            if len(word) > limit:
                if current:
                    output.append(current)
                    current = ""
                output.extend(word[i:i+limit] for i in range(0, len(word), limit))
                continue
            if current and len(current) + len(word) + 1 > limit:
                output.append(current)
                current = ""
            current = (current + " " + word).strip()
    if current:
        output.append(current)
    return output

class JobRequest(BaseModel):
    book_id: str
    chapter: int = Field(ge=0)
    exaggeration: float = Field(default=0.5, ge=0, le=1)
    cfg_weight: float = Field(default=0.5, ge=0, le=1)
    voice_id: str | None = None
    speed: float = Field(default=1.0, ge=0.75, le=1.25)

def get_job(job_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return dict(row)

def create(req: JobRequest):
    path = _core().book_path(req.book_id)
    chapters = json.loads((path / "chapters.json").read_text(encoding="utf-8"))
    if req.chapter >= len(chapters):
        raise HTTPException(404, "Chapter not found")
    if req.voice_id:
        from .voices import reference_path
        reference_path(req.voice_id)
    total = len(segment(chapters[req.chapter]["text"]))
    if not total:
        raise HTTPException(422, "Chapter is empty")
    job_id = uuid.uuid4().hex
    now = time.time()
    with connect() as db:
        db.execute("INSERT INTO jobs (id,book_id,chapter,status,completed,total,error,exaggeration,cfg_weight,created_at,updated_at,voice_id,speed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, req.book_id, req.chapter, "queued", 0, total, None, req.exaggeration, req.cfg_weight, now, now, req.voice_id, req.speed))
    WAKE.set()
    return get_job(job_id)

def cancel(job_id: str):
    job = get_job(job_id)
    if job["status"] in ("queued", "running"):
        with connect() as db:
            db.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE id=?", (time.time(), job_id))
    return get_job(job_id)

def retry(job_id: str):
    job = get_job(job_id)
    if job["status"] not in ("failed", "cancelled"):
        raise HTTPException(409, "Only failed or cancelled jobs can be retried")
    with connect() as db:
        db.execute("UPDATE jobs SET status='queued', error=NULL, updated_at=? WHERE id=?", (time.time(), job_id))
    WAKE.set()
    return get_job(job_id)

def run_worker():
    while True:
        try:
            with connect() as db:
                row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (time.time(), row["id"]))
            if not row:
                WAKE.wait(timeout=3)
                WAKE.clear()
                continue
            job = dict(row)
            try:
                process(job)
            except Exception as exc:
                with connect() as db:
                    db.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=? AND status='running'",
                        (str(exc)[:1000], time.time(), job["id"]))
        except Exception:
            time.sleep(2)

def process(job):
    book_dir = _core().book_path(job["book_id"])
    chapters = json.loads((book_dir / "chapters.json").read_text(encoding="utf-8"))
    parts = segment(chapters[job["chapter"]]["text"])
    folder = book_dir / "jobs" / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    for index, text in enumerate(parts):
        if get_job(job["id"])["status"] != "running":
            return
        target = folder / f"{index:05}.wav"
        if not target.exists():
            tmp = folder / f"{index:05}.tmp.wav"
            with GPU_LOCK:
                _core().synthesize(text, tmp, job["exaggeration"], job["cfg_weight"], job.get("voice_id"), job.get("speed", 1.0))
            tmp.replace(target)
        with connect() as db:
            db.execute("UPDATE jobs SET completed=?, updated_at=? WHERE id=? AND status='running'",
                (index + 1, time.time(), job["id"]))
    if get_job(job["id"])["status"] != "running":
        return
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required for MP3 export. Install FFmpeg and add it to PATH.")
    # FFmpeg concat demuxer accepts an explicit file list; files are generated by us.
    listing = folder / "concat.txt"
    listing.write_text("".join(f"file '{i:05}.wav'\n" for i in range(len(parts))), encoding="utf-8")
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "1", "-i", str(listing),
        "-codec:a", "pcm_s16le", str(folder / "chapter.wav")],
        cwd=folder, check=True, timeout=3600)
    output = folder / "chapter.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "1", "-i", str(listing),
        "-af", "loudnorm=I=-18:TP=-2:LRA=11", "-codec:a", "libmp3lame",
        "-b:a", "128k", str(output)], cwd=folder, check=True, timeout=3600)
    with connect() as db:
        db.execute("UPDATE jobs SET status='completed', updated_at=? WHERE id=? AND status='running'",
            (time.time(), job["id"]))

def audio_path(job_id: str) -> Path:
    job = get_job(job_id)
    if job["status"] != "completed":
        raise HTTPException(409, "Audio is not ready")
    path = _core().book_path(job["book_id"]) / "jobs" / job_id / "chapter.mp3"
    if not path.exists():
        raise HTTPException(404, "Audio missing")
    return path

def audio_wav_path(job_id: str) -> Path:
    job = get_job(job_id)
    if job["status"] != "completed":
        raise HTTPException(409, "Audio is not ready")
    path = _core().book_path(job["book_id"]) / "jobs" / job_id / "chapter.wav"
    if not path.exists():
        raise HTTPException(404, "WAV audio missing")
    return path
