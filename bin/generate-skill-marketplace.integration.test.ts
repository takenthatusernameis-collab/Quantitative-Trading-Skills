import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test, type TestContext } from "node:test";
import * as yaml from "yaml";
import { generateMarketplace } from "./marketplace-generator-utils.ts";
import { validateLicensePath } from "./marketplace-generator-utils.ts";
import matter from "gray-matter";
import {
  validateRequirements,
  validateSuggestFor,
  isValidVscodeExtension,
} from "./marketplace-generator-utils.ts";

function fixture(t: TestContext) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "skill-marketplace-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function skillDir(root: string, itemId: string): string {
  const dir = path.join(root, itemId);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function writeSkill(
  root: string,
  id: string,
  frontmatter: Record<string, unknown>,
  body = "Skill content",
): void {
  const dir = skillDir(root, id);
  const skillMdPath = path.join(dir, "SKILL.md");
  const content = `---\n${yaml.stringify(frontmatter)}---\n\n${body}\n`;
  fs.writeFileSync(skillMdPath, content);
}

function createMcpsDir(root: string): string {
  const mcpsDir = path.join(root, "mcps");
  fs.mkdirSync(mcpsDir, { recursive: true });
  return mcpsDir;
}

interface SkillItem {
  id: string;
  description: string;
  category?: string;
  suggest_for?: unknown;
  requirements?: {
    skills?: string[];
    vscode_extensions?: Array<{ name: string; id: string }>;
    mcps?: string[];
  };
  githubUrl: string;
  rawUrl: string;
  content: string;
}

function generateSkillsMarketplace(skillsDir: string, mcpsDir: string) {
  const skillIds = new Set(
    fs
      .readdirSync(skillsDir, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !d.name.startsWith(".") && d.name !== "mcps")
      .map((d) => d.name),
  );
  const mcpIds = new Set<string>();

  // Load MCP IDs from mcpsDir
  if (fs.existsSync(mcpsDir)) {
    for (const dirName of fs.readdirSync(mcpsDir, { withFileTypes: true })) {
      if (dirName.isDirectory() && !dirName.name.startsWith(".")) {
        const mcpFile = path.join(mcpsDir, dirName.name, "MCP.yaml");
        if (fs.existsSync(mcpFile)) {
          const parsed = yaml.parse(fs.readFileSync(mcpFile, "utf-8")) as Record<string, unknown>;
          if (parsed.id && typeof parsed.id === "string") {
            mcpIds.add(parsed.id);
          }
        }
      }
    }
  }

  const items: SkillItem[] = [];
  const declaredNames = new Set<string>();

  for (const dirName of skillIds) {
    const skillMdPath = path.join(skillsDir, dirName, "SKILL.md");
    const { data } = matter(
      fs.readFileSync(skillMdPath, "utf-8"),
    );
    if (data.name !== dirName) {
      throw new Error(
        `${dirName}/SKILL.md: name must match directory (found "${data.name ?? "missing"}")`,
      );
    }
    if (declaredNames.has(data.name)) {
      throw new Error(`Duplicate skill name: ${data.name}`);
    }
    declaredNames.add(data.name);
    const requirements = validateRequirements(
      data.requirements,
      dirName,
      skillIds,
      mcpIds,
      { subgroup: "skills", id: dirName },
    );
    validateLicensePath(data, dirName, skillsDir);
    items.push({
      id: dirName,
      description: data.description,
      category: data.metadata?.category || undefined,
      suggest_for: validateSuggestFor(
        data.metadata?.suggest_for,
        dirName,
        { fieldName: "metadata.suggest_for", filenameExample: "*.rb" },
      ),
      requirements,
      githubUrl: `https://github.com/Kilo-Org/kilo-marketplace/tree/main/skills/${dirName}`,
      rawUrl: `https://raw.githubusercontent.com/Kilo-Org/kilo-marketplace/main/skills/${dirName}/SKILL.md`,
      content: `https://github.com/Kilo-Org/kilo-marketplace/releases/download/skills-latest/${dirName}.tar.gz`,
    });
  }

  // Sort by category then id
  items.sort((a, b) => {
    const catCmp = (a.category || "zzz").localeCompare(b.category || "zzz");
    return catCmp !== 0 ? catCmp : a.id.localeCompare(b.id);
  });

  return items;
}

