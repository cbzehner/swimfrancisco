import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { CAPTURE_SOURCES, captureScreenshot, runCapture, connectionUrl, sha256 } from '../../scripts/capture-schedules.mjs';

const account = 'a'.repeat(32);
const session = '11111111-1111-1111-1111-111111111111';
async function fixture(t, options = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'swim-capture-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(path.join(root, 'schedule-tools/src/schedules'), { recursive: true });
  await writeFile(path.join(root, 'schedule-tools/src/schedules/registry.toml'), Object.entries(CAPTURE_SOURCES).map(([slug, url]) => `[[pool]]\nslug="${slug}"\npdf_url="${url}"\ncapture_method="cloudflare_browser"\n`).join('\n'));
  const calls = [];
  let timer;
  let pages = 0;
  const fetchApi = async (url, request) => {
    calls.push(request.method);
    assert.equal(request.redirect, 'error');
    if (request.method === 'POST') {
      if (options.createError) throw Error('secret-token query=private');
      return { ok: true, json: async () => ({ sessionId: session, webSocketDebuggerUrl: options.badConnection || `wss://api.cloudflare.com/client/v4/accounts/${account}/browser-rendering/devtools/browser/${session}` }) };
    }
    return { ok: true, json: async () => ({ status: options.closeStatus || 'closed' }) };
  };
  const browser = {
    version: () => 'mock-browser',
    close: async () => { calls.push('browser-close'); },
    newContext: async () => {
      const frame = {};
      let url;
      return {
        close: async () => { calls.push('context-close'); },
        newCDPSession: async () => ({
          detach: async () => { calls.push('cdp-detach'); },
          send: async (method, config) => {
            if (method === 'Page.getLayoutMetrics') return { cssContentSize: { width: 1280, height: options.oversize ? 30001 : 4500 } };
            assert.equal(method, 'Page.captureScreenshot');
            assert.deepEqual(config.clip, { x: 0, y: 0, width: 1280, height: 4500, scale: 1 });
            if (options.screenshotError) throw Error('secret-token cookies=private');
            return { data: Buffer.from('mock-png').toString('base64') };
          },
        }),
        newPage: async () => {
          pages++;
          return {
            mainFrame: () => frame,
            url: () => url,
            goto: async value => {
              url = value;
              if (options.deadline) { timer(); throw Error('secret-token'); }
              if (options.pageError) throw Error('secret-token cookies=private');
              return { status: () => options.status || 200, headers: () => ({ 'content-type': options.contentType || 'text/html; charset=utf-8', 'set-cookie': 'private=secret-token', 'location': 'https://private/?token=secret-token' }),
                url: () => options.finalUrl || url,
                request: () => ({ frame: () => options.wrongFrame ? {} : frame, redirectedFrom: () => options.redirect || null }),
                body: async () => Buffer.from('<html>original</html>') };
            },
            waitForLoadState: async (state, config) => {
              assert.equal(state, 'networkidle');
              assert.equal(config.timeout, 3000);
              if (options.idleTimeout) { const error = Error('secret-token'); error.name = 'TimeoutError'; throw error; }
            },
            content: async () => '<html>rendered</html>',

          };
        },
      };
    },
  };
  return { root, calls, pages: () => pages, args: {
    root, env: { CLOUDFLARE_BROWSER_API_TOKEN: 'secret-token', CLOUDFLARE_ACCOUNT_ID: account },
    fetchApi, connect: async () => { calls.push('connect'); return browser; }, now: () => Date.parse('2026-09-08T12:00:00Z'),
    setTimer: callback => { timer = callback; return 1; }, clearTimer: () => {},
  } };
}

test('six primary captures preserve original and rendered bytes, hashes and close the session once', async t => {
  const f = await fixture(t);
  const result = await runCapture(f.args);
  assert.equal(result.closed, true);
  assert.equal(result.results.length, 6);
  assert(result.results.every(item => item.status === 'captured'));
  assert.equal(f.calls.filter(item => item === 'POST').length, 1);
  assert.equal(f.calls.filter(item => item === 'DELETE').length, 1);
  assert.equal(f.pages(), 6);
  const directory = path.join(f.root, 'tmp/browser-capture/jccsf');
  const receipt = JSON.parse(await readFile(path.join(directory, 'capture.json')));
  assert.equal(receipt.hashes.source, sha256(await readFile(path.join(directory, 'source.html'))));
  assert.equal(receipt.hashes.rendered, sha256(await readFile(path.join(directory, 'rendered.html'))));
  assert.equal(receipt.hashes.screenshot, sha256(await readFile(path.join(directory, 'screenshot.png'))));
  assert.notEqual(receipt.hashes.source, receipt.hashes.rendered);
  assert.equal(receipt.status, 200);
  assert.match(receipt.configuration.script_sha256, /^[a-f0-9]{64}$/);
  await assert.rejects(runCapture(f.args), { code: 'EEXIST' });
  assert.equal(f.calls.filter(item => item === 'POST').length, 1);
});

