"""Selected voice-reference clipping tests."""

import asyncio
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from fastapi import UploadFile

from app import voices


def make_wav(seconds: int = 8) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 24000 * seconds)
    return output.getvalue()


def test_voice_profile_clips_selected_range_and_keeps_source(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES", tmp_path / "voices")
    upload = UploadFile(file=io.BytesIO(make_wav()), filename="original.wav")

    profile = asyncio.run(voices.create("Narrator", True, upload, 1.5, 5.5))

    folder = tmp_path / "voices" / profile["id"]
    assert profile["source_filename"] == "original.wav"
    assert profile["selection_start"] == 1.5
    assert profile["selection_end"] == 5.5
    assert profile["sample_seconds"] == 4.0
    assert (folder / "source.wav").exists()
    assert (folder / "reference.wav").exists()
    assert voices.reference_path(profile["id"]) == str(folder / "reference.wav")
