import test from "node:test";
import assert from "node:assert/strict";

import { audioDuration, normalizeSelection } from "../apps/web/src/app/audio-range.js";

test("uses the decoded audio duration to enable a selectable range", () => {
  const duration = audioDuration({ duration: 2019 });
  const selection = normalizeSelection(duration, 0, 30);

  assert.equal(duration, 2019);
  assert.equal(selection.ready, true);
  assert.equal(selection.start, 0);
  assert.equal(selection.end, 30);
  assert.equal(selection.startMax, 2016);
});

test("keeps the selected range within the recording when the start moves", () => {
  const selection = normalizeSelection(10, 8, 30);

  assert.equal(selection.start, 7);
  assert.equal(selection.end, 10);
  assert.equal(selection.endMin, 10);
  assert.equal(selection.endMax, 10);
});
