import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const dataDir = path.join(root, "data");
const outPath = path.join(root, "data", "bulletin.json");

async function reviewedSnapshotPaths(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const paths = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      paths.push(...await reviewedSnapshotPaths(fullPath));
    } else if (entry.isFile() && entry.name === "reviewed.json") {
      paths.push(fullPath);
    }
  }
  return paths;
}

const snapshots = await reviewedSnapshotPaths(dataDir);
snapshots.sort();

const hash = createHash("sha256");
for (const snapshot of snapshots) {
  hash.update(path.relative(root, snapshot));
  hash.update("\0");
  hash.update(await readFile(snapshot));
  hash.update("\0");
}
const scheduleFingerprint = hash.digest("hex");

let existing = {};
try {
  existing = JSON.parse(await readFile(outPath, "utf8"));
} catch (err) {
  // ENOENT (first run) is expected and starts the launch bulletin at 00.
  // Any other error — parse failure, permission, etc. — would silently
  // reset the bulletin counter and re-broadcast a fresh launch label,
  // which is bad. Re-throw so the generator fails loudly instead.
  if (err.code !== "ENOENT") throw err;
}

const existingNumber = Number.isInteger(existing.number) ? existing.number : 0;
const hasPreviousFingerprint = typeof existing.schedule_fingerprint === "string";
const releasedFingerprint =
  typeof existing.released_schedule_fingerprint === "string"
    ? existing.released_schedule_fingerprint
    : hasPreviousFingerprint
      ? existing.schedule_fingerprint
      : scheduleFingerprint;
const releasePending = releasedFingerprint !== scheduleFingerprint;
const number = releasePending ? existingNumber + 1 : existingNumber;
const releasedScheduleFingerprint = releasePending ? scheduleFingerprint : releasedFingerprint;

const payload = {
  schedule_fingerprint: scheduleFingerprint,
  released_schedule_fingerprint: releasedScheduleFingerprint,
  reviewed_count: snapshots.length,
  number,
  label: String(number).padStart(2, "0"),
};

await writeFile(outPath, `${JSON.stringify(payload, null, 2)}\n`);
console.log(
  `Wrote bulletin ${payload.label} from ${snapshots.length} reviewed schedules to ` +
    path.relative(root, outPath),
);
