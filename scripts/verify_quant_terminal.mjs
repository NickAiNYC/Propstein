import { spawn } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const PORT = 8995;
const viewerDir = path.resolve('viewer');

// 1. Static file server
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
  const chrome = spawn(chromePath, [
    '--headless=new',
    '--remote-debugging-port=9229',
    '--disable-gpu',
    '--window-size=1280,820',
    `http://127.0.0.1:${PORT}/index.html`
  ]);

  await new Promise((r) => setTimeout(r, 2000));

  try {
    const listRes = await fetch('http://127.0.0.1:9229/json');
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

    // Test 1: Desktop Layout & Above The Fold Real Estate
    const eval1 = await send('Runtime.evaluate', {
      expression: `(() => {
        const firstRow = document.querySelector('tr[data-testid="slate-row"]');
        const cmdBar = document.querySelector('.quant-command-bar');
        const bullet = document.querySelector('.bullet-container');
        const gateVal = document.getElementById('gateVal')?.textContent;
        const capVal = document.getElementById('capVal')?.textContent;
        const firstRowTop = firstRow ? Math.round(firstRow.getBoundingClientRect().top) : -1;
        return {
          hasCmdBar: Boolean(cmdBar),
          hasBullet: Boolean(bullet),
          firstRowTop,
          gateVal,
          capVal,
          activeRowsCount: document.querySelectorAll('tr[data-testid="slate-row"]').length
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Desktop Layout Evaluation:', eval1.result.value);

    // Test 2: Steppers
    await send('Runtime.evaluate', { expression: `document.getElementById('gatePlus').click();` });
    await new Promise((r) => setTimeout(r, 200));
    const eval2 = await send('Runtime.evaluate', {
      expression: `(() => ({ gateVal: document.getElementById('gateVal')?.textContent }))()`,
      returnByValue: true
    });
    console.log('==> Gate Stepper after click +:', eval2.result.value);

    // Test 3: Keyboard Navigation J/K & L key to Log Bet
    await send('Runtime.evaluate', {
      expression: `window.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }));`
    });
    await new Promise((r) => setTimeout(r, 200));
    const eval3 = await send('Runtime.evaluate', {
      expression: `(() => {
        const row = document.querySelector('tr[data-testid="slate-row"].keyboard-focus');
        return {
          hasFocusedRow: Boolean(row),
          player: row ? row.querySelector('.player-name')?.textContent?.trim() : null
        };
      })()`,
      returnByValue: true
    });
    console.log('==> J Navigation Evaluation:', eval3.result.value);

    // Test L Key to log bet
    await send('Runtime.evaluate', {
      expression: `window.dispatchEvent(new KeyboardEvent('keydown', { key: 'l', bubbles: true }));`
    });
    await new Promise((r) => setTimeout(r, 200));
    const eval4 = await send('Runtime.evaluate', {
      expression: `(() => {
        const portfolio = JSON.parse(localStorage.getItem('propwire_portfolio_ledger') || '[]');
        return {
          portfolioCount: portfolio.length,
          loggedPlayer: portfolio[0]?.player_name
        };
      })()`,
      returnByValue: true
    });
    console.log('==> L Key Log Bet Evaluation:', eval4.result.value);

    // Capture Desktop Screenshot
    const shot1 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('quant_terminal_desktop.png', Buffer.from(shot1.data, 'base64'));
    console.log('==> Saved quant_terminal_desktop.png');

    // Test 4: Mobile Viewport 390x844 & 76px Order-Book Rows
    await send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 3,
      mobile: true
    });
    await send('Runtime.evaluate', {
      expression: `document.querySelector('.view-switch button[data-view="cards"]').click();`
    });
    await new Promise((r) => setTimeout(r, 600));

    const evalMobile = await send('Runtime.evaluate', {
      expression: `(() => {
        const cards = document.querySelectorAll('.mobile-quant-row');
        const first = cards[0];
        const l1 = first?.querySelector('.mq-line-1');
        const l2 = first?.querySelector('.mq-line-2');
        return {
          mobileCardCount: cards.length,
          firstCardHeight: first ? Math.round(first.getBoundingClientRect().height) : -1,
          l1H: l1 ? Math.round(l1.getBoundingClientRect().height) : -1,
          l2H: l2 ? Math.round(l2.getBoundingClientRect().height) : -1,
          l1Children: l1 ? Array.from(l1.children).map(c => ({ cls: c.className, h: Math.round(c.getBoundingClientRect().height), w: Math.round(c.getBoundingClientRect().width) })) : [],
          l2Children: l2 ? Array.from(l2.children).map(c => ({ cls: c.className, h: Math.round(c.getBoundingClientRect().height), w: Math.round(c.getBoundingClientRect().width) })) : [],
          idGroup: l1?.querySelector('.mq-id-group') ? Array.from(l1.querySelector('.mq-id-group').children).map(c => ({ cls: c.className, h: Math.round(c.getBoundingClientRect().height), w: Math.round(c.getBoundingClientRect().width) })) : [],
          hasLine2: first ? Boolean(first.querySelector('.mq-line-2')) : false,
          bookLine: first ? first.querySelector('.mq-book-line')?.textContent : null,
          fairModel: first ? first.querySelector('.mq-model-nums')?.textContent : null,
          stakeText: first ? first.querySelector('.mq-stake-val')?.textContent : null
        };
      })()`,
      returnByValue: true
    });
    console.log('==> Mobile Evaluation:', JSON.stringify(evalMobile.result.value, null, 2));

    const shot2 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('quant_terminal_mobile.png', Buffer.from(shot2.data, 'base64'));
    console.log('==> Saved quant_terminal_mobile.png');

    ws.close();
  } catch (err) {
    console.error('Error during verification:', err);
  } finally {
    chrome.kill();
    server.close();
    process.exit(0);
  }
});
