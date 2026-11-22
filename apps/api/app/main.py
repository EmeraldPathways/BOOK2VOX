from __future__ import annotations

import io
import json
import math
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import uuid
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import jobs as job_queue


@asynccontextmanager
async def lifespan(_: FastAPI):
    job_queue.init()
    yield


ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "storage"
STORE.mkdir(exist_ok=True)
MAX_UPLOAD = 30 * 1024 * 1024
app = FastAPI(title="BOOK2VOX API", version="0.1.0", lifespan=lifespan)
_default_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()] or _default_cors_origins
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"])

def book_path(book_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", book_id):
        raise HTTPException(400, "Invalid book ID")
    path = STORE / book_id
    if not (path / "book.json").exists():
        raise HTTPException(404, "Book not found")
    return path

def load_book(book_id: str) -> dict:
    return json.loads((book_path(book_id) / "book.json").read_text(encoding="utf-8"))

def split_text(text: str) -> list[dict]:
    chunks = re.split(r"(?im)^\s*(chapter\s+(?:\d+|[ivxlcdm]+)|part\s+\d+)\b[^\n]*$", text)
    if len(chunks) <= 1:
        return [{"title": "Chapter 1", "text": text.strip()}]
    out = []
    if chunks[0].strip():
        out.append({"title": "Introduction", "text": chunks[0].strip()})
    for i in range(1, len(chunks), 2):
        out.append({"title": chunks[i].strip(), "text": chunks[i + 1].strip()})
    return [x for x in out if x["text"]]

def _extract_docx(data: bytes) -> list[dict]:
    from docx import Document

    document = Document(io.BytesIO(data))
    chapters: list[dict] = []
    title = "Chapter 1"
    paragraphs: list[str] = []

    def flush() -> None:
        text = "\n".join(paragraphs).strip()
        if text:
            chapters.append({"title": title, "text": text})

    for paragraph in document.paragraphs:
        value = paragraph.text.strip()
        if not value:
            continue
        style = (paragraph.style.name or "").lower()
        if style.startswith("heading"):
            flush()
            title = value
            paragraphs = []
        else:
            paragraphs.append(value)
    flush()
    return chapters


def _extract_mobi(data: bytes) -> list[dict]:
    converter = shutil.which("ebook-convert")
    if not converter:
        raise HTTPException(503, "MOBI import requires Calibre's ebook-convert on PATH")
    with tempfile.TemporaryDirectory(prefix="book2vox-mobi-") as directory:
        source = Path(directory) / "book.mobi"
        converted = Path(directory) / "book.epub"
        source.write_bytes(data)
        try:
            subprocess.run(
                [converter, str(source), str(converted)],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(422, "MOBI conversion timed out; the file may be DRM-protected") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "conversion failed").strip().splitlines()[-1]
            raise HTTPException(422, f"Unable to convert MOBI: {detail}") from exc
        except OSError as exc:
            raise HTTPException(503, f"Unable to run Calibre's ebook-convert: {exc}") from exc
        if not converted.exists():
            raise HTTPException(422, "Calibre did not produce an EPUB from this MOBI file")
        try:
            return extract(converted.read_bytes(), ".epub")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, f"Unable to read converted MOBI: {exc}") from exc


def _epub_path(value: str) -> str:
    path = unquote(value.split("#", 1)[0]).replace("\\", "/")
    return posixpath.normpath(path).lstrip("/") if path else ""


def _epub_toc_titles(book: Any) -> dict[str, list[str]]:
    titles: dict[str, list[str]] = {}

    def visit(entry: Any) -> None:
        if isinstance(entry, (list, tuple)):
            for child in entry:
                visit(child)
            return
        href = getattr(entry, "href", None)
        title = " ".join(str(getattr(entry, "title", "")).split())
        path = _epub_path(str(href or ""))
        if not path or not title:
            return
        keys = [path]
        basename = posixpath.basename(path)
        if basename and basename != path:
            keys.append(basename)
        for key in keys:
            if title not in titles.setdefault(key, []):
                titles[key].append(title)

    visit(getattr(book, "toc", []))
    return titles


