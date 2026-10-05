const REFETCH_INTERVAL_MS = 15 * 60 * 1000;

// One conditions feed per mounted page. Time and I/O enter only here; failed
// loads preserve the last good snapshot and remain eligible for the next tick.
export function createConditionsClient({ load, now = Date.now, onChange = () => {} }) {
  let lastFetchedAt = null;
  let data = null;
  let pending = null;
  const controller = new AbortController();

  function refresh({ force = false } = {}) {
    if (controller.signal.aborted) return Promise.resolve(data);
    if (pending) return pending;
    if (!force && lastFetchedAt !== null && now() - lastFetchedAt < REFETCH_INTERVAL_MS) return Promise.resolve(data);
    pending = (async () => {
      let next;
      try {
        next = await load(controller.signal);
      } catch {
        return data;
      }
      if (controller.signal.aborted || !next || typeof next !== "object" || Array.isArray(next)) return data;
      data = next;
      lastFetchedAt = now();
      onChange(data);
      return data;
    })().finally(() => { pending = null; });
    return pending;
  }

  return { refresh, get data() { return data; }, dispose() { controller.abort(); } };
}
