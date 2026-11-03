import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const PORT = 8996;
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
  console.log(`Server listening at http://127.0.0.1:${PORT}`);

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const DEBUG_PORT = 9235;
  const tmpDir = `/tmp/chrome-test-${Date.now()}`;
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
    console.log('Connecting to page:', pageTab.title, pageTab.url);

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

    // Test A.J. Brown Inspector Modal
    const ajTest = await send('Runtime.evaluate', {
      expression: `(() => {
        // Find A.J. Brown
        const rows = Array.from(document.querySelectorAll('tr[data-testid="slate-row"]'));
        const ajRow = rows.find(r => r.textContent.includes('A.J. Brown')) || rows[0];
        if (ajRow) ajRow.click();

        const dialog = document.getElementById('detailDialog');
        const isOpen = dialog ? dialog.open : false;

        const title = document.getElementById('detailTitle')?.innerText?.replace(/\\s+/g, ' ');
        const simTargets = document.getElementById('simTargetsVal')?.textContent;
        const simYards = document.getElementById('simYardsVal')?.textContent;
        const simEdge = document.getElementById('simEdgeVal')?.textContent;
        const shareVal = document.getElementById('scenarioShareVal')?.textContent;
        const rippleText = document.getElementById('teammateRipplePreview')?.innerText?.replace(/\\s+/g, ' ');
        const gateBadge = document.getElementById('kellyGateBadge')?.textContent;
        const kellyDollars = document.getElementById('kellyWagerDollars')?.textContent;
        const rulerCard = document.querySelector('.quant-ruler-card');
        const telemetry = document.querySelector('.telemetry-grid');
        const bridge = document.querySelector('.bridge-body');
        const ticketBox = document.querySelector('.execution-ticket-box');
        const copyReceiptBtn = document.getElementById('copyReceiptBtn');
        const receiptHash = copyReceiptBtn?.getAttribute('data-receipt');

        // Check invalidation text
        const sections = Array.from(dialog.querySelectorAll('.detail-section'));
        const invSec = sections.find(s => s.querySelector('h3')?.textContent.includes('invalidate'));
        const invText = invSec ? invSec.querySelector('p')?.textContent : '';

        return {
          isOpen,
          title,
          simTargets,
          simYards,
          simEdge,
          shareVal,
          rippleText,
          gateBadge,
          kellyDollars,
          hasRuler: Boolean(rulerCard),
          hasTelemetry: Boolean(telemetry),
          hasBridge: Boolean(bridge),
          hasTicketBox: Boolean(ticketBox),
          receiptHash,
          invText
        };
      })()`,
      returnByValue: true
    });
    console.log('==> A.J. Brown Modal Evaluation:', JSON.stringify(ajTest.result.value, null, 2));

    // Test Gate Override click
    const overrideTest = await send('Runtime.evaluate', {
      expression: `(() => {
        const btn = document.getElementById('overrideGateBtn');
        if (btn) btn.click();
        return {
          newBadge: document.getElementById('kellyGateBadge')?.textContent,
          newDollars: document.getElementById('kellyWagerDollars')?.textContent
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Gate Override Click Evaluation:', overrideTest.result.value);

    // Test slider move to simulate injury vacancy (target share drops)
    const sliderTest = await send('Runtime.evaluate', {
      expression: `(() => {
        const slider = document.getElementById('targetShareSlider');
        if (slider) {
          slider.value = '0.18';
          slider.dispatchEvent(new Event('input', { bubbles: true }));
        }
        return {
          simYards: document.getElementById('simYardsVal')?.textContent,
          simEdge: document.getElementById('simEdgeVal')?.textContent,
          rippleText: document.getElementById('teammateRipplePreview')?.innerText?.replace(/\\s+/g, ' ')
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Slider to 18% Evaluation:', sliderTest.result.value);

    // Test Inline Execution Ticket Confirm Log
    const ticketTest = await send('Runtime.evaluate', {
      expression: `(() => {
        const lineInput = document.getElementById('ticketLineInput');
        const oddsInput = document.getElementById('ticketOddsInput');
        const stakeInput = document.getElementById('ticketStakeInput');
        const confirmBtn = document.getElementById('ticketConfirmBtn');

        if (lineInput) lineInput.value = '68.5';
        if (oddsInput) oddsInput.value = '-110';
        if (stakeInput) stakeInput.value = '150';
        if (confirmBtn) confirmBtn.click();

        const portfolio = JSON.parse(localStorage.getItem('propwire_portfolio_ledger') || '[]');
        return {
          portfolioLen: portfolio.length,
          loggedBet: portfolio[portfolio.length - 1],
          buttonText: document.getElementById('ticketConfirmBtn')?.textContent?.trim()
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Execution Ticket Log Test:', JSON.stringify(ticketTest.result.value, null, 2));

    // Capture screenshot of A.J. Brown modal (top view)
    const shot1 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('modal_aj_brown.png', Buffer.from(shot1.data, 'base64'));
    console.log('==> Saved modal_aj_brown.png');

    // Scroll #detailContent down and capture lower half (2-col grid & execution ticket)
    await send('Runtime.evaluate', {
      expression: `(() => {
        const el = document.getElementById('detailContent');
        if (el) el.scrollTop = 420;
      })()`
    });
    await new Promise((r) => setTimeout(r, 300));
    const shot1b = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('modal_aj_brown_scrolled.png', Buffer.from(shot1b.data, 'base64'));
    console.log('==> Saved modal_aj_brown_scrolled.png');

    // Test Amon-Ra St. Brown (Dome check)
    const domeTest = await send('Runtime.evaluate', {
      expression: `(() => {
        // Close modal
        document.getElementById('detailDialog').close();
        const rows = Array.from(document.querySelectorAll('tr[data-testid="slate-row"]'));
        const amonRow = rows.find(r => r.textContent.includes('Amon-Ra St. Brown'));
        if (amonRow) amonRow.click();

        const dialog = document.getElementById('detailDialog');
        const sections = Array.from(dialog.querySelectorAll('.detail-section'));
        const invSec = sections.find(s => s.querySelector('h3')?.textContent.includes('invalidate'));
        const invText = invSec ? invSec.querySelector('p')?.textContent : '';

        return {
          playerName: document.getElementById('detailTitle')?.innerText?.replace(/\\s+/g, ' '),
          invText
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Amon-Ra Dome Test:', domeTest.result.value);

    const shot2 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('modal_amon_ra.png', Buffer.from(shot2.data, 'base64'));
    console.log('==> Saved modal_amon_ra.png');

    ws.close();
  } catch (err) {
    console.error('Error during verification:', err);
  } finally {
    chrome.kill();
    server.close();
    process.exit(0);
  }
});
