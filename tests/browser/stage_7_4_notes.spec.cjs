const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/opt/data/workspace/AUTOEDIT/.hermes/watchdog-browser/node_modules/playwright');

const ROOT = path.resolve(__dirname, '../../src/autoedit/web');
const PROJECT = '01J00000000000000000000000';
const notes = [
  { id: 'n1', t_ms: 1000, body: '<script>window.__xss = true</script>', kind: 'note', author: 'Reviewer Alpha' },
  { id: 'n2', t_ms: 5000, body: 'Cut to the wide here', kind: 'cut_suggestion', author: 'Reviewer Beta' },
];

function makeServer() {
  return http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    const json = (status, value) => {
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(value));
    };
    if (url.pathname === `/projects/${PROJECT}/progress`) return json(200, { ready: true, status: 'ready' });
    if (url.pathname === `/projects/${PROJECT}/player-state`) return json(200, {
      project: { fps_num: 25, fps_den: 1 },
      quality_default: 'proxy',
      angles: [{ id: 'a', label: 'Camera A', color: '#fff' }],
      cut: { clips: [{ angle_id: 'a', timeline_in_ms: 0, dur_ms: 10000, src_in_ms: 0, reason: 'test' }] },
      audio: { program_url: '/empty-audio.m4a' },
    });
    if (url.pathname === `/projects/${PROJECT}/timeline-state`) return json(200, {
      total_duration_ms: 10000, clips: [], topics: [], notes: notes.slice(),
    });
    if (url.pathname === `/projects/${PROJECT}/notes` && req.method === 'GET') return json(200, { notes: notes.slice() });
    if (url.pathname === `/projects/${PROJECT}/notes/n1` && req.method === 'DELETE') {
          notes.splice(0, 1);
          return json(204, {});
    }
    if (url.pathname === '/web/player.js') {
      res.writeHead(200, { 'Content-Type': 'text/javascript' });
      return res.end(fs.readFileSync(path.join(ROOT, 'player.js')));
    }
    if (url.pathname === '/web/styles.css') {
      res.writeHead(200, { 'Content-Type': 'text/css' });
      return res.end(fs.readFileSync(path.join(ROOT, 'styles.css')));
    }
    if (url.pathname === `/player/${PROJECT}` || url.pathname === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      return res.end(fs.readFileSync(path.join(ROOT, 'index.html')));
    }
    res.writeHead(404); res.end('not found');
  });
}

