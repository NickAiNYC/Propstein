import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const PORT = 8997;
const viewerDir = path.resolve('viewer');

const mimeTypes = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml'
};

const server = http.createServer((req, res) => {
  const parsedUrl = new URL(req.url, `http://127.0.0.1:${PORT}`);
  let filePath = path.join(viewerDir, parsedUrl.pathname === '/' ? 'index.html' : parsedUrl.pathname);
  if (!fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end('Not Found');
    return;
  }
  const ext = path.extname(filePath);
  res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'application/octet-stream' });
  fs.createReadStream(filePath).pipe(res);
});

server.listen(PORT, async () => {
  console.log(`Test server running at http://127.0.0.1:${PORT}`);

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const DEBUG_PORT = 9236;
  const tmpDir = `/tmp/chrome-cp-test-${Date.now()}`;
  const chrome = spawn(chromePath, [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${tmpDir}`,
    '--disable-gpu',
    '--window-size=1280,880',
    `http://127.0.0.1:${PORT}/index.html`
  ]);

  await new Promise((r) => setTimeout(r, 2000));

  try {
    const listRes = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`);
    const tabs = await listRes.json();
    const pageTab = tabs.find((t) => t.type === 'page');
    console.log('Connecting to page:', pageTab.title);

    const ws = new WebSocket(pageTab.webSocketDebuggerUrl);
    await new Promise((resolve) => { ws.onopen = resolve; });

    let msgId = 0;
    const send = (method, params = {}) => new Promise((resolve) => {
      msgId++;
      const id = msgId;
      const handler = (evt) => {
        const data = JSON.parse(evt.data);
        if (data.id === id) {
          ws.removeEventListener('message', handler);
          resolve(data.result);
        }
      };
      ws.addEventListener('message', handler);
      ws.send(JSON.stringify({ id, method, params }));
    });

    await new Promise((r) => setTimeout(r, 1500));

    // 1. Audit Desktop Control Plane & Table
    const desktopAudit = await send('Runtime.evaluate', {
      expression: `(() => {
        const searchInput = document.getElementById('searchInput');
        const searchRect = searchInput ? searchInput.getBoundingClientRect() : null;

        const gateSteppers = document.getElementById('headerRiskSteppers');
        const liveWidget = document.getElementById('livePollingWidget');
        const timerText = document.getElementById('pollingTimerText')?.textContent;

        const table = document.querySelector('.slate-table');
        const headers = Array.from(document.querySelectorAll('#slateHead th')).map(th => ({
          text: th.innerText.replace(/\\s+/g, ' '),
          width: th.getBoundingClientRect().width
        }));

        const firstRowCells = Array.from(document.querySelectorAll('#slateRows tr:first-child td')).map(td => ({
          text: td.innerText.replace(/\\s+/g, ' ').slice(0, 30),
          width: td.getBoundingClientRect().width
        }));

        // Check Team Crests in Game Chips
        const gameChips = Array.from(document.querySelectorAll('.game-chip')).map(chip => {
          const imgs = Array.from(chip.querySelectorAll('img.crest-img')).map(img => img.src);
          return { text: chip.innerText.replace(/\\s+/g, ' '), crestCount: imgs.length, crests: imgs };
        });

        // Check Team Crests in Matchup column
        const matchupCrests = Array.from(document.querySelectorAll('.matchup-crests-row img.crest-img')).map(img => img.src).slice(0, 4);

        return {
          searchWidth: searchRect?.width,
          hasHeaderSteppers: Boolean(gateSteppers),
          hasLiveWidget: Boolean(liveWidget),
          timerText,
          headerCount: headers.length,
          headers,
          firstRowCellCount: firstRowCells.length,
          firstRowCells,
          gameChips: gameChips.slice(0, 4),
          matchupCrests
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Desktop Control Plane Audit:', JSON.stringify(desktopAudit.result.value, null, 2));

    // Desktop screenshot
    const shotDesktop = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('desktop_control_plane.png', Buffer.from(shotDesktop.data, 'base64'));
    console.log('==> Saved desktop_control_plane.png');

    // Test live polling manual click
    const pollClickRes = await send('Runtime.evaluate', {
      expression: `(() => {
        const manualBtn = document.getElementById('manualPollBtn');
        if (manualBtn) manualBtn.click();
        return {
          isSpinning: manualBtn?.classList.contains('is-spinning'),
          timerText: document.getElementById('pollingTimerText')?.textContent
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Manual Poll Trigger Test:', pollClickRes.result.value);

    // 2. Switch to Mobile Viewport (390 x 844 iPhone 14 Pro)
    await send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true
    });
    await new Promise((r) => setTimeout(r, 600));

    // Audit Mobile Layout
    const mobileAudit = await send('Runtime.evaluate', {
      expression: `(() => {
        const searchInput = document.getElementById('searchInput');
        const searchRect = searchInput ? searchInput.getBoundingClientRect() : null;

        const tableView = document.getElementById('tableView');
        const cardView = document.getElementById('cardView');

        const cards = Array.from(document.querySelectorAll('.mobile-quant-row'));
        const firstCard = cards[0];
        const cardCrest = firstCard?.querySelector('img.crest-img')?.src;
        const playerName = firstCard?.querySelector('.mq-player-name')?.textContent;
        const quantStrip = firstCard?.querySelector('.mq-line-2')?.innerText?.replace(/\\s+/g, ' ');

        return {
          searchWidth: searchRect?.width,
          isTableViewHidden: tableView ? (tableView.hidden || window.getComputedStyle(tableView).display === 'none') : false,
          isCardViewVisible: cardView ? (!cardView.hidden && window.getComputedStyle(cardView).display !== 'none') : false,
          cardCount: cards.length,
          firstCardPlayer: playerName,
          firstCardCrest: cardCrest,
          firstCardQuantStrip: quantStrip
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Mobile View Audit:', JSON.stringify(mobileAudit.result.value, null, 2));

    const shotMobile = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_orderbook.png', Buffer.from(shotMobile.data, 'base64'));
    console.log('==> Saved mobile_orderbook.png');

    // Click first card to inspect bottom sheet on mobile
    const bottomSheetAudit = await send('Runtime.evaluate', {
      expression: `(() => {
        const cards = Array.from(document.querySelectorAll('.mobile-quant-row'));
        if (cards[0]) cards[0].click();

        const dialog = document.getElementById('detailDialog');
        const dialogRect = dialog ? dialog.getBoundingClientRect() : null;
        const handle = dialog?.querySelector('.dialog-sheet-handle');
        const handleDisplay = handle ? window.getComputedStyle(handle).display : 'none';
        const modalCrest = dialog?.querySelector('.detail-title-row img.crest-img')?.src;

        return {
          isOpen: dialog ? dialog.open : false,
          dialogTop: dialogRect?.top,
          dialogBottom: dialogRect?.bottom,
          dialogWidth: dialogRect?.width,
          hasHandle: Boolean(handle),
          handleDisplay,
          modalCrest
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Mobile Bottom Sheet Audit:', JSON.stringify(bottomSheetAudit.result.value, null, 2));

    const shotBottomSheet = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_bottom_sheet.png', Buffer.from(shotBottomSheet.data, 'base64'));
    console.log('==> Saved mobile_bottom_sheet.png');

    ws.close();
  } catch (err) {
    console.error('Error in verification:', err);
  } finally {
    chrome.kill();
    server.close();
    process.exit(0);
  }
});
