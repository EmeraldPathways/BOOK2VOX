# BOOK2VOX import and voice-selection design

## Goal

Let users import `.docx` and `.mobi` books, and create a Chatterbox voice profile from a selected time range of an uploaded audio file without losing the original recording.

## Decisions

- DOCX extraction uses `python-docx`, grouping Heading 1/2/3 sections and falling back to Chapter 1 when no headings exist.
- MOBI extraction delegates conversion to Calibre's `ebook-convert` executable, then reuses the existing EPUB parser. DRM-protected files are reported as conversion failures.
- Voice uploads retain the original source file and create a mono 24 kHz `reference.wav` from a validated 3–30 second range.
- The frontend uses a dependency-free canvas waveform, dual range controls, and a selection preview. The backend remains authoritative for clipping and validation.
- Vercel hosts the Next.js frontend only. Chatterbox, FFmpeg, storage, and the generation worker remain on the user's Windows NVIDIA machine or another reachable GPU backend.

## Success criteria

- DOCX and MOBI import paths return readable chapter records.
- Voice metadata records the selected range and the source file remains available.
- Browser users can preview and save a selected range as a voice profile.
- Existing preview, LM Studio guidance, full-chapter MP3, and download flows continue to pass their tests.
