import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import { validateLicense, validateLicensePath } from "./marketplace-generator-utils.ts";

function fixture(t: TestContext) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "skill-marketplace-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

// validateLicensePath resolves `license_path` relative to
// `<skillsDir>/<itemId>/`, so each test creates the item's own directory.
function skillDir(root: string, itemId: string): string {
  const dir = path.join(root, itemId);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

test("validateLicensePath is a no-op when source is absent", (t) => {
  const root = fixture(t);
  // Should not throw.
  validateLicensePath({}, "x", root);
});

test("validateLicensePath is a no-op when license_path is absent", (t) => {
  const root = fixture(t);
  validateLicensePath(
    { metadata: { source: { repository: "https://example.com" } } },
    "x",
    root,
  );
});

test("validateLicensePath accepts an existing relative license_path", (t) => {
  const root = fixture(t);
  const dir = skillDir(root, "x");
  fs.writeFileSync(path.join(dir, "LICENSE"), "MIT");
  validateLicensePath(
    { metadata: { source: { license_path: "LICENSE" } } },
    "x",
    root,
  );
});

test("validateLicensePath rejects a missing license_path", (t) => {
  const root = fixture(t);
  skillDir(root, "x");
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "LICENSE.txt" } } },
        "x",
        root,
      ),
    /does not exist/,
  );
});

test("validateLicensePath rejects an absolute license_path", (t) => {
  const root = fixture(t);
  skillDir(root, "x");
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "/etc/passwd" } } },
        "x",
        root,
      ),
    /must be a relative path/,
  );
});

test("validateLicensePath rejects a path with .. segments", (t) => {
  const root = fixture(t);
  skillDir(root, "x");
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "../LICENSE" } } },
        "x",
        root,
      ),
    /must be a relative path/,
  );
});

test("validateLicensePath rejects a path with embedded newlines", (t) => {
  const root = fixture(t);
  skillDir(root, "x");
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "LICENSE\nfoo" } } },
        "x",
        root,
      ),
    /must be a relative path/,
  );
});

test("validateLicensePath rejects an empty license_path", (t) => {
  const root = fixture(t);
  skillDir(root, "x");
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "   " } } },
        "x",
        root,
      ),
    /must be a non-empty string/,
  );
});

test("validateLicensePath rejects a directory named like a license", (t) => {
  const root = fixture(t);
  const dir = skillDir(root, "x");
  fs.mkdirSync(path.join(dir, "LICENSE"), { recursive: true });
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "LICENSE" } } },
        "x",
        root,
      ),
    /does not exist/,
  );
});

test("validateLicensePath rejects a symlinked license_path that dangles", (t) => {
  const root = fixture(t);
  const dir = skillDir(root, "x");
  fs.symlinkSync(
    path.join(dir, "does-not-exist"),
    path.join(dir, "LICENSE"),
  );
  assert.throws(
    () =>
      validateLicensePath(
        { metadata: { source: { license_path: "LICENSE" } } },
        "x",
        root,
      ),
    /does not exist/,
  );
});

test("validateLicensePath accepts a valid symlinked license_path", (t) => {
  const root = fixture(t);
  const dir = skillDir(root, "x");
  fs.writeFileSync(path.join(dir, "LICENSE.real"), "MIT");
  fs.symlinkSync("LICENSE.real", path.join(dir, "LICENSE"));
  assert.doesNotThrow(() =>
    validateLicensePath(
      { metadata: { source: { license_path: "LICENSE" } } },
      "x",
      root,
    ),
  );
});

test("validateLicense accepts top-level license field", (t) => {
  assert.doesNotThrow(() =>
    validateLicense({ license: "MIT" }, "test"),
  );
});

test("validateLicense accepts metadata.source.license_path", (t) => {
  assert.doesNotThrow(() =>
    validateLicense({ metadata: { source: { license_path: "LICENSE" } } }, "test"),
  );
});

test("validateLicense rejects when both license and license_path are present", (t) => {
  assert.throws(
    () =>
      validateLicense(
        { license: "MIT", metadata: { source: { license_path: "LICENSE" } } },
        "test",
      ),
    /must not specify both/,
  );
});

test("validateLicense rejects when neither license nor license_path is present", (t) => {
  assert.throws(
    () => validateLicense({}, "test"),
    /must specify either/,
  );
});

test("validateLicense rejects empty license string", (t) => {
  assert.throws(
    () => validateLicense({ license: "   " }, "test"),
    /must specify either/,
  );
});

test("validateLicense rejects empty license_path string", (t) => {
  assert.throws(
    () =>
      validateLicense(
        { metadata: { source: { license_path: "   " } } },
        "test",
      ),
    /must specify either/,
  );
});

test("validateLicense rejects when metadata.source is absent", (t) => {
  assert.throws(
    () => validateLicense({ metadata: {} }, "test"),
    /must specify either/,
  );
});