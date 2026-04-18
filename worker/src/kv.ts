// KV helpers for conditions storage.
// Layout: one key per slug (`conditions:<slug>`) + one `all` bulk key.

import type { SpotConditions, AllConditions } from "./assemble";

const PREFIX = "conditions:";
const ALL_KEY = "all";

export async function readSpot(kv: KVNamespace, slug: string): Promise<SpotConditions | null> {
  return kv.get<SpotConditions>(`${PREFIX}${slug}`, "json");
}

export async function writeSpot(kv: KVNamespace, slug: string, value: SpotConditions): Promise<void> {
  await kv.put(`${PREFIX}${slug}`, JSON.stringify(value));
}

export async function writeAll(kv: KVNamespace, value: AllConditions): Promise<void> {
  await kv.put(ALL_KEY, JSON.stringify(value));
}

export async function readSpotRaw(kv: KVNamespace, slug: string): Promise<string | null> {
  return kv.get(`${PREFIX}${slug}`);
}

export async function readAllRaw(kv: KVNamespace): Promise<string | null> {
  return kv.get(ALL_KEY);
}
