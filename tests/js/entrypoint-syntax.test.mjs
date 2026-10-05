import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { join } from "node:path";

test("all browser modules parse", () => {
  for (const module of readdirSync("static/js", { recursive: true }).filter((name) => /\.m?js$/.test(name))) {
    execFileSync(process.execPath, ["--check", join("static/js", module)], { stdio: "pipe" });
  }
});
