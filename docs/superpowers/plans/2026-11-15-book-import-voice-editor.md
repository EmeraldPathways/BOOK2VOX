# BOOK2VOX import and voice editor plan

## Goal

Add DOCX/MOBI import and a simple visual MP3 range selector for Chatterbox voice profiles, then verify and publish the frontend.

## Architecture

FastAPI owns parsing, FFmpeg clipping, profile metadata, and validation. Next.js owns the waveform and selection controls. Calibre is an explicit Windows dependency for MOBI conversion; Vercel hosts only the frontend.

## Tech Stack

Python 3.11+, FastAPI, `python-docx`, EbookLib, PyMuPDF, Calibre, FFmpeg; Next.js/React, browser Web Audio API and Canvas.

## Spec

1. Add failing API tests for DOCX/MOBI extraction and voice range metadata.
2. Implement parsers, Calibre conversion, source retention, and selected-range clipping.
3. Add the browser range editor and connect its values to the voice upload form.
4. Update API-origin configuration and operator setup documentation.
5. Run backend tests, frontend tests/build, live health/import checks, then commit and push the feature branch and deploy the frontend.

## Global Constraints

- Preserve existing APIs and local-first behavior.
- Do not commit generated audio, runtime storage, secrets, or generated Next.js config changes.
- Keep the original uploaded voice file; only the derived reference is used for synthesis.
- Never bypass DRM or claim that Chatterbox is installed unless the runtime check proves it.

## Review Focus

Validate file-extension handling, subprocess timeouts and error messages, range bounds, CORS/API configuration, and the Vercel frontend/backend boundary.

## Task 1: API tests first

- Add in-memory DOCX fixture and MOBI converter tests.
- Add an FFmpeg-backed voice-range test proving the source is retained.
- Run the focused tests and confirm they fail for the missing behavior.

## Task 2: Import implementation

- Add `python-docx` and DOCX chapter extraction.
- Add Calibre detection/conversion for MOBI and reuse EPUB extraction.
- Update accepted upload extensions and errors.

## Task 3: Voice range implementation

- Accept `start_seconds`/`end_seconds` form fields.
- Validate source and selection durations, clip to mono 24 kHz WAV, and persist source/profile metadata.

## Task 4: Frontend editor

- Add a canvas waveform with dual range controls and selection playback.
- Send selected times when saving a voice and add DOCX/MOBI to the library picker.
- Read the API URL from `NEXT_PUBLIC_API_URL`.

## Task 5: Verification and publishing

- Run all backend/frontend checks and a live FastAPI smoke test.
- Restore generated Next.js files, inspect the diff, commit only task files, push the feature branch, and deploy/inspect the Vercel frontend.
