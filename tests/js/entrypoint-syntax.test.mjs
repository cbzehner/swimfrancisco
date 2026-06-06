import { test } from "node:test";
import { execFileSync } from "node:child_process";

const ENTRYPOINTS = [
  "static/js/status.js",
  "static/js/detail.js",
  "static/js/conditions.js",
  "static/js/map.js",
];

test("browser entrypoints parse", () => {
  for (const entrypoint of ENTRYPOINTS) {
    execFileSync(process.execPath, ["--check", entrypoint], { stdio: "pipe" });
  }
});