(async () => {
  const server = makeServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  const serverErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));
  page.on('response', (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  try {
    await page.goto(`http://127.0.0.1:${port}/player/${PROJECT}`);
    await page.waitForTimeout(250);

    try {
      await page.locator('.note-item').nth(0).waitFor({ timeout: 5000 });
    } catch (error) {
      throw new Error(`${error.message}; status=${await page.locator('#statusText').textContent()}; html=${await page.locator('#playerShell').innerHTML()}`);
    }
    assert.equal(await page.locator('.note-item').count(), 2, 'both reviewer notes render');
    assert.deepEqual(await page.locator('.note-item-author').allTextContents(), ['Reviewer Alpha', 'Reviewer Beta']);

    for (const width of [1920, 1440, 1280, 1024, 900, 800, 768, 640]) {
      await page.setViewportSize({ width, height: 900 });
      const layout = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      assert.ok(layout.scrollWidth <= layout.clientWidth, `horizontal overflow at ${width}px: ${JSON.stringify(layout)}`);
      const required = [
        '#playerShell .player-header', '#playerShell .player-controls', '#currentAngle', '#qualitySelect',
        '#backToAutoButton', '#syncMinus', '#syncOffsetDisplay', '#syncPlus', '#syncSave',
        '.cut-review-panel', '#cutSourceGroup', '.notes-panel', '#noteForm', '#noteBody',
        '#noteKind', '#noteSubmit', '.angle-panel', '#angleButtons', '.lut-panel',
        '#lutFile', '#defaultLutSelect', '#activateDefaultLut', '#deactivateDefaultLut',
        '.cut-params-panel', '#cutPresetSteady', '#cutPresetDirect', '#cutPresetLooser',
        '#regenerateCutBtn', '#exportFcpxmlBtn', '#exportEdlBtn',
      ];
      const controls = await page.evaluate((selectors) => selectors.map((selector) => {
        const el = document.querySelector(selector);
        if (!el) return { selector, missing: true };
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return { selector, display: style.display, visibility: style.visibility, width: rect.width, height: rect.height,
          left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
      }), required);
      for (const control of controls) {
        assert.equal(control.missing, undefined, `missing responsive control ${control.selector} at ${width}px`);
        assert.notEqual(control.display, 'none', `hidden responsive control ${control.selector} at ${width}px`);
        assert.notEqual(control.visibility, 'hidden', `invisible responsive control ${control.selector} at ${width}px`);
        assert.ok(control.width > 0 && control.height > 0, `zero-area responsive control ${control.selector} at ${width}px: ${JSON.stringify(control)}`);
        assert.ok(control.left >= -1 && control.right <= width + 1,
          `horizontally unreachable responsive control ${control.selector} at ${width}px: ${JSON.stringify(control)}`);
      }
      if (width >= 1024) {
        const geometry = await page.locator('.player-controls').evaluate((el) => ({
          width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height,
          syncWidth: el.querySelector('.sync-nudge').getBoundingClientRect().width,
          syncHeight: el.querySelector('.sync-nudge').getBoundingClientRect().height,
          wrap: getComputedStyle(el).flexWrap, syncWrap: getComputedStyle(el.querySelector('.sync-nudge')).flexWrap,
        }));
        assert.equal(geometry.wrap, 'nowrap', `wide controls wrap at ${width}px`);
        assert.equal(geometry.syncWrap, 'nowrap', `wide sync controls wrap at ${width}px`);
        if (width === 1024) {
          assert.ok(Math.abs(geometry.width - 844.08) < 0.5, `player-controls geometry changed at 1024px: ${JSON.stringify(geometry)}`);
          assert.ok(Math.abs(geometry.height - 56) < 0.5, `player-controls height changed at 1024px: ${JSON.stringify(geometry)}`);
          assert.ok(Math.abs(geometry.syncWidth - 388.48) < 0.5, `sync-nudge geometry changed at 1024px: ${JSON.stringify(geometry)}`);
          assert.ok(Math.abs(geometry.syncHeight - 40) < 0.5, `sync-nudge height changed at 1024px: ${JSON.stringify(geometry)}`);
        }
      }
    }

    const body = page.locator('.note-item-body').nth(0);
    assert.equal(await body.textContent(), '<script>window.__xss = true</script>');
    assert.equal(await page.evaluate(() => window.__xss), undefined, 'note script must not execute');
    assert.equal(await body.locator('script').count(), 0, 'note body must not create script elements');

    await page.locator('.note-marker').nth(1).click();
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#programAudio').evaluate((el) => el.currentTime), 5, 'marker seeks to note time');

    const deleteResponse = page.waitForResponse((response) => response.url().endsWith(`/projects/${PROJECT}/notes/n1`) && response.request().method() === 'DELETE');
    await page.locator('.note-item-delete').nth(0).click();
    await deleteResponse;
    await page.waitForFunction(() => document.querySelectorAll('.note-item').length === 1);
    await page.screenshot({ path: '/opt/data/workspace/AUTOEDIT/tests/browser/stage_7_4_delete-failure.png', fullPage: true });
    assert.equal(await page.locator('.note-item').count(), 1, 'deleted note leaves list');
    assert.equal(await page.locator('.note-marker').count(), 1, 'deleted note leaves timeline lane');
    assert.equal(consoleErrors.some((message) => message.startsWith('pageerror:')), false, `browser page errors: ${consoleErrors.join('; ')}`);
    assert.deepEqual(serverErrors, [], `browser HTTP >=500 errors: ${serverErrors.join('; ')}`);
    console.log('STAGE_7_4_XSS_GATE_PASS');
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((err) => { console.error(err.stack || err); process.exitCode = 1; });
