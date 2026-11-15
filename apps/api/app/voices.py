"""Local, permission-based reference voice library."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .main import STORE

VOICES = STORE / "voices"
VOICES.mkdir(parents=True, exist_ok=True)
MAX_SOURCE_BYTES = 30 * 1024 * 1024

def voice_dir(voice_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", voice_id):
        raise HTTPException(400, "Invalid voice ID")
    folder = VOICES / voice_id
    if not (folder / "profile.json").is_file():
        raise HTTPException(404, "Voice not found")
    return folder

def get(voice_id: str) -> dict:
    return json.loads((voice_dir(voice_id) / "profile.json").read_text(encoding="utf-8"))

def list_voices() -> list[dict]:
    return sorted(
        [json.loads(p.read_text(encoding="utf-8")) for p in VOICES.glob("*/profile.json")],
        key=lambda x: x["name"].lower(),
    )

async def create(name: str, consent: bool, file: UploadFile, start_seconds: float = 0.0, end_seconds: float | None = None):
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(422, "Voice name must be 1–80 characters")
    if not consent:
        raise HTTPException(422, "Confirm you own this voice or have permission to clone it")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        raise HTTPException(415, "Upload WAV, MP3, M4A, FLAC or OGG audio")
    data = await file.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise HTTPException(413, "Source voice recording exceeds 30 MB")
    if not math.isfinite(start_seconds) or (end_seconds is not None and not math.isfinite(end_seconds)):
        raise HTTPException(422, "Voice selection times must be finite numbers")
    if start_seconds < 0 or (end_seconds is not None and end_seconds <= start_seconds):
        raise HTTPException(422, "Voice selection range is invalid")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(503, "FFmpeg and FFprobe must be installed")
    voice_id = uuid.uuid4().hex
    folder = VOICES / voice_id
    folder.mkdir(parents=True)
    source = folder / ("source" + suffix)
    target = folder / "reference.wav"
    try:
        source.write_bytes(data)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        duration = float(probe.stdout.strip())
        if duration < 3:
            raise HTTPException(422, "Recording must be at least 3 seconds")
        selection_start = float(start_seconds)
        selection_end = min(duration, selection_start + 30) if end_seconds is None else float(end_seconds)
        selection_duration = selection_end - selection_start
        if selection_start >= duration or selection_end > duration or not 3 <= selection_duration <= 30:
            raise HTTPException(422, "Select between 3 and 30 seconds within the recording")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-ss", str(selection_start), "-t", str(selection_duration), "-vn", "-ac", "1", "-ar", "24000", str(target)],
            capture_output=True, timeout=45, check=True,
        )
        profile = {
            "id": voice_id,
            "name": name,
            "source_filename": file.filename or source.name,
            "source_seconds": round(duration, 1),
            "selection_start": round(selection_start, 1),
            "selection_end": round(selection_end, 1),
            "sample_seconds": round(selection_duration, 1),
            "permission_confirmed": True,
        }
        (folder / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        return profile
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except (ValueError, subprocess.SubprocessError, OSError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, f"Unable to process voice recording: {exc}") from exc

def reference_path(voice_id: str | None) -> str | None:
    if not voice_id:
        return None
    return str(voice_dir(voice_id) / "reference.wav")

def remove(voice_id: str):
    folder = voice_dir(voice_id)
    shutil.rmtree(folder)
    return {"deleted": voice_id}

def sample(voice_id: str):
    return FileResponse(voice_dir(voice_id) / "reference.wav", media_type="audio/wav")
