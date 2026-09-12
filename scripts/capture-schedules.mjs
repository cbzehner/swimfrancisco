import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'smol-toml';
import { chromium } from 'playwright-core';

const scriptPath = fileURLToPath(import.meta.url);
const require = createRequire(import.meta.url);
export const CAPTURE_SOURCES = Object.freeze({
  'jccsf': 'https://www.jccsf.org/fitness/aquatics/',
  'presidio-ymca-letterman': 'https://www.ymcasf.org/location/presidio-community-ymca/letterman-pool-gym/',
  'stonestown-ymca': 'https://www.ymcasf.org/location/stonestown-family-ymca/',
  'embarcadero-ymca': 'https://www.ymcasf.org/location/embarcadero-ymca/',
  'chinatown-ymca': 'https://www.ymcasf.org/location/chinatown-ymca/',
  'sfsu-mashouf': 'https://campusrec.sfsu.edu/Aquatics',
});
const DEADLINE = 80_000;
export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = code => { throw new Error(code); };
const writeJson = (file, value) => writeFile(file, JSON.stringify(value, null, 2) + '\n');

export function sourceUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) fail('invalid_source_url');
  return url.href.replace(/\/$/, '');
}

export function connectionUrl(value, account, session) {
  const url = new URL(value);
  if (url.protocol !== 'wss:' || url.host !== 'api.cloudflare.com' || url.username || url.password || url.search || url.hash
      || url.pathname !== `/client/v4/accounts/${account}/browser-rendering/devtools/browser/${session}`) fail('invalid_connection_url');
  return url.href;
}

export async function captureScreenshot(context, page) {
  const session = await context.newCDPSession(page);
  let timer;
  try {
    return await Promise.race([
      (async () => {
        const { cssContentSize } = await session.send('Page.getLayoutMetrics');
        const { width, height } = cssContentSize || {};
        if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || width > 2000 || height > 30000) fail('screenshot_dimensions_unsupported');
        const result = await session.send('Page.captureScreenshot', {
          format: 'png', captureBeyondViewport: true,
          clip: { x: 0, y: 0, width: Math.ceil(width), height: Math.ceil(height), scale: 1 },
        });
        return Buffer.from(result.data, 'base64');
      })(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('screenshot_timeout')), 5000); }),
    ]);
  } finally {
    clearTimeout(timer);
    await session.detach().catch(() => {});
  }
}

