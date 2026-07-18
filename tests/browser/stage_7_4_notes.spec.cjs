const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/opt/data/workspace/AUTOEDIT/.hermes/watchdog-browser/node_modules/playwright');

const ROOT = '/opt/data/workspace/AUTOEDIT/src/autoedit/web';
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
      cut: { clips: [{ angle_id: 'a', timeline_in_ms: 0, timeline_out_ms: 10000, src_in_ms: 0, reason: 'test' }] },
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
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

  try {
    await page.goto(`http://127.0.0.1:${port}/player/${PROJECT}`);
    await page.locator('.note-item').nth(0).waitFor();
    assert.equal(await page.locator('.note-item').count(), 2, 'both reviewer notes render');
    assert.deepEqual(await page.locator('.note-item-author').allTextContents(), ['Reviewer Alpha', 'Reviewer Beta']);

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
    assert.deepEqual(consoleErrors, [], `browser console errors: ${consoleErrors.join('; ')}`);
    console.log('STAGE_7_4_XSS_GATE_PASS');
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((err) => { console.error(err.stack || err); process.exitCode = 1; });
