// KV helper for the conditions record.
// Single key holds the slug-keyed bulk record; the cron writes it, the
// HTTP handler reads it, and the assembler reads it back as last-good.

import type { Conditions } from "./assemble";

const KEY = "conditions";

export async function writeConditions(kv: KVNamespace, value: Conditions): Promise<void> {
  await kv.put(KEY, JSON.stringify(value));
}

export async function readConditionsRaw(kv: KVNamespace): Promise<string | null> {
  return kv.get(KEY);
}

export async function readConditions(kv: KVNamespace): Promise<Conditions | null> {
  return kv.get<Conditions>(KEY, "json");
}
