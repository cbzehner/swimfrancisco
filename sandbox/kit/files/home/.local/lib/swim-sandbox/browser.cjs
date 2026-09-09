const { chromium } = require('/home/agent/workspace/node_modules/playwright-core');

(async () => {
  const proxyServer = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
  const context = await chromium.launchPersistentContext(
    '/home/agent/.local/share/swim-browser',
    {
      headless: false,
      chromiumSandbox: true,
      viewport: null,
      args: [
        '--start-maximized', '--hide-crash-restore-bubble',
        '--remote-debugging-port=9222', '--remote-debugging-address=127.0.0.1',
      ],
      ...(proxyServer && {
        proxy: { server: proxyServer, bypass: 'localhost,127.0.0.1,[::1]' },
      }),
    },
  );
  const page = context.pages()[0] || await context.newPage();
  await page.goto('http://localhost:8787').catch(() => {});
  await new Promise(resolve => context.on('close', resolve));
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
