"""The quick chapter path must honour the selected reference voice."""

import json
import shutil
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import main


def test_quick_chapter_passes_selected_voice_to_synthesis(tmp_path, monkeypatch):
    book_id = "d" * 32
    voice_id = "e" * 32
    book_dir = tmp_path / book_id
    book_dir.mkdir()
    (book_dir / "book.json").write_text(json.dumps({"title": "Test", "chapters": []}), encoding="utf-8")
    (book_dir / "chapters.json").write_text(json.dumps([{"title": "Chapter 1", "text": "A short chapter."}]), encoding="utf-8")
    monkeypatch.setattr(main, "STORE", tmp_path)
    monkeypatch.setattr(main, "narration_direction", lambda text: None, raising=False)
    monkeypatch.setattr(main.voice_library, "reference_path", lambda selected: "reference.wav")

    calls = []

    def fake_synthesize(text, output, exaggeration, cfg_weight, selected_voice_id=None, speed=1.0):
        calls.append((text, exaggeration, cfg_weight, selected_voice_id, speed))
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b"\0\0" * 24000)

    monkeypatch.setattr(main, "synthesize", fake_synthesize)

    main.generate_chapter(book_id, 0, exaggeration=0.7, voice_id=voice_id, speed=1.15)

    assert calls == [("A short chapter.", 0.7, 0.5, voice_id, 1.15)]


def test_quick_chapter_serializes_chatterbox_generation(tmp_path, monkeypatch):
    book_id = "a" * 32
    book_dir = tmp_path / book_id
    book_dir.mkdir()
    (book_dir / "book.json").write_text(json.dumps({"title": "Test", "chapters": []}), encoding="utf-8")
    (book_dir / "chapters.json").write_text(json.dumps([{"title": "Chapter 1", "text": "A short chapter."}]), encoding="utf-8")
    monkeypatch.setattr(main, "STORE", tmp_path)
    monkeypatch.setattr(main, "narration_direction", lambda text: None, raising=False)
    monkeypatch.setattr(main, "export_mp3", lambda source, output: output.write_bytes(b"mp3"))

    events = []

    class FakeLock:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, exc_type, exc, tb):
            events.append("exit")

    def fake_synthesize(text, output, exaggeration, cfg_weight, voice_id=None, speed=1.0):
        events.append("synthesize")
        output.write_bytes(b"wav")

    monkeypatch.setattr(main.job_queue, "GPU_LOCK", FakeLock())
    monkeypatch.setattr(main, "synthesize", fake_synthesize)

    main.generate_chapter(book_id, 0)

    assert events == ["enter", "synthesize", "exit"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required for MP3 export")
def test_quick_chapter_exports_wav_and_mp3(tmp_path, monkeypatch):
    book_id = "f" * 32
    book_dir = tmp_path / book_id
    book_dir.mkdir()
    (book_dir / "book.json").write_text(json.dumps({"title": "Test", "chapters": []}), encoding="utf-8")
    (book_dir / "chapters.json").write_text(json.dumps([{"title": "Chapter 1", "text": "A short chapter."}]), encoding="utf-8")
    monkeypatch.setattr(main, "STORE", tmp_path)
    monkeypatch.setattr(main, "narration_direction", lambda text: None, raising=False)

    def fake_synthesize(text, output, exaggeration, cfg_weight, selected_voice_id=None, speed=1.0):
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b"\0\0" * 24000)

    monkeypatch.setattr(main, "synthesize", fake_synthesize)

    result = main.generate_chapter(book_id, 0)

    assert result["audio_url"].endswith("/audio")
    assert result["audio_mp3_url"].endswith("/audio.mp3")
    assert (book_dir / "chapter-0.wav").is_file()
    assert (book_dir / "chapter-0.mp3").is_file()
