import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { findLicenseFile } from "./add-remote-skill.ts";

function fixture(t: TestContext) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "add-remote-skill-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test("findLicenseFile returns the canonical LICENSE name", (t) => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, "LICENSE"), "Apache-2.0");
  assert.strictEqual(findLicenseFile(root), "LICENSE");
});

test("findLicenseFile accepts LICENSE.md and LICENSE.txt", (t) => {
  for (const name of ["LICENSE.md", "LICENSE.txt"]) {
    const root = fixture(t);
    fs.writeFileSync(path.join(root, name), "text");
    assert.strictEqual(findLicenseFile(root), name);
  }
});

test("findLicenseFile falls back to case-insensitive matching", (t) => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, "license.txt"), "text");
  assert.strictEqual(findLicenseFile(root), "license.txt");
});

test("findLicenseFile accepts COPYING variants", (t) => {
  for (const name of ["COPYING", "COPYING.md", "COPYING.txt"]) {
    const root = fixture(t);
    fs.writeFileSync(path.join(root, name), "text");
    assert.strictEqual(findLicenseFile(root), name);
  }
});

test("findLicenseFile returns undefined when no license file is present", (t) => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, "SKILL.md"), "name: x");
  assert.strictEqual(findLicenseFile(root), undefined);
});

test("findLicenseFile ignores directories named like licenses", (t) => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, "LICENSE"), { recursive: true });
  assert.strictEqual(findLicenseFile(root), undefined);
});