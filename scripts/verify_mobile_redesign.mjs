import fs from 'node:fs';

async function run() {
  const DEBUG_PORT = 9222;
  try {
    const listRes = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`);
    const tabs = await listRes.json();
    const pageTab = tabs.find((t) => t.type === 'page' && t.url.includes('4173'));
    if (!pageTab) {
      console.error('Could not find PropWire page on port 9222');
      process.exit(1);
    }
    console.log('Connecting to page:', pageTab.title, pageTab.webSocketDebuggerUrl);

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

    console.log('Reloading page...');
    await send('Page.reload', { ignoreCache: true });
    await new Promise((r) => setTimeout(r, 1500));

    // Apply iPhone 390 x 844 viewport
    await send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true
    });
    await send('Runtime.evaluate', { expression: 'window.scrollTo(0, 0);' });
    await new Promise((r) => setTimeout(r, 600));

    const clip = { x: 0, y: 0, width: 390, height: 844, scale: 2 };

    // Capture 1: Slate Mobile View
    console.log('Capturing Screenshot 1: mobile_slate_redesign.png...');
    const shot1 = await send('Page.captureScreenshot', { format: 'png', clip });
    fs.writeFileSync('mobile_slate_redesign.png', Buffer.from(shot1.data, 'base64'));

    // Capture 2: Detail Sheet (Inspect first card)
    console.log('Opening player detail bottom sheet...');
    await send('Runtime.evaluate', {
      expression: `
        const firstCard = document.querySelector('.mobile-quant-row');
        if (firstCard) firstCard.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing Screenshot 2: mobile_detail_redesign.png...');
    const shot2 = await send('Page.captureScreenshot', { format: 'png', clip });
    fs.writeFileSync('mobile_detail_redesign.png', Buffer.from(shot2.data, 'base64'));

    // Close detail dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#detailDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });
    await new Promise((r) => setTimeout(r, 500));

    // Capture 3: Settings & Risk Bottom Sheet
    console.log('Opening settings & risk bottom sheet...');
    await send('Runtime.evaluate', {
      expression: `
        const menuBtn = document.querySelector('#mobileMenuBtn');
        if (menuBtn) menuBtn.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing Screenshot 3: mobile_settings_redesign.png...');
    const shot3 = await send('Page.captureScreenshot', { format: 'png', clip });
    fs.writeFileSync('mobile_settings_redesign.png', Buffer.from(shot3.data, 'base64'));

    // Close settings dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#settingsDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });
    await new Promise((r) => setTimeout(r, 500));

    // Capture 4: Personal CLV Ledger Bottom Sheet via Bottom Nav
    console.log('Opening ledger bottom sheet via bottom nav...');
    await send('Runtime.evaluate', {
      expression: `
        const ledgerTab = document.querySelector('#bottomNavLedger');
        if (ledgerTab) ledgerTab.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing Screenshot 4: mobile_ledger_redesign.png...');
    const shot4 = await send('Page.captureScreenshot', { format: 'png', clip });
    fs.writeFileSync('mobile_ledger_redesign.png', Buffer.from(shot4.data, 'base64'));

    // Close ledger dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#portfolioDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });
    await new Promise((r) => setTimeout(r, 500));

    // Capture 5: More Filters Bottom Sheet
    console.log('Opening more filters bottom sheet...');
    await send('Runtime.evaluate', {
      expression: `
        const moreBtn = document.querySelector('#moreFiltersBtn');
        if (moreBtn) moreBtn.click();
      `
    });
    await new Promise((r) => setTimeout(r, 1000));
    console.log('Capturing Screenshot 5: mobile_more_filters_redesign.png...');
    const shot5 = await send('Page.captureScreenshot', { format: 'png', clip });
    fs.writeFileSync('mobile_more_filters_redesign.png', Buffer.from(shot5.data, 'base64'));

    // Close more filters dialog
    await send('Runtime.evaluate', {
      expression: `
        const dlg = document.querySelector('#moreFiltersDialog');
        if (dlg && dlg.open) dlg.close();
      `
    });

    console.log('All mobile screenshots captured successfully!');
    ws.close();
  } catch (err) {
    console.error('Error during mobile verification:', err);
  }
}

run();
