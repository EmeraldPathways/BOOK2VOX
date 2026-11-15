"""The quick chapter path must honour the selected reference voice."""

import json
import sys
from pathlib import Path

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
    monkeypatch.setattr(main.voice_library, "reference_path", lambda selected: "reference.wav")

    calls = []

    def fake_synthesize(text, output, exaggeration, cfg_weight, selected_voice_id=None, speed=1.0):
        calls.append((text, exaggeration, cfg_weight, selected_voice_id, speed))

    monkeypatch.setattr(main, "synthesize", fake_synthesize)

    main.generate_chapter(book_id, 0, exaggeration=0.7, voice_id=voice_id, speed=1.15)

    assert calls == [("A short chapter.", 0.7, 0.5, voice_id, 1.15)]