export async function runCapture({ root = path.resolve(path.dirname(scriptPath), '..'), env = process.env, fetchApi = fetch,
  connect = (...args) => chromium.connectOverCDP(...args), now = Date.now,
  setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  const token = env.CLOUDFLARE_BROWSER_API_TOKEN;
  const account = env.CLOUDFLARE_ACCOUNT_ID;
  if (!token || !/^[a-f0-9]{32}$/.test(account || '')) fail('browser_configuration_missing');
  const entries = parse(await readFile(path.join(root, 'schedule-tools/src/schedules/registry.toml'), 'utf8')).pool
    .filter(entry => entry.capture_method === 'cloudflare_browser');
  if (entries.length !== 6 || new Set(entries.map(entry => entry.slug)).size !== 6) fail('invalid_capture_registry');
  for (const entry of entries) {
    if (CAPTURE_SOURCES[entry.slug] !== entry.pdf_url) fail('invalid_capture_registry');
    sourceUrl(entry.pdf_url);
  }
  const output = path.join(root, 'tmp/browser-capture');
  await mkdir(path.dirname(output), { recursive: true });
  await mkdir(output);
  let session;
  let browser;
  let timer;
  let closePromise;
  let expired = false;
  const started = now();
  const manifest = { results: [], closed: false };
  const headers = { Authorization: `Bearer ${token}` };
  const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/browser-rendering/devtools/browser`;
  const configuration = { script_sha256: sha256(await readFile(scriptPath)), playwright_version: require('playwright-core/package.json').version };
  async function closeSession() {
    if (!session) return false;
    if (closePromise) return closePromise;
    closePromise = (async () => {
      try {
        const response = await fetchApi(`${endpoint}/${session}`, { method: 'DELETE', headers, redirect: 'error', signal: AbortSignal.timeout(5000) });
        const result = await response.json();
        return response.ok && result.status === 'closed';
      } catch { return false; }
    })();
    return closePromise;
  }
  const checkDeadline = () => { if (expired || now() - started >= DEADLINE) fail('browser_deadline'); };
  try {
    timer = setTimer(() => { expired = true; void closeSession(); void browser?.close().catch(() => {}); }, DEADLINE);
    const response = await fetchApi(`${endpoint}?keep_alive=60000`, { method: 'POST', headers, redirect: 'error', signal: AbortSignal.timeout(10000) });
    if (!response.ok) fail('browser_create_failed');
    const created = await response.json();
    if (!/^[a-f0-9-]{36}$/.test(created.sessionId || '')) fail('browser_create_invalid');
    session = created.sessionId;
    checkDeadline();
    const address = connectionUrl(created.webSocketDebuggerUrl, account, session);
    browser = await connect(address, { headers, timeout: 10000 });
    for (const entry of entries) {
      let context;
      let stage = 'context';
      let responseEvidence = {};
      try {
        checkDeadline();
        context = await browser.newContext({ viewport: { width: 1280, height: 960 }, timezoneId: 'America/Los_Angeles', locale: 'en-US', serviceWorkers: 'block' });
        const page = await context.newPage();
        stage = 'navigation';
        const response = await page.goto(entry.pdf_url, { waitUntil: 'domcontentloaded', timeout: 10000 });
        stage = 'response_validation';
        if (response) {
          const headers = response.headers();
          responseEvidence = { http_status: response.status(), headers: {} };
          const contentType = headers['content-type']?.split(';')[0].trim().toLowerCase();
          if (['text/html', 'application/xhtml+xml', 'application/json', 'text/plain'].includes(contentType)) responseEvidence.headers['content-type'] = contentType;
          if (headers['cf-mitigated'] === 'challenge') responseEvidence.headers['cf-mitigated'] = 'challenge';
        }
        if (!response || response.request().frame() !== page.mainFrame() || response.status() !== 200) fail('source_http_failed');
        if (!/^text\/html(?:;|$)/i.test(response.headers()['content-type'] || '')) fail('source_not_html');
        if (response.request().redirectedFrom() || sourceUrl(response.url()) !== sourceUrl(entry.pdf_url)
            || sourceUrl(page.url()) !== sourceUrl(entry.pdf_url)) fail('source_identity_changed');
        stage = 'response_body';
        const source = await response.body();
        stage = 'network_idle';
        await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(error => {
          if (error.name !== 'TimeoutError') throw error;
        });
        checkDeadline();
        stage = 'rendered';
        const rendered = Buffer.from(await page.content());
        stage = 'screenshot';
        const screenshot = await captureScreenshot(context, page);
        checkDeadline();
        if (sourceUrl(page.url()) !== sourceUrl(entry.pdf_url)) fail('source_identity_changed');
        stage = 'evidence_write';
        const directory = path.join(output, entry.slug);
        await mkdir(directory);
        await writeFile(path.join(directory, 'source.html'), source);
        await writeFile(path.join(directory, 'rendered.html'), rendered);
        await writeFile(path.join(directory, 'screenshot.png'), screenshot);
        await writeJson(path.join(directory, 'capture.json'), {
          method: 'cloudflare_browser', requested_url: entry.pdf_url, url: response.url(), captured_at: new Date(now()).toISOString(), status: 200,
          configuration, hashes: { source: sha256(source), rendered: sha256(rendered), screenshot: sha256(screenshot) }, browser_version: browser.version(),
        });
        manifest.results.push({ slug: entry.slug, status: 'captured', path: `${entry.slug}/capture.json` });
      } catch (error) {
        const known = ['browser_deadline', 'source_http_failed', 'source_not_html', 'source_identity_changed', 'invalid_source_url', 'screenshot_timeout', 'screenshot_dimensions_unsupported'];
        manifest.results.push({ slug: entry.slug, status: 'failed', stage, ...responseEvidence, error: known.includes(error.message) ? error.message : 'capture_failed' });
      } finally { await context?.close().catch(() => {}); }
    }
  } catch { manifest.error = 'browser_batch_failed'; }
  finally {
    clearTimer(timer);
    manifest.closed = await closeSession();
    await browser?.close().catch(() => {});
    await writeJson(path.join(output, 'results.json'), manifest);
  }
  return manifest;
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  runCapture().then(result => { process.exitCode = result.closed && result.results.length === 6 && result.results.every(item => item.status === 'captured') ? 0 : 1; })
    .catch(() => { console.error('Browser capture failed before completion.'); process.exitCode = 1; });
}
