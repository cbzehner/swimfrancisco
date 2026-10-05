// Isolated production-parity preview owned and stopped by the e2e runner.
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { generateAgentData } from "./generate-agent-data.mjs";

const port = process.argv[2];
if (!/^\d+$/.test(port ?? "")) throw new Error("Expected the e2e runner's port");
const directory = mkdtempSync(join(tmpdir(), "swim-e2e-"));
const assets = join(directory, "public");
const kv = join(process.cwd(), ".e2e", "kv", port);
execFileSync("zola", ["build", "--base-url", `http://127.0.0.1:${port}`, "--output-dir", assets], { stdio: "inherit" });
// Write generated data directly to test assets: never disturb a dev watcher.
await generateAgentData({ outputDir: join(assets, "agent") });
const worker = spawn("node", ["node_modules/wrangler/bin/wrangler.js", "dev", "--config", "worker/wrangler.toml", "--name", `swimfrancisco-e2e-${port}`, "--local", "--ip", "127.0.0.1", "--port", port, "--inspector-port", "0", "--assets", assets, "--persist-to", kv], {
  stdio: "inherit",
  env: { ...process.env, WRANGLER_SEND_METRICS: "false" },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => worker.kill(signal));
worker.on("exit", (code) => { rmSync(directory, { recursive: true, force: true }); rmSync(kv, { recursive: true, force: true }); process.exit(code ?? 1); });