def _epub_item_toc_titles(item: Any, toc_titles: dict[str, list[str]]) -> list[str]:
    path = _epub_path(str(getattr(item, "file_name", "")))
    if not path:
        return []
    titles = list(toc_titles.get(path, []))
    basename = posixpath.basename(path)
    if basename != path:
        for title in toc_titles.get(basename, []):
            if title not in titles:
                titles.append(title)
    return titles


def _remove_epub_navigation(soup: BeautifulSoup, text: str) -> bool:
    links = soup.find_all("a", href=True)
    lowered = text.casefold()
    looks_like_navigation = len(links) >= 4 and (
        "table of contents" in lowered
        or re.search(r"(?im)^\s*contents\s*$", text)
        or (len(links) >= 10 and len(text) < 5000)
    )
    if not looks_like_navigation:
        return False

    blocks = []
    seen: set[int] = set()
    for link in links:
        block = link.find_parent(["li", "p", "blockquote"]) or link
        if id(block) not in seen:
            blocks.append(block)
            seen.add(id(block))
    for block in blocks:
        block.decompose()
    for tag in soup.find_all(["ul", "ol"]):
        if not tag.get_text(" ", strip=True):
            tag.decompose()
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4"]):
        if re.fullmatch(r"(?:table\s+of\s+)?contents", tag.get_text(" ", strip=True), re.IGNORECASE):
            tag.decompose()
    return True


