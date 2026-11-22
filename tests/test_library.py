"""Book library management and chapter editing tests."""

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import main


def make_book(tmp_path):
    book_id = "a" * 32
    book_dir = tmp_path / book_id
    book_dir.mkdir()
    (book_dir / "book.json").write_text(
        json.dumps({"title": "Original title", "chapters": [{"index": 0, "title": "Chapter 1", "characters": 12}]}),
        encoding="utf-8",
    )
    (book_dir / "chapters.json").write_text(
        json.dumps([{"title": "Chapter 1", "text": "Original text."}]),
        encoding="utf-8",
    )
    return book_id, book_dir


def test_rename_book_updates_library_record(tmp_path, monkeypatch):
    book_id, _ = make_book(tmp_path)
    monkeypatch.setattr(main, "STORE", tmp_path)

    result = main.rename_book(book_id, main.BookUpdate(title="Renamed book"))

    assert result["title"] == "Renamed book"
    assert main.load_book(book_id)["title"] == "Renamed book"


def test_update_chapter_persists_text_title_and_character_count(tmp_path, monkeypatch):
    book_id, _ = make_book(tmp_path)
    monkeypatch.setattr(main, "STORE", tmp_path)

    result = main.update_chapter(book_id, 0, main.ChapterUpdate(title="Corrected chapter", text="Fixed wording."))

    assert result == {"index": 0, "title": "Corrected chapter", "text": "Fixed wording."}
    assert main.load_book(book_id)["chapters"][0]["characters"] == len("Fixed wording.")


def test_delete_book_removes_library_storage(tmp_path, monkeypatch):
    book_id, book_dir = make_book(tmp_path)
    monkeypatch.setattr(main, "STORE", tmp_path)

    assert main.delete_book(book_id) == {"deleted": True, "id": book_id}
    assert not book_dir.exists()
    with pytest.raises(HTTPException) as error:
        main.book_path(book_id)
    assert error.value.status_code == 404
