import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function archiveHead(target) {
  const archivePath = path.join(target, "head.tar");
  const archive = spawnSync("git", ["archive", "--format=tar", "-o", archivePath, "HEAD"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  assert.equal(archive.status, 0, archive.stderr || "git archive failed");

  const extract = spawnSync("tar", ["-xf", archivePath, "-C", target], {
    encoding: "utf8",
  });
  assert.equal(extract.status, 0, extract.stderr || "tar extract failed");
  rmSync(archivePath, { force: true });

  const nodeModules = path.join(ROOT, "node_modules");
  if (existsSync(nodeModules)) {
    symlinkSync(nodeModules, path.join(target, "node_modules"), "dir");
  }
}

test("check-i18n fails when a locale UI catalog loses a key", () => {
  const worktree = mkdtempSync(path.join(tmpdir(), "swimfrancisco-i18n-"));
  try {
    archiveHead(worktree);
    const catalogPath = path.join(worktree, "i18n", "ui", "es.toml");
    const original = readFileSync(catalogPath, "utf8");
    const corrupted = original.replace(/^access = .+\n/m, "");
    assert.notEqual(corrupted, original);
    writeFileSync(catalogPath, corrupted);

    const result = spawnSync(process.execPath, ["scripts/generate-i18n.mjs", "check"], {
      cwd: worktree,
      encoding: "utf8",
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /i18n\/ui\/es\.toml key mismatch/);
  } finally {
    rmSync(worktree, { recursive: true, force: true });
  }
});
