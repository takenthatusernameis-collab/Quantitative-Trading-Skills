#!/usr/bin/env npx tsx
/**
 * Add a remote skill from a GitHub repository.
 *
 * Usage: npx tsx bin/add-remote-skill.ts <github-url-with-path>
 *
 * Example:
 *   npx tsx bin/add-remote-skill.ts https://github.com/vercel-labs/agent-skills/tree/main/skills/claude.ai/web-design-guidelines
 *   npx tsx bin/add-remote-skill.ts https://github.com/google-gemini/gemini-cli/tree/main/.gemini/skills/pr-creator
 *
 * This script will:
 * 1. Clone/download the specified directory from the GitHub repo
 * 2. Copy it to the local skills directory
 * 3. Update the SKILL.md frontmatter to add source metadata and category if missing
 */

import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import { execFileSync } from "child_process";
import matter from "gray-matter";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillsDir = path.join(__dirname, "..", "skills");

function ensureFinalNewline(content: string): string {
  return content.replace(/(?:\r?\n)+$/, "") + "\n";
}

function parseGitHubUrl(url: string): {
  owner: string;
  repo: string;
  ref: string;
  skillPath: string;
} {
  const parsed = new URL(url);
  if (parsed.hostname !== "github.com") {
    throw new Error(`Invalid GitHub URL host: ${parsed.hostname}`);
  }

  const parts = parsed.pathname.replace(/^\/|\/$/g, "").split("/");
  const [owner, repo, kind, ...refAndPath] = parts;
  if (!owner || !repo || !["tree", "blob"].includes(kind) || refAndPath.length < 2) {
    throw new Error(
      `Invalid GitHub URL: ${url}\n\nExpected format: https://github.com/owner/repo/tree/branch/path/to/skill`,
    );
  }

  const resolved = resolveRefAndPath(owner, repo, refAndPath);
  const skillPath =
    kind === "blob" ? path.dirname(resolved.path) : resolved.path;

  validateSourcePath(skillPath);

  return {
    owner,
    repo,
    ref: resolved.ref,
    skillPath,
  };
}

function resolveRefAndPath(
  owner: string,
  repo: string,
  refAndPath: string[],
): { ref: string; path: string } {
  const repository = `https://github.com/${owner}/${repo}.git`;
  const refs = listRemoteRefs(repository);

  for (let i = refAndPath.length - 1; i >= 1; i -= 1) {
    const candidate = refAndPath.slice(0, i).join("/");
    if (refs.has(candidate)) {
      return {
        ref: candidate,
        path: refAndPath.slice(i).join("/"),
      };
    }
  }

  if (/^[0-9a-f]{40}$/i.test(refAndPath[0])) {
    return {
      ref: refAndPath[0],
      path: refAndPath.slice(1).join("/"),
    };
  }

  throw new Error(
    `Could not resolve GitHub ref from ${repository}: ${refAndPath.join("/")}`,
  );
}

