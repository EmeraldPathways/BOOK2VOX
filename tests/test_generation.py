"""Generation job tests that avoid loading the GPU TTS model."""

import json
import math
import shutil
import sys
import struct
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import jobs, main


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required for MP3 export")
def test_process_generates_every_segment_and_exports_mp3(tmp_path, monkeypatch):
    book_id = "a" * 32
    job_id = "b" * 32
    voice_id = "c" * 32
    book_dir = tmp_path / book_id
    book_dir.mkdir()
    chapter_text = " ".join(["A sentence for the narrator."] * 30)
    (book_dir / "book.json").write_text(
        json.dumps({"title": "Test", "chapters": [{"index": 0, "title": "Chapter 1", "characters": len(chapter_text)}]}),
        encoding="utf-8",
    )
    (book_dir / "chapters.json").write_text(json.dumps([{"title": "Chapter 1", "text": chapter_text}]), encoding="utf-8")
    monkeypatch.setattr(main, "STORE", tmp_path)

    with jobs.connect() as db:
        db.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY, book_id TEXT NOT NULL, chapter INTEGER NOT NULL,
                status TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0, error TEXT,
                exaggeration REAL NOT NULL, cfg_weight REAL NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL, voice_id TEXT
            )"""
        )
        parts = jobs.segment(chapter_text)
        db.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, book_id, 0, "running", 0, len(parts), None, 0.8, 0.4, 0, 0, voice_id),
        )

    calls = []

    def fake_synthesize(text, output, exaggeration, cfg_weight, selected_voice_id=None, speed=1.0):
        calls.append((text, exaggeration, cfg_weight, selected_voice_id, speed))
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / 24000))) for i in range(24000)))

    monkeypatch.setattr(main, "synthesize", fake_synthesize)

    jobs.process({"id": job_id, "book_id": book_id, "chapter": 0, "exaggeration": 0.8, "cfg_weight": 0.4, "voice_id": voice_id, "speed": 1.15})

    job = jobs.get_job(job_id)
    output = book_dir / "jobs" / job_id / "chapter.mp3"
    wav_output = book_dir / "jobs" / job_id / "chapter.wav"
    assert job["status"] == "completed"
    assert job["completed"] == len(parts)
    assert len(calls) == len(parts)
    assert all(call[3] == voice_id for call in calls)
    assert all(call[4] == 1.15 for call in calls)
    assert output.is_file()
    assert output.stat().st_size > 0
    assert wav_output.is_file()
    assert wav_output.stat().st_size > 0
    assert Path(main.download_generated_audio_wav(job_id).path) == wav_output


def test_job_request_persists_talking_speed(tmp_path, monkeypatch):
    book_id = "d" * 32
    book_dir = tmp_path / book_id
    book_dir.mkdir()
    (book_dir / "book.json").write_text(json.dumps({"title": "Test", "chapters": []}), encoding="utf-8")
    (book_dir / "chapters.json").write_text(json.dumps([{"title": "Chapter 1", "text": "A queued chapter."}]), encoding="utf-8")
    monkeypatch.setattr(main, "STORE", tmp_path)
    monkeypatch.setattr(jobs, "run_worker", lambda: None)
    jobs.init()

    request = jobs.JobRequest(book_id=book_id, chapter=0, speed=1.15)
    job = jobs.create(request)

    assert request.speed == 1.15
    assert job["speed"] == 1.15
