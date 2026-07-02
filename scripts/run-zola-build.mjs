#!/usr/bin/env node

import { spawn } from "node:child_process";
import { chmod, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..");
const zolaVersion = process.env.ZOLA_VERSION || "0.22.1";
const cacheDir = join(repoRoot, "node_modules/.cache/swimfrancisco", `zola-v${zolaVersion}`);
const cachedZola = join(cacheDir, "zola");

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      stdio: "inherit",
      ...options,
    });

    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} ${args.join(" ")} exited with ${code}`));
      }
    });
  });
}

async function runIfAvailable(command, args) {
  try {
    await run(command, args);
    return true;
  } catch (err) {
    if (err.code === "ENOENT") return false;
    throw err;
  }
}

function cloudflareLinuxTarget() {
  if (process.platform === "linux" && process.arch === "x64") {
    return "x86_64-unknown-linux-gnu";
  }
  return null;
}

async function ensureCachedZola() {
  const target = cloudflareLinuxTarget();
  if (!target) {
    throw new Error("zola was not found on PATH. Install Zola locally or run on Cloudflare's Linux x64 build image.");
  }

  await mkdir(cacheDir, { recursive: true });
  const archive = join(cacheDir, "zola.tar.gz");
  const url = `https://github.com/getzola/zola/releases/download/v${zolaVersion}/zola-v${zolaVersion}-${target}.tar.gz`;

  await run("curl", ["-fsSL", "-o", archive, url]);
  await run("tar", ["-xzf", archive, "-C", cacheDir, "zola"]);
  await chmod(cachedZola, 0o755);
  return cachedZola;
}

async function main() {
  if (await runIfAvailable("zola", ["build"])) return;

  console.log(`zola not found on PATH; downloading Zola ${zolaVersion}`);
  const zola = await ensureCachedZola();
  await run(zola, ["build"]);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
