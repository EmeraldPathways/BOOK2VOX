# BOOK2VOX

Local-first, cloud-ready audiobook generator with expressive narration.

## MVP
- Upload EPUB, TXT, or text-based PDF
- Extract and review chapters
- Preview and generate narration on NVIDIA CUDA using Chatterbox
- Optional LM Studio narration analysis (never rewrites source text)
- Download WAV previews and chapter audio

## Requirements
Windows 10/11, Python 3.11, Node.js LTS, FFmpeg, NVIDIA driver and CUDA-compatible PyTorch. Install the CUDA build of PyTorch from https://pytorch.org/get-started/locally/ before installing Chatterbox.

## Start API (PowerShell)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt
uvicorn app.main:app --app-dir apps/api --reload --port 8000
```

## Start frontend (second terminal)
```powershell
cd apps/web
npm install
npm run dev
```
Open http://localhost:3000. API runs at http://127.0.0.1:8000.

For voice generation, install `chatterbox-tts` in the API environment after CUDA PyTorch. The first synthesis downloads model weights. Preview and chapter generation run synchronously in this initial prototype; long-running background jobs and cloud connectivity are subsequent milestones.

## LM Studio
Enable LM Studio's local API server on http://127.0.0.1:1234 and load a chat model. The optional `/narration/analyse` endpoint returns structured direction; it does not change the book text.

## Safety
Use only books you are entitled to process. No DRM circumvention. Uploaded books and generated audio remain in local `storage/` (gitignored). The API binds to loopback by default; do not expose it publicly without authentication.