test("generates marketplace with valid skill", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      category: "development",
    },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items.length, 1);
  assert.equal(items[0].id, "test-skill");
  assert.equal(items[0].description, "A test skill");
  assert.equal(items[0].category, "development");
});

test("generates marketplace with multiple skills sorted by category then id", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "aaa-skill", {
    name: "aaa-skill",
    description: "A skill",
    metadata: { category: "development" },
  });
  writeSkill(root, "bbb-skill", {
    name: "bbb-skill",
    description: "B skill",
    metadata: { category: "business" },
  });
  writeSkill(root, "ccc-skill", {
    name: "ccc-skill",
    description: "C skill",
    metadata: { category: "development" },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items.length, 3);
  assert.equal(items[0].id, "bbb-skill");
  assert.equal(items[1].id, "aaa-skill");
  assert.equal(items[2].id, "ccc-skill");
});

test("rejects skill with missing name", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  const dir = skillDir(root, "test-skill");
  const skillMdPath = path.join(dir, "SKILL.md");
  fs.writeFileSync(skillMdPath, `---\ndescription: "A test skill"\n---\n\nContent\n`);

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /name must match directory/,
  );
});

test("rejects skill with mismatched name", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "other-name",
    description: "A test skill",
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /name must match directory/,
  );
});

test("rejects duplicate skill names via mismatched directory", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "skill-a", {
    name: "duplicate",
    description: "Skill A",
  });
  writeSkill(root, "skill-b", {
    name: "duplicate",
    description: "Skill B",
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /name must match directory/,
  );
});

test("rejects skill with invalid category", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: { category: "invalid-category" },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items[0].category, "invalid-category");
});

test("validates requirements against known skill IDs", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "skill-a", {
    name: "skill-a",
    description: "Skill A",
  });
  writeSkill(root, "skill-b", {
    name: "skill-b",
    description: "Skill B",
    requirements: { skills: ["skill-a"] },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  const skillB = items.find((i) => i.id === "skill-b");
  assert.deepEqual(skillB?.requirements, { skills: ["skill-a"] });
});

test("rejects requirements referencing unknown skill", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "skill-a", {
    name: "skill-a",
    description: "Skill A",
    requirements: { skills: ["nonexistent"] },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /references unknown skill ID "nonexistent"/,
  );
});

test("rejects requirements referencing self", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "skill-a", {
    name: "skill-a",
    description: "Skill A",
    requirements: { skills: ["skill-a"] },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must not reference itself/,
  );
});

test("validates vscode_extensions in requirements", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "skill-a", {
    name: "skill-a",
    description: "Skill A",
    requirements: {
      vscode_extensions: [{ name: "Jupyter", id: "ms-toolsai.jupyter" }],
    },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  const skillA = items.find((i) => i.id === "skill-a");
  assert.deepEqual(skillA?.requirements?.vscode_extensions, [
    { name: "Jupyter", id: "ms-toolsai.jupyter" },
  ]);
});

test("rejects invalid vscode_extensions in requirements", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "skill-a", {
    name: "skill-a",
    description: "Skill A",
    requirements: { vscode_extensions: [{ name: "", id: "invalid" }] },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must contain a non-empty name and a valid extension ID/,
  );
});

test("validates suggest_for with filename patterns", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      suggest_for: { filename: ["*.component.ts", "*.spec.ts"] },
    },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.deepEqual(items[0].suggest_for, {
    filename: ["*.component.ts", "*.spec.ts"],
  });
});