function listRemoteRefs(repository: string): Set<string> {
  const output = execFileSync("git", ["ls-remote", "--heads", "--tags", repository], {
    encoding: "utf-8",
  });
  const refs = new Set<string>();
  for (const line of output.split(/\r?\n/)) {
    const [, refName] = line.split(/\s+/);
    if (!refName || refName.endsWith("^{}")) continue;
    refs.add(refName.replace(/^refs\/(heads|tags)\//, ""));
  }
  return refs;
}

function validateSourcePath(sourcePath: string): void {
  if (
    path.isAbsolute(sourcePath) ||
    sourcePath.split(/[\\/]/).some((part) => part === "..") ||
    /[\r\n]/.test(sourcePath)
  ) {
    throw new Error(`Invalid source path: ${sourcePath}`);
  }
}

function copySkillSource(sourceDir: string, destinationDir: string, checkoutDir: string): void {
  const gitDir = path.resolve(checkoutDir, ".git");
  fs.cpSync(sourceDir, destinationDir, {
    recursive: true,
    filter: (source) => {
      const resolved = path.resolve(source);
      return resolved !== gitDir && !resolved.startsWith(`${gitDir}${path.sep}`);
    },
  });
}

function getSkillName(skillPath: string): string {
  // Get the last component of the path as the skill name
  return path.basename(skillPath);
}

/**
 * Locate a LICENSE file within the skill directory. Returns the path relative
 * to the skill directory, or undefined when none is present. The canonical
 * naming variants from CONTRIBUTING.md are checked first, then a case-
 * insensitive fallback.
 */
function findLicenseFile(skillDir: string): string | undefined {
  const candidates = [
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "license",
    "COPYING",
    "COPYING.md",
    "COPYING.txt",
  ];
  for (const name of candidates) {
    const candidatePath = path.join(skillDir, name);
    if (fs.existsSync(candidatePath) && fs.statSync(candidatePath).isFile()) {
      return name;
    }
  }
  try {
    const entries = fs.readdirSync(skillDir);
    const match = entries.find((entry) => {
      if (
        !(
          entry.toLowerCase() === "license" ||
          entry.toLowerCase() === "license.md" ||
          entry.toLowerCase() === "license.txt" ||
          entry.toLowerCase() === "copying" ||
          entry.toLowerCase() === "copying.md" ||
          entry.toLowerCase() === "copying.txt"
        )
      ) {
        return false;
      }
      // Directories named like licenses are not valid license files.
      try {
        return fs.statSync(path.join(skillDir, entry)).isFile();
      } catch {
        return false;
      }
    });
    return match;
  } catch {
    return undefined;
  }
}

async function main() {
  const args = process.argv.slice(2);

  if (args.length < 1) {
    console.error(
      "Usage: npx tsx bin/add-remote-skill.ts <github-url-with-path>",
    );
    console.error(
      "\nExample: npx tsx bin/add-remote-skill.ts https://github.com/vercel-labs/agent-skills/tree/main/skills/claude.ai/web-design-guidelines",
    );
    console.error(
      "         npx tsx bin/add-remote-skill.ts https://github.com/google-gemini/gemini-cli/tree/main/.gemini/skills/pr-creator",
    );
    process.exit(1);
  }

  const [fullUrl] = args;

  const { owner, repo, ref, skillPath } = parseGitHubUrl(fullUrl);
  const skillName = getSkillName(skillPath);
  const targetDir = path.join(skillsDir, skillName);

  console.log(`Adding skill from ${owner}/${repo}:${skillPath}`);
  console.log(`Target directory: ${targetDir}`);

  // Check if target already exists
  if (fs.existsSync(targetDir)) {
    console.error(`Error: Skill directory already exists: ${targetDir}`);
    console.error("Remove it first if you want to re-add the skill.");
    process.exit(1);
  }

  // Create a temporary directory for sparse checkout
  const tempDir = fs.mkdtempSync(path.join("/tmp", "skill-"));

  try {
    console.log("\nCloning repository (sparse checkout)...");

    // Initialize a sparse checkout
    execFileSync("git", ["init"], { cwd: tempDir, stdio: "pipe" });
    execFileSync(
      "git",
      ["remote", "add", "origin", `https://github.com/${owner}/${repo}.git`],
      { cwd: tempDir, stdio: "pipe" },
    );
    execFileSync("git", ["config", "core.sparseCheckout", "true"], {
      cwd: tempDir,
      stdio: "pipe",
    });

    // Set up sparse checkout for just the skill directory
    fs.writeFileSync(
      path.join(tempDir, ".git", "info", "sparse-checkout"),
      skillPath + "\n",
    );

    // Fetch and checkout the URL's requested ref
    execFileSync("git", ["fetch", "--depth", "1", "origin", ref], {
      cwd: tempDir,
      stdio: "pipe",
    });
    execFileSync("git", ["checkout", "FETCH_HEAD"], {
      cwd: tempDir,
      stdio: "pipe",
    });
    const sourceCommit = execFileSync(
      "git",
      ["rev-parse", "FETCH_HEAD"],
      { cwd: tempDir, encoding: "utf-8" },
    ).trim();

    const sourceDir = path.join(tempDir, skillPath);

    if (!fs.existsSync(sourceDir)) {
      throw new Error(`Skill directory not found in repository: ${skillPath}`);
    }

    // Copy the skill directory
    console.log(`Copying skill to ${targetDir}...`);
    copySkillSource(sourceDir, targetDir, tempDir);

    // Update the SKILL.md frontmatter
    const skillMdPath = path.join(targetDir, "SKILL.md");
    if (!fs.existsSync(skillMdPath)) {
      throw new Error(`SKILL.md not found in ${targetDir}`);
    }

    console.log("Updating SKILL.md frontmatter...");
    const content = fs.readFileSync(skillMdPath, "utf-8");
    const { data: frontmatter, content: body } = matter(content);

    // Ensure metadata object exists
    if (!frontmatter.metadata) {
      frontmatter.metadata = {};
    }

    // Add category if not present
    if (!frontmatter.metadata.category) {
      frontmatter.metadata.category = "unknown";
      console.log("  Added category: unknown");
    }

    // Add source information
    frontmatter.metadata.source = {
      repository: `https://github.com/${owner}/${repo}`,
      path: skillPath,
      ref,
      commit: sourceCommit,
    };
    console.log(`  Added source: https://github.com/${owner}/${repo}`);
    console.log(`  Added path: ${skillPath}`);
    console.log(`  Added ref: ${ref}`);
    console.log(`  Added commit: ${sourceCommit}`);

    // CONTRIBUTING.md requires metadata.source.license_path for every
    // contributed skill. Copy the license file alongside the skill and
    // record it; if none is present, warn so the importer can add it
    // rather than shipping a silently non-compliant entry.
    const licenseFile = findLicenseFile(targetDir);
    if (licenseFile) {
      frontmatter.metadata.source.license_path = licenseFile;
      console.log(`  Added license_path: ${licenseFile}`);
    } else {
      console.log(
        `  Warning: no LICENSE file found in ${targetDir}; ` +
          "metadata.source.license_path was not set (see CONTRIBUTING.md).",
      );
    }

    // Write back the updated SKILL.md
    const updatedContent = matter.stringify(body, frontmatter);
    fs.writeFileSync(skillMdPath, ensureFinalNewline(updatedContent));

    console.log(`\n✓ Successfully added skill: ${skillName}`);
    console.log(`  Location: ${targetDir}`);
  } finally {
    // Clean up temp directory
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

export { findLicenseFile };

// Only run main() when executed directly, so the module can be imported by
// tests without triggering the CLI flow.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    console.error("Error:", err.message);
    process.exit(1);
  });
}
