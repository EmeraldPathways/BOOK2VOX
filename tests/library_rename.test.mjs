import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../apps/web/src/app/page.tsx", import.meta.url), "utf8");

test("book rename uses an in-page editor instead of window.prompt", () => {
  assert.doesNotMatch(page, /window\.prompt\(/);
  assert.match(page, /aria-label="Rename book title"/);
});
