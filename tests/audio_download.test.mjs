import test from "node:test";
import assert from "node:assert/strict";

import { audioDownloadName, audioDownloadLabel } from "../apps/web/src/app/audio.js";

test("chapter audio uses the MP3 download name", () => {
  assert.equal(audioDownloadName("mp3"), "book2vox-chapter.mp3");
  assert.equal(audioDownloadLabel("mp3"), "Download MP3");
});

test("preview audio keeps the WAV download name", () => {
  assert.equal(audioDownloadName("wav"), "book2vox-preview.wav");
  assert.equal(audioDownloadLabel("wav"), "Download WAV");
});

test("chapter audio uses the chapter WAV download name", () => {
  assert.equal(audioDownloadName("wav", "chapter"), "book2vox-chapter.wav");
});
