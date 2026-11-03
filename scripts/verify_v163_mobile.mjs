import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

const ARTIFACTS_DIR = '/Users/nick/.gemini/antigravity-ide/brain/e6a06847-5d35-427f-8387-bb239bf470ec';
const VIEWER_DIR = path.resolve('viewer');

function createStaticServer(port = 4173) {
  const mimeTypes = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon'
  };

  const server = http.createServer((req, res) => {
    let reqPath = req.url.split('?')[0];
    if (reqPath === '/') reqPath = '/index.html';
    const filePath = path.join(VIEWER_DIR, reqPath);

    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      const ext = path.extname(filePath);
      res.writeHead(200, {
        'Content-Type': mimeTypes[ext] || 'application/octet-stream',
        'Access-Control-Allow-Origin': '*'
      });
      fs.createReadStream(filePath).pipe(res);
    } else {
      res.writeHead(404);
      res.end('Not found');
    }
  });

  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

async function main() {
  const isProd = process.argv.includes('--prod');
  const targetUrl = isProd ? 'https://propwire.vercel.app/' : 'http://127.0.0.1:4173/';
  let server = null;

  if (!isProd) {
    console.log('Starting local server on http://127.0.0.1:4173...');
    server = await createStaticServer(4173);
  } else {
    console.log('Verifying LIVE PRODUCTION on https://propwire.vercel.app/ (iPhone 390x844)...');
  }

  console.log('Launching headless Chrome with iPhone 390x844 viewport...');
  const tmpDir = `/tmp/chrome-mobile-v163-${Date.now()}`;
  fs.mkdirSync(tmpDir, { recursive: true });

  const chromeProc = spawn(
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    [
      '--headless=new',
      '--remote-debugging-port=9336',
      '--window-size=390,844',
      `--user-data-dir=${tmpDir}`,
      '--disable-gpu',
      targetUrl
    ],
    { stdio: 'ignore' }
  );

  try {
    let connected = false;
    let pageTab = null;
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 300));
      try {
        const listRes = await fetch('http://127.0.0.1:9336/json');
        const tabs = await listRes.json();
        pageTab = tabs.find((t) => t.type === 'page' && (t.url.includes('4173') || t.url.includes('propwire.vercel.app')));
        if (pageTab && pageTab.webSocketDebuggerUrl) {
          connected = true;
          break;
        }
      } catch (e) {}
    }

    if (!connected || !pageTab) {
      throw new Error('Could not connect to headless Chrome on port 9335');
    }

    console.log('Connected to CDP:', pageTab.webSocketDebuggerUrl);
    const ws = new WebSocket(pageTab.webSocketDebuggerUrl);
    await new Promise((resolve) => { ws.onopen = resolve; });

    let msgId = 0;
    const send = (method, params = {}) => new Promise((resolve) => {
      msgId++;
      const id = msgId;
      const handler = (evt) => {
        const msg = JSON.parse(evt.data);
        if (msg.id === id) {
          ws.removeEventListener('message', handler);
          resolve(msg.result);
        }
      };
      ws.addEventListener('message', handler);
      ws.send(JSON.stringify({ id, method, params }));
    });

    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true
    });

    // Wait 2.5s for data fetch and initial render
    await new Promise((r) => setTimeout(r, 2500));

    // 1. Evaluate Hero Card & Brand Blue elements
    const heroEval = await send('Runtime.evaluate', {
      expression: `(() => {
        const heroVal = document.querySelector('.hero-metric-val')?.textContent?.trim() || '';
        const heroSub = document.querySelector('.hero-metric-sub')?.textContent?.trim() || '';
        const heroPill = document.querySelector('.hero-card-status-pill')?.textContent?.trim() || '';
        const hasResearchPill = document.querySelector('.hero-card-status-pill')?.classList.contains('research-pill');
        const dqBanner = document.querySelector('.data-quality-banner');
        const dqText = dqBanner?.textContent?.trim() || '';
        const dqHasWarn = dqBanner?.classList.contains('warn');
        const commandRow = document.querySelector('.pw-command-row');
        const scrollWidth = commandRow ? commandRow.scrollWidth : 0;
        const clientWidth = commandRow ? commandRow.clientWidth : 0;

        return {
          heroVal,
          heroSub,
          heroPill,
          hasResearchPill,
          dqText,
          dqHasWarn,
          scrollWidth,
          clientWidth,
          filterScrollable: scrollWidth > clientWidth
        };
      })()`,
      returnByValue: true
    });

    console.log('Hero & Layout Evaluation:', JSON.stringify(heroEval.result.value, null, 2));

    // Capture Screen 1: Slate in Research Mode
    console.log('Capturing mobile_slate_v163.png...');
    const shot1 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(ARTIFACTS_DIR, 'mobile_slate_v163.png'), Buffer.from(shot1.data, 'base64'));

    // 2. Click Watchlist Tab
    console.log('Clicking Watchlist tab...');
    await send('Runtime.evaluate', {
      expression: `(() => {
        const wl = document.querySelector('#bottomNavWatchlist');
        if (wl) wl.click();
      })()`
    });
    await new Promise((r) => setTimeout(r, 1000));

    // Evaluate Watchlist Empty State
    const watchlistEval = await send('Runtime.evaluate', {
      expression: `(() => {
        const wrap = document.querySelector('.watchlist-empty-wrap');
        const title = wrap ? wrap.querySelector('.anti-tout-title')?.textContent?.trim() : '';
        const sub = wrap ? wrap.querySelector('.anti-tout-desc')?.textContent?.trim() : '';
        const suggestions = document.querySelectorAll('.watchlist-suggest-item');
        const names = Array.from(suggestions).map(s => s.querySelector('.watchlist-suggest-name')?.textContent?.trim());
        const hasBrowseBtn = !!document.querySelector('#watchlistBrowseBtn');

        return {
          hasEmptyWrap: !!wrap,
          title,
          sub,
          suggestionCount: suggestions.length,
          names,
          hasBrowseBtn
        };
      })()`,
      returnByValue: true
    });

    console.log('Watchlist Evaluation:', JSON.stringify(watchlistEval.result.value, null, 2));

    // Capture Screen 2: Watchlist Onboarding
    console.log('Capturing mobile_watchlist_onboarding_v163.png...');
    const shot2 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(ARTIFACTS_DIR, 'mobile_watchlist_onboarding_v163.png'), Buffer.from(shot2.data, 'base64'));

    // 3. Test Clicking 1st Suggested Player Star Button
    console.log('Clicking star on first suggested player...');
    const starClickRes = await send('Runtime.evaluate', {
      expression: `(() => {
        const starBtn = document.querySelector('.watchlist-suggest-item .star-btn');
        if (starBtn) {
          starBtn.click();
          return { clicked: true, playerId: starBtn.dataset.watchPlayer };
        }
        return { clicked: false };
      })()`,
      returnByValue: true
    });
    console.log('Star click result:', starClickRes.result.value);
    await new Promise((r) => setTimeout(r, 1000));

    // Verify watchlist now has 1 row
    const postStarEval = await send('Runtime.evaluate', {
      expression: `(() => {
        const cardCount = document.querySelectorAll('.mobile-quant-row').length;
        const resultCountText = document.querySelector('#resultCount')?.textContent?.trim() || '';
        return { cardCount, resultCountText };
      })()`,
      returnByValue: true
    });
    console.log('Post-Star Watchlist Rows:', JSON.stringify(postStarEval.result.value, null, 2));

    // Capture Screen 3: Watchlist with 1 starred player
    console.log('Capturing mobile_watchlist_populated_v163.png...');
    const shot3 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(ARTIFACTS_DIR, 'mobile_watchlist_populated_v163.png'), Buffer.from(shot3.data, 'base64'));

    // 4. Test Unstarring to return to empty state
    console.log('Unstarring player to test Browse CTA...');
    await send('Runtime.evaluate', {
      expression: `(() => {
        const starBtn = document.querySelector('.star-btn.starred');
        if (starBtn) starBtn.click();
      })()`
    });
    await new Promise((r) => setTimeout(r, 800));

    // 5. Test Clicking "Browse Top Projections ->" CTA
    console.log('Clicking "Browse Top Projections ->" CTA...');
    await send('Runtime.evaluate', {
      expression: `(() => {
        const browseBtn = document.querySelector('#watchlistBrowseBtn');
        if (browseBtn) browseBtn.click();
      })()`
    });
    await new Promise((r) => setTimeout(r, 1000));

    const postBrowseEval = await send('Runtime.evaluate', {
      expression: `(() => {
        const activeTab = document.querySelector('.bottom-nav-item.active')?.id;
        const cardCount = document.querySelectorAll('.mobile-quant-row').length;
        return { activeTab, cardCount };
      })()`,
      returnByValue: true
    });

    console.log('Post-Browse State:', JSON.stringify(postBrowseEval.result.value, null, 2));

    ws.close();
    console.log('Mobile verification completed successfully!');
  } finally {
    chromeProc.kill('SIGKILL');
    await new Promise((r) => setTimeout(r, 600));
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch (e) {}
    if (server) server.close();
  }
}

main().catch((err) => {
  console.error('Mobile verification failed:', err);
  process.exit(1);
});
