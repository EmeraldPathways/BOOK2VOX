# BOOK2VOX

Local-first, cloud-ready audiobook generator with expressive narration.

## MVP
- Upload EPUB, MOBI, DOCX, TXT, or text-based PDF
- Extract and review chapters
- Preview and generate full-chapter MP3 narration on NVIDIA CUDA using Chatterbox
- Select a 3–30 second range from an MP3/WAV voice recording; the original is retained and the selected clip becomes the Chatterbox reference
- Optional LM Studio narration analysis (never rewrites source text)
- Download WAV previews and chapter audio

## Requirements
Windows 10/11, Python 3.11, Node.js LTS, FFmpeg, Calibre (for MOBI), an NVIDIA driver, and CUDA-compatible PyTorch. Install the CUDA build of PyTorch from https://pytorch.org/get-started/locally/ before installing Chatterbox.

## Start API (PowerShell)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt
# Install the CUDA PyTorch command selected at https://pytorch.org/get-started/locally/
pip install chatterbox-tts
uvicorn app.main:app --app-dir apps/api --reload --port 8000
```

Install Calibre on Windows and ensure its folder containing `ebook-convert.exe` is on `PATH`. MOBI conversion uses Calibre and does not bypass DRM. FFmpeg and FFprobe must also be on `PATH` for voice clipping and MP3 export.

## Start frontend (second terminal)
```powershell
cd apps/web
npm install
npm run dev
```
Open http://localhost:3000. API runs at http://127.0.0.1:8000.

The first Chatterbox synthesis downloads model weights. Full chapters run through the local background queue and export MP3 with FFmpeg. The API must remain running while a job is generating.

For a deployed frontend, copy `apps/web/.env.example` to `.env.local` for local work or set `NEXT_PUBLIC_API_URL` in Vercel to the public HTTPS URL of a separately hosted FastAPI backend. Set the backend's `CORS_ORIGINS` to the Vercel origin. Vercel hosts the Next.js frontend only; Chatterbox, CUDA, FFmpeg, local storage, and the generation worker cannot run inside this Vercel deployment.

## Voice profiles

Choose an MP3, WAV, M4A, FLAC, or OGG recording, then use the waveform and start/end sliders to select a clean 3–30 second passage. Preview the selection before saving. The uploaded source recording remains in the local voice folder for later re-editing; `reference.wav` is the derived mono 24 kHz clip passed to Chatterbox.

## LM Studio
Enable LM Studio's local API server on http://127.0.0.1:1234 and load an instruct model. For an RTX 3060, start with the current Qwen3 8B Instruct GGUF in Q4_K_M quantization if it is available in the LM Studio catalog; use a Qwen2.5 3B Instruct Q4_K_M model if memory is tight. Use an 8k–16k context, temperature around 0.2, and keep responses short (about 256 tokens) because the endpoint only needs mood, pacing, pause, and dialogue-delivery guidance.

The optional `/narration/analyse` endpoint uses LM Studio's OpenAI-compatible `/v1/models` and `/v1/chat/completions` endpoints. Start the server from LM Studio's Developer tab, load the model first, and leave the server on port 1234. It does not change the book text.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp
cd apps/web
npm test
npm run build
```

## Safety
Use only books you are entitled to process. No DRM circumvention. Uploaded books and generated audio remain in local `storage/` (gitignored). The API binds to loopback by default; do not expose it publicly without authentication.
