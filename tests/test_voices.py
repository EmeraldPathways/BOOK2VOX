"""Selected voice-reference clipping tests."""

import asyncio
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from fastapi import UploadFile

from app import voices


def make_wav(seconds: int = 8, channels: int = 1, sample_rate: int = 24000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\0\0" * channels * sample_rate * seconds)
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


def test_voice_profile_allows_source_over_15mb_for_selected_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES", tmp_path / "voices")
    source = make_wav(seconds=90, channels=2, sample_rate=44100)
    assert len(source) > 15 * 1024 * 1024
    upload = UploadFile(file=io.BytesIO(source), filename="large-source.wav")

    profile = asyncio.run(voices.create("Large source", True, upload, 10, 25))

    assert profile["sample_seconds"] == 15.0
    assert profile["selection_start"] == 10.0
    assert profile["selection_end"] == 25.0


def test_voice_profile_allows_long_source_for_selected_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "VOICES", tmp_path / "voices")
    source = make_wav(seconds=201)
    upload = UploadFile(file=io.BytesIO(source), filename="long-source.wav")

    profile = asyncio.run(voices.create("Long source", True, upload, 100, 115))

    assert profile["source_seconds"] == 201.0
    assert profile["sample_seconds"] == 15.0