def _epub_title(soup: BeautifulSoup, text: str, toc_titles: list[str], fallback: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for toc_title in toc_titles:
        if toc_title.isdigit():
            continue
        if any(line.casefold() == toc_title.casefold() or line.casefold().startswith(f"{toc_title.casefold()} ") for line in lines[:20]):
            return toc_title
    if lines and re.match(r"(?i)^(?:part|chapter|book|volume)\b", lines[0]):
        return lines[0]
    heading = soup.find(["h1", "h2", "h3"])
    if heading:
        title = heading.get_text(" ", strip=True)
        if title and title.casefold() not in {"unknown", "untitled"}:
            return title
    if toc_titles:
        return toc_titles[0]
    if lines and len(lines[0]) <= 120 and len(lines[0].split()) <= 14 and not re.search(r"[.!?]$", lines[0]):
        return lines[0]
    return fallback


def extract(data: bytes, suffix: str) -> list[dict]:
    suffix = suffix.lower()
    if suffix == ".txt":
        return split_text(data.decode("utf-8-sig"))
    if suffix == ".docx":
        return _extract_docx(data)
    if suffix == ".mobi":
        return _extract_mobi(data)
    if suffix == ".epub":
        book = epub.read_epub(io.BytesIO(data))
        items = {item.id: item for item in book.get_items() if item.get_type() == ITEM_DOCUMENT}
        toc_titles = _epub_toc_titles(book)
        chapters = []
        for entry in book.spine:
            item = items.get(entry[0])
            if item is None:
                continue
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for tag in soup(["script", "style", "nav", "title"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
            navigation_removed = _remove_epub_navigation(soup, text)
            if navigation_removed:
                text = soup.get_text("\n", strip=True)
            if len(text) >= 40:
                titles = _epub_item_toc_titles(item, toc_titles)
                chapters.append({"title": _epub_title(soup, text, titles, f"Section {len(chapters)+1}"), "text": text})
        return chapters
    if suffix == ".pdf":
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        return split_text(text)
    raise HTTPException(400, "Supported formats: EPUB, MOBI, DOCX, TXT or PDF")

@app.get("/health")
def health():
    return {"status": "ok", "lm_studio": os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1")}

@app.get("/books")
def books():
    return [{"id": p.name, **json.loads((p / "book.json").read_text(encoding="utf-8"))} for p in STORE.iterdir() if p.is_dir() and (p / "book.json").exists()]

@app.post("/books")
async def upload_book(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".epub", ".mobi", ".docx", ".txt", ".pdf"}:
        raise HTTPException(400, "Unsupported file type")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File exceeds 30 MB")
    try:
        chapters = extract(data, suffix)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Unable to parse book: {exc}") from exc
    if not chapters:
        raise HTTPException(422, "No readable text found; scanned PDFs require OCR")
    book_id = uuid.uuid4().hex
    path = STORE / book_id
    path.mkdir()
    record = {"title": Path(file.filename or "Untitled").stem, "chapters": [{"index": i, "title": c["title"], "characters": len(c["text"])} for i, c in enumerate(chapters)]}
    (path / "book.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (path / "chapters.json").write_text(json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
    return {"id": book_id, **record}

@app.get("/books/{book_id}")
def get_book(book_id: str):
    return {"id": book_id, **load_book(book_id)}

class BookUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

class ChapterUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)

@app.patch("/books/{book_id}")
def rename_book(book_id: str, request: BookUpdate):
    path = book_path(book_id)
    title = request.title.strip()
    if not title:
        raise HTTPException(422, "Book title cannot be empty")
    record = load_book(book_id)
    record["title"] = title
    (path / "book.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return {"id": book_id, **record}

@app.delete("/books/{book_id}")
def delete_book(book_id: str):
    path = book_path(book_id)
    shutil.rmtree(path)
    return {"deleted": True, "id": book_id}

@app.get("/books/{book_id}/chapters/{index}")
def get_chapter(book_id: str, index: int):
    chapters = json.loads((book_path(book_id) / "chapters.json").read_text(encoding="utf-8"))
    if index < 0 or index >= len(chapters):
        raise HTTPException(404, "Chapter not found")
    return chapters[index]

@app.put("/books/{book_id}/chapters/{index}")
def update_chapter(book_id: str, index: int, request: ChapterUpdate):
    path = book_path(book_id)
    chapters_path = path / "chapters.json"
    chapters = json.loads(chapters_path.read_text(encoding="utf-8"))
    if index < 0 or index >= len(chapters):
        raise HTTPException(404, "Chapter not found")
    title = request.title.strip()
    text = request.text.strip()
    if not title or not text:
        raise HTTPException(422, "Chapter title and text cannot be empty")
    chapter = {"title": title, "text": text}
    chapters[index] = chapter
    chapters_path.write_text(json.dumps(chapters, ensure_ascii=False), encoding="utf-8")
    record = load_book(book_id)
    record["chapters"][index] = {"index": index, "title": title, "characters": len(text)}
    (path / "book.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return {"index": index, **chapter}

class PreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    exaggeration: float = Field(default=0.5, ge=0, le=1)
    cfg_weight: float = Field(default=0.5, ge=0, le=1)
    voice_id: str | None = None
    speed: float = Field(default=1.0, ge=0.75, le=1.25)

_model: Any = None

def _validate_speed(speed: float) -> float:
    if not math.isfinite(speed) or not 0.75 <= speed <= 1.25:
        raise HTTPException(422, "Talking speed must be between 0.75x and 1.25x")
    return speed

def export_mp3(source: Path, output: Path):
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg is required for MP3 export. Install FFmpeg and add it to PATH.")
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-codec:a", "libmp3lame", "-b:a", "128k", str(output)],
            cwd=source.parent, check=True, timeout=3600,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(422, f"Unable to export MP3: {exc}") from exc

def synthesize(text: str, output: Path, exaggeration: float, cfg_weight: float, voice_id: str | None = None, speed: float = 1.0):
    global _model
    speed = _validate_speed(speed)
    try:
        import torch
        import torchaudio
        from chatterbox.tts import ChatterboxTTS
    except ImportError as exc:
        raise HTTPException(503, "Install CUDA PyTorch, torchaudio and chatterbox-tts to enable narration") from exc
    if _model is None:
        _model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
    if voice_id:
        kwargs["audio_prompt_path"] = voice_library.reference_path(voice_id)
    audio = _model.generate(text, **kwargs)
    if speed == 1.0:
        torchaudio.save(str(output), audio.cpu(), _model.sr)
        return
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg must be installed to adjust talking speed")
    source = output.with_name(f".{output.stem}-{uuid.uuid4().hex}.wav")
    try:
        torchaudio.save(str(source), audio.cpu(), _model.sr)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-filter:a", f"atempo={speed:.3f}", "-c:a", "pcm_s16le", str(output)],
            capture_output=True, timeout=45, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(422, f"Unable to adjust talking speed: {exc}") from exc
    finally:
        source.unlink(missing_ok=True)

@app.post("/previews")
def preview(req: PreviewRequest):
    path = STORE / f"preview-{uuid.uuid4().hex}.wav"
    direction = narration_direction(req.text)
    exaggeration, cfg_weight = apply_narration_direction(req.exaggeration, req.cfg_weight, direction)
    synthesize(req.text, path, exaggeration, cfg_weight, req.voice_id, req.speed)
    return FileResponse(path, media_type="audio/wav", filename="book2vox-preview.wav")

class AnalyseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

class NarrationDirection(BaseModel):
    guidance: str = ""
    mood: str = "neutral"
    exaggeration: float | None = Field(default=None, ge=0, le=1)
    cfg_weight: float | None = Field(default=None, ge=0, le=1)

def _select_lm_model(available: list[dict]) -> str:
    preferred = os.getenv("LM_STUDIO_MODEL", "qwen/qwen3.5-9b")
    ids = [str(item.get("id", "")) for item in available]
    if preferred in ids:
        return preferred
    for model_id in ids:
        if "embed" not in model_id.lower():
            return model_id
    raise RuntimeError("Load a chat model in LM Studio")

def _control_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(1.0, number)), 3)

def _parse_narration_direction(content: str) -> NarrationDirection:
    text = content.strip()
    payload: dict[str, Any] | None = None
    try:
        decoded = json.loads(text)
        if isinstance(decoded, dict):
            payload = decoded
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                decoded = json.loads(match.group(0))
                if isinstance(decoded, dict):
                    payload = decoded
            except json.JSONDecodeError:
                pass
    if payload is None:
        return NarrationDirection(guidance=text)
    return NarrationDirection(
        guidance=str(payload.get("guidance") or payload.get("direction") or text).strip(),
        mood=str(payload.get("mood") or "neutral").strip(),
        exaggeration=_control_value(payload.get("exaggeration")),
        cfg_weight=_control_value(payload.get("cfg_weight")),
    )

def narration_direction(text: str, strict: bool = False) -> NarrationDirection | None:
    base = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1").rstrip("/")
    try:
        with httpx.Client(timeout=90) as client:
            models = client.get(f"{base}/models")
            models.raise_for_status()
            available = models.json().get("data", [])
            model = _select_lm_model(available)
            response = client.post(f"{base}/chat/completions", json={
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": "You are an audiobook narration director. Analyze the passage and return JSON only with these keys: guidance (one concise actionable sentence), mood (one word), exaggeration (number from 0 to 1), cfg_weight (number from 0 to 1). Do not rewrite or repeat the passage."},
                    {"role": "user", "content": text[:4000]},
                ],
            })
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_narration_direction(str(content))
    except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        if strict:
            raise HTTPException(503, f"LM Studio unavailable: {exc}") from exc
        return None

def apply_narration_direction(exaggeration: float, cfg_weight: float, direction: NarrationDirection | None) -> tuple[float, float]:
    if direction is None:
        return exaggeration, cfg_weight
    blend = 0.35
    guided_exaggeration = exaggeration if direction.exaggeration is None else exaggeration + (direction.exaggeration - exaggeration) * blend
    guided_cfg_weight = cfg_weight if direction.cfg_weight is None else cfg_weight + (direction.cfg_weight - cfg_weight) * blend
    return round(guided_exaggeration, 3), round(guided_cfg_weight, 3)

@app.post("/narration/analyse")
def analyse(req: AnalyseRequest):
    return narration_direction(req.text, strict=True).model_dump()

@app.post("/books/{book_id}/chapters/{index}/generate")
def generate_chapter(book_id: str, index: int, exaggeration: float = 0.5, cfg_weight: float = 0.5, voice_id: str | None = None, speed: float = 1.0):
    chapters = json.loads((book_path(book_id) / "chapters.json").read_text(encoding="utf-8"))
    if index < 0 or index >= len(chapters):
        raise HTTPException(404, "Chapter not found")
    if not (0 <= exaggeration <= 1 and 0 <= cfg_weight <= 1):
        raise HTTPException(422, "Controls must be between 0 and 1")
    _validate_speed(speed)
    if voice_id:
        voice_library.reference_path(voice_id)
    # Keep this synchronous route as a limited preview; full chapters use /jobs.
    text = chapters[index]["text"][:1200]
    output = book_path(book_id) / f"chapter-{index}.wav"
    mp3_output = book_path(book_id) / f"chapter-{index}.mp3"
    direction = narration_direction(text)
    exaggeration, cfg_weight = apply_narration_direction(exaggeration, cfg_weight, direction)
    synthesize(text, output, exaggeration, cfg_weight, voice_id, speed)
    export_mp3(output, mp3_output)
    return {
        "chapter": index,
        "generated_characters": len(text),
        "partial": len(chapters[index]["text"]) > 1200,
        "audio_url": f"/books/{book_id}/chapters/{index}/audio",
        "audio_mp3_url": f"/books/{book_id}/chapters/{index}/audio.mp3",
    }

@app.get("/books/{book_id}/chapters/{index}/audio.mp3")
def chapter_audio_mp3(book_id: str, index: int):
    path = book_path(book_id) / f"chapter-{index}.mp3"
    if not path.exists():
        raise HTTPException(404, "MP3 audio not generated")
    return FileResponse(path, media_type="audio/mpeg", filename=f"chapter-{index}.mp3")

@app.get("/books/{book_id}/chapters/{index}/audio")
def chapter_audio(book_id: str, index: int):
    path = book_path(book_id) / f"chapter-{index}.wav"
    if not path.exists():
        raise HTTPException(404, "Audio not generated")
    return FileResponse(path, media_type="audio/wav", filename=f"chapter-{index}.wav")

@app.post("/jobs", status_code=202)
def create_job(request: job_queue.JobRequest):
    return job_queue.create(request)

@app.get("/jobs/{job_id}")
def get_generation_job(job_id: str):
    return job_queue.get_job(job_id)

@app.post("/jobs/{job_id}/cancel")
def cancel_generation_job(job_id: str):
    return job_queue.cancel(job_id)

@app.post("/jobs/{job_id}/retry")
def retry_generation_job(job_id: str):
    return job_queue.retry(job_id)

@app.get("/jobs/{job_id}/audio")
def download_generated_audio(job_id: str):
    return FileResponse(job_queue.audio_path(job_id), media_type="audio/mpeg", filename="book2vox-chapter.mp3")

@app.get("/jobs/{job_id}/audio-wav")
def download_generated_audio_wav(job_id: str):
    return FileResponse(job_queue.audio_wav_path(job_id), media_type="audio/wav", filename="book2vox-chapter.wav")

@app.get("/books/{book_id}/jobs")
def list_book_jobs(book_id: str):
    book_path(book_id)
    with job_queue.connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM jobs WHERE book_id=? ORDER BY created_at DESC", (book_id,)).fetchall()]

from . import voices as voice_library

@app.get("/voices")
def list_saved_voices():
    return voice_library.list_voices()

@app.post("/voices", status_code=201)
async def add_voice(
    name: str = Form(...),
    consent: bool = Form(...),
    start_seconds: float = Form(0),
    end_seconds: float | None = Form(None),
    file: UploadFile = File(...),
):
    return await voice_library.create(name, consent, file, start_seconds, end_seconds)

@app.get("/voices/{voice_id}/sample")
def play_voice_sample(voice_id: str):
    return voice_library.sample(voice_id)

@app.delete("/voices/{voice_id}")
def delete_saved_voice(voice_id: str):
    return voice_library.remove(voice_id)
