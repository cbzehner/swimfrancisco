import type { E2EConfig } from "e2e";
import { web } from "@e2e-dev/web";

// A fresh Worker and KV store per run: no production data or model login.
const app = {
  url: "http://127.0.0.1:0",
  command: {
    executable: "node",
    args: ["scripts/serve-e2e.mjs", "{port}"],
    startupTimeout: 120_000,
    log: ".e2e/logs/worker.log",
  },
};

export default {
  tests: "tests/e2e/**/*.e2e.ts",
  targets: [
    { name: "chromium", engine: web({ timezoneId: "Asia/Tokyo" }), app },
    { name: "narrow-webkit", engine: web({ browser: "webkit", viewport: { width: 390, height: 844 }, timezoneId: "Asia/Tokyo" }), app },
  ],
  workers: 1,
  retries: 0,
  timeout: 30_000,
  trace: "retain-on-failure",
} satisfies E2EConfig;
