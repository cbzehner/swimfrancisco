import { test } from "node:test";
import assert from "node:assert/strict";
import { createConditionsClient } from "../../static/js/helpers/conditions-client.mjs";

test("conditions deduplicate pending requests and throttle from the last successful completion", async () => {
  let now = 0;
  let finish;
  let requests = 0;
  const received = [];
  const client = createConditionsClient({ now: () => now, onChange: (data) => received.push(data),
    load: () => { requests++; return new Promise((resolve) => { finish = resolve; }); } });
  const first = client.refresh();
  assert.equal(client.refresh({ force: true }), first);
  now = 60_000;
  finish({ bay: { water_temp_f: 60 } });
  await first;
  assert.deepEqual(received, [{ bay: { water_temp_f: 60 } }]);
  now = 15 * 60_000;
  await client.refresh();
  assert.equal(requests, 1, "throttle starts when the response completes");
  now += 60_000;
  const next = client.refresh();
  assert.equal(requests, 2);
  finish({});
  await next;
  assert.deepEqual(client.data, {}, "successful empty data withdraws prior readings");
  client.dispose();
});

test("conditions failures retain last-good data and retry on the next tick", async () => {
  let now = 0;
  let response = null;
  let requests = 0;
  const received = [];
  const client = createConditionsClient({ now: () => now, onChange: (data) => received.push(data),
    load: async () => { requests++; if (response instanceof Error) throw response; return response; } });
  await client.refresh();
  response = { bay: { water_temp_f: 58 } };
  now += 60_000;
  await client.refresh();
  assert.equal(requests, 2);
  const lastGood = client.data;
  response = new Error("upstream unavailable");
  now += 15 * 60_000;
  await client.refresh();
  assert.equal(client.data, lastGood);
  now += 60_000;
  await client.refresh();
  assert.equal(requests, 4);
  assert.deepEqual(received, [lastGood]);
  response = [];
  await client.refresh();
  assert.equal(client.data, lastGood, "an array is not the slug-keyed conditions record");
  client.dispose();
});

test("disposing conditions aborts the request and ignores a late completion; mounts are independent", async () => {
  let finish;
  let signal;
  let requests = 0;
  const client = createConditionsClient({
    load: (requestSignal) => { requests++; signal = requestSignal; return new Promise((resolve) => { finish = resolve; }); },
    onChange: () => assert.fail("disposed client cannot notify the page"),
  });
  const pending = client.refresh();
  client.dispose();
  assert.equal(signal.aborted, true);
  finish({ bay: { water_temp_f: 60 } });
  await pending;
  await client.refresh({ force: true });
  assert.equal(requests, 1);
  assert.equal(client.data, null);
  const remounted = createConditionsClient({ load: async () => ({ bay: { water_temp_f: 61 } }) });
  await remounted.refresh();
  assert.deepEqual(remounted.data, { bay: { water_temp_f: 61 } });
  remounted.dispose();
});
