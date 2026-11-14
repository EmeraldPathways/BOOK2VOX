"""Run with: python -m pytest tests/test_segmentation.py (after API dependencies installed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.jobs import segment


def test_segments_cover_all_words():
    text = "The first sentence ends here. A second sentence follows! Finally, the ending."
    parts = segment(text, limit=35)
    assert parts
    assert " ".join(" ".join(parts).split()) == " ".join(text.split())
    assert all(len(part) <= 35 for part in parts)


def test_empty_text():
    assert segment("   ") == []


def test_very_long_token():
    parts = segment("x" * 1000, limit=450)
    assert "".join(parts) == "x" * 1000
    assert all(len(part) <= 450 for part in parts)