for (const [name, options] of Object.entries({ status: { status: 403 }, html: { contentType: 'application/json' }, url: { finalUrl: 'https://evil.example/?token=private' }, frame: { wrongFrame: true }, redirect: { redirect: {} }, failure: { pageError: true } })) {
  test(`rejects ${name} without retries or secret-bearing errors and closes browser`, async t => {
    const f = await fixture(t, options);
    const result = await runCapture(f.args);
    assert.equal(result.closed, true);
    assert(result.results.every(item => item.status === 'failed'));
    assert.equal(f.pages(), 6);
    assert.equal(f.calls.filter(item => item === 'POST').length, 1);
    assert(!JSON.stringify(result).includes('private'));
    assert(!JSON.stringify(result).includes('secret-token'));
  });
}

test('hard deadline closes once, prevents later pages and never retries navigation', async t => {
  const f = await fixture(t, { deadline: true });
  const result = await runCapture(f.args);
  assert.equal(f.pages(), 1);
  assert.equal(f.calls.filter(item => item === 'DELETE').length, 1);
  assert(result.results.every(item => item.status === 'failed'));
});

test('an unconfirmed session close is reported, not assumed closed', async t => {
  const f = await fixture(t, { closeStatus: 'closing' });
  const result = await runCapture(f.args);
  assert.equal(result.closed, false);
});

test('creation failure stops the batch; invalid connection never gets credentials', async t => {
  for (const options of [{ createError: true }, { badConnection: 'wss://evil.example/browser' }]) {
    const f = await fixture(t, options);
    const result = await runCapture(f.args);
    assert.equal(f.calls.includes('connect'), false);
    assert.equal(f.calls.filter(item => item === 'POST').length, 1);
    assert.equal(result.error, 'browser_batch_failed');
  }
});

test('missing credentials fail before browser creation', async t => {
  const f = await fixture(t);
  await assert.rejects(runCapture({ ...f.args, env: {} }), /browser_configuration_missing/);
  assert.equal(f.calls.length, 0);
});

test('connection URL cannot redirect authorization to other hosts or accounts', () => {
  for (const url of [`wss://api.cloudflare.com.evil.example/client/v4/accounts/${account}/browser-rendering/devtools/browser/${session}`, `wss://api.cloudflare.com/client/v4/accounts/${account}/browser-rendering/devtools/browser/${session}?token=x`]) assert.throws(() => connectionUrl(url, account, session));
});


test('registry changes outside the six approved original URLs fail before browser creation', async t => {
  const f = await fixture(t);
  const registry = path.join(f.root, 'schedule-tools/src/schedules/registry.toml');
  await writeFile(registry, (await readFile(registry, 'utf8')).replace(CAPTURE_SOURCES.jccsf, 'https://example.com/unapproved'));
  await assert.rejects(runCapture(f.args), /invalid_capture_registry/);
  assert.equal(f.calls.length, 0);
});


test('screenshot failure reports its stage and safe response facts only', async t => {
  const f = await fixture(t, { screenshotError: true });
  const result = await runCapture(f.args);
  assert(result.results.every(item => item.stage === 'screenshot' && item.http_status === 200));
  assert.deepEqual(result.results[0].headers, { 'content-type': 'text/html' });
  assert(!JSON.stringify(result).includes('private'));
  assert(!JSON.stringify(result).includes('secret-token'));
  assert.equal(result.closed, true);
});

test('network idle timeout does not prevent screenshot capture', async t => {
  const f = await fixture(t, { idleTimeout: true });
  const result = await runCapture(f.args);
  assert(result.results.every(item => item.status === 'captured'));
});


test('oversized full-page captures hold without cropping and always detach CDP', async t => {
  const f = await fixture(t, { oversize: true });
  const result = await runCapture(f.args);
  assert(result.results.every(item => item.error === 'screenshot_dimensions_unsupported'));
  assert.equal(f.calls.filter(item => item === 'cdp-detach').length, 6);
});


test('CDP screenshot deadline rejects and detaches a stalled capture', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let detached = false;
  const context = { newCDPSession: async () => ({ send: async () => new Promise(() => {}), detach: async () => { detached = true; } }) };
  const pending = captureScreenshot(context, {});
  const rejection = assert.rejects(pending, /screenshot_timeout/);
  await Promise.resolve();
  t.mock.timers.tick(5000);
  await rejection;
  assert.equal(detached, true);
});