test("validates suggest_for with vscode_extension", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      suggest_for: {
        vscode_extension: [{ name: "Angular", id: "angular.ng-template" }],
      },
    },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.deepEqual(items[0].suggest_for, {
    vscode_extension: [{ name: "Angular", id: "angular.ng-template" }],
  });
});

test("rejects suggest_for with unknown property", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: { suggest_for: { unknown: "value" } },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /has unknown property "unknown"/,
  );
});

test("rejects suggest_for with neither filename nor vscode_extension", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: { suggest_for: {} },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must contain filename or vscode_extension/,
  );
});

test("rejects suggest_for with invalid filename pattern", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: { suggest_for: { filename: ["*ts"] } },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must be a non-empty list of patterns like/,
  );
});

test("validates license_path exists", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  const dir = skillDir(root, "test-skill");
  fs.writeFileSync(path.join(dir, "LICENSE"), "MIT");

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      source: {
        repository: "https://github.com/test/repo",
        path: "skills/test-skill",
        license_path: "LICENSE",
      },
    },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items.length, 1);
});

test("rejects missing license_path", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      source: {
        repository: "https://github.com/test/repo",
        path: "skills/test-skill",
        license_path: "MISSING-LICENSE",
      },
    },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /does not exist/,
  );
});

test("rejects absolute license_path", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      source: {
        repository: "https://github.com/test/repo",
        path: "skills/test-skill",
        license_path: "/etc/passwd",
      },
    },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must be a relative path/,
  );
});

test("rejects license_path with .. segments", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    metadata: {
      source: {
        repository: "https://github.com/test/repo",
        path: "skills/test-skill",
        license_path: "../LICENSE",
      },
    },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must be a relative path/,
  );
});

test("includes githubUrl and rawUrl in output", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.match(items[0].githubUrl, /github\.com\/Kilo-Org\/kilo-marketplace/);
  assert.match(items[0].rawUrl, /raw\.githubusercontent\.com/);
  assert.match(items[0].content, /skills-latest\/test-skill\.tar\.gz/);
});

test("handles skill without metadata.category", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items[0].category, undefined);
});

test("handles skill without requirements", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items[0].requirements, undefined);
});

test("handles skill without suggest_for", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  assert.equal(items[0].suggest_for, undefined);
});

test("handles skill with empty requirements object", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: {},
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /must contain at least one supported subgroup/,
  );
});

test("handles skill with requirements containing empty skills array", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: { skills: [] },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /requirements\.skills must be a non-empty list/,
  );
});

test("validates requirements against known MCP IDs", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  const mcpDir = path.join(mcpsDir, "test-mcp");
  fs.mkdirSync(mcpDir);
  fs.writeFileSync(
    path.join(mcpDir, "MCP.yaml"),
    yaml.stringify({
      id: "test-mcp",
      name: "Test MCP",
      description: "A test MCP",
      author: "test",
      url: "https://example.com",
      category: "development",
      content: '{"type":"streamable-http","url":"https://example.com/mcp"}',
    }),
  );

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: { mcps: ["test-mcp"] },
  });

  const items = generateSkillsMarketplace(root, mcpsDir);
  const skill = items.find((i) => i.id === "test-skill");
  assert.deepEqual(skill?.requirements, { mcps: ["test-mcp"] });
});

test("rejects requirements referencing unknown MCP", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: { mcps: ["unknown-mcp"] },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /references unknown MCP ID "unknown-mcp"/,
  );
});

test("rejects requirements with unknown subgroup", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: { unknown: ["value"] },
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /has unknown property "unknown"/,
  );
});

test("rejects requirements that is not an object", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: "not-an-object",
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /requirements must be an object/,
  );
});

test("rejects requirements that is an array", (t) => {
  const root = fixture(t);
  const mcpsDir = createMcpsDir(root);

  writeSkill(root, "test-skill", {
    name: "test-skill",
    description: "A test skill",
    requirements: ["skill-a"],
  });

  assert.throws(
    () => generateSkillsMarketplace(root, mcpsDir),
    /requirements must be an object/,
  );
});