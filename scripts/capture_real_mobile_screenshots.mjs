import { spawn } from 'node:child_process';
import fs from 'node:fs';

async function main() {
  console.log('Launching headless Chrome with exact 390x844 iPhone viewport...');
  const tmpDir = `/tmp/chrome-mobile-${Date.now()}`;
  fs.mkdirSync(tmpDir, { recursive: true });

  const chromeProc = spawn(
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    [
      '--headless=new',
      '--remote-debugging-port=9333',
      '--window-size=390,844',
      `--user-data-dir=${tmpDir}`,
      '--disable-gpu',
      'http://127.0.0.1:4173/'
    ],
    { stdio: 'ignore' }
  );

  try {
    // Wait for debugging port
    let connected = false;
    let pageTab = null;
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 300));
      try {
        const listRes = await fetch('http://127.0.0.1:9333/json');
        const tabs = await listRes.json();
        pageTab = tabs.find((t) => t.type === 'page' && t.url.includes('4173'));
        if (pageTab && pageTab.webSocketDebuggerUrl) {
          connected = true;
          break;
        }
      } catch (e) {}
    }

    if (!connected || !pageTab) {
      throw new Error('Could not connect to headless Chrome on port 9333');
    }

    console.log('Connected to headless Chrome:', pageTab.webSocketDebuggerUrl);
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

    // Wait for initial render
    await new Promise((r) => setTimeout(r, 2000));

    // Ensure scroll is at 0
    await send('Runtime.evaluate', { expression: 'window.scrollTo(0, 0);' });
    await new Promise((r) => setTimeout(r, 300));

    // 1. Capture Slate Mobile View
    console.log('Capturing mobile_slate_redesign.png...');
    const shot1 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_slate_redesign.png', Buffer.from(shot1.data, 'base64'));

    // 2. Open Detail View (first player card)
    console.log('Opening player detail bottom sheet...');
    await send('Runtime.evaluate', {
      expression: `
        const firstCard = document.querySelector('.mobile-quant-row');
        if (firstCard) firstCard.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing mobile_detail_redesign.png...');
    const shot2 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_detail_redesign.png', Buffer.from(shot2.data, 'base64'));

    // Close detail dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#detailDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });
    await new Promise((r) => setTimeout(r, 400));

    // 3. Open Settings & Risk Bottom Sheet
    console.log('Opening settings & risk bottom sheet...');
    await send('Runtime.evaluate', {
      expression: `
        const menuBtn = document.querySelector('#mobileMenuBtn');
        if (menuBtn) menuBtn.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing mobile_settings_redesign.png...');
    const shot3 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_settings_redesign.png', Buffer.from(shot3.data, 'base64'));

    // Close settings dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#settingsDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });
    await new Promise((r) => setTimeout(r, 400));

    // 4. Open Personal CLV Ledger Bottom Sheet via Bottom Nav
    console.log('Opening ledger bottom sheet via bottom nav...');
    await send('Runtime.evaluate', {
      expression: `
        const ledgerTab = document.querySelector('#bottomNavLedger');
        if (ledgerTab) ledgerTab.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing mobile_ledger_redesign.png...');
    const shot4 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_ledger_redesign.png', Buffer.from(shot4.data, 'base64'));

    // Close ledger dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#portfolioDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });
    await new Promise((r) => setTimeout(r, 400));

    // 5. Open More Filters Bottom Sheet
    console.log('Opening more filters bottom sheet...');
    await send('Runtime.evaluate', {
      expression: `
        const moreBtn = document.querySelector('#moreFiltersBtn');
        if (moreBtn) moreBtn.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing mobile_more_filters_redesign.png...');
    const shot5 = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('mobile_more_filters_redesign.png', Buffer.from(shot5.data, 'base64'));

    console.log('All real mobile screenshots captured successfully!');
    ws.close();
  } finally {
    chromeProc.kill('SIGKILL');
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error('Error running mobile capture:', err);
  process.exit(1);
});
