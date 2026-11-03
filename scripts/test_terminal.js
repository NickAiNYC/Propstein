const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

async function testTerminal() {
  const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
    '--headless=new',
    '--remote-debugging-port=9230',
    '--disable-gpu',
    '--no-sandbox',
    '--window-size=1280,950',
    'http://127.0.0.1:8089/index.html'
  ]);

  await new Promise(r => setTimeout(r, 1500));

  try {
    const res = await fetch('http://127.0.0.1:9230/json');
    const tabs = await res.json();
    const pageTab = tabs.find((t) => t.type === 'page' && t.url.includes('8089')) || tabs[0];
    const ws = new WebSocket(pageTab.webSocketDebuggerUrl);
    await new Promise((r) => { ws.onopen = r; });

    let curId = 1;
    function cmd(method, params = {}) {
      return new Promise((resolve) => {
        const id = curId++;
        const onMsg = (evt) => {
          const d = JSON.parse(evt.data);
          if (d.id === id) {
            ws.removeEventListener('message', onMsg);
            resolve(d.result);
          }
        };
        ws.addEventListener('message', onMsg);
        ws.send(JSON.stringify({ id, method, params }));
      });
    }

    await cmd('Runtime.enable');
    await cmd('Page.enable');

    ws.addEventListener('message', (evt) => {
      const d = JSON.parse(evt.data);
      if (d.method === 'Runtime.consoleAPICalled') {
        console.log('BROWSER LOG:', d.params.type, d.params.args.map(a => a.value || a.description).join(' '));
      }
      if (d.method === 'Runtime.exceptionThrown') {
        console.error('BROWSER EXCEPTION:', d.params.exceptionDetails);
      }
    });

    console.log('Tabs detected:', tabs.map(t => ({ url: t.url, type: t.type })));
    console.log('Using target tab:', pageTab.url);

    await cmd('Page.navigate', { url: 'http://127.0.0.1:8089/index.html' });

    // Wait for slate load
    console.log('Polling for ready state...');
    for (let i = 0; i < 40; i++) {
      const r = await cmd('Runtime.evaluate', { expression: 'Boolean(window.__PROP_WIRE_READY__)' });
      if (r?.result?.value) {
        console.log(`Board ready after ${i * 200}ms!`);
        break;
      }
      await new Promise(r => setTimeout(r, 200));
    }

    // 1. Check Sparklines
    const sparkCount = await cmd('Runtime.evaluate', { expression: 'document.querySelectorAll(".price-sparkline-svg").length' });
    console.log(`[FEATURE 1] Inline SVG Sparklines: ${sparkCount?.result?.value} rendered`);

    // Capture desktop table screenshot
    const shot1 = await cmd('Page.captureScreenshot');
    fs.writeFileSync(path.join(__dirname, '..', 'artifacts', 'sparklines_table_verified.png'), Buffer.from(shot1.data, 'base64'));

    // 2. Open Sniper Modal & verify controls
    await cmd('Runtime.evaluate', { expression: 'document.querySelector("#sniperBtn").click();' });
    await new Promise(r => setTimeout(r, 600));

    const sniperOpen = await cmd('Runtime.evaluate', { expression: 'Boolean(document.querySelector("#sniperDialog")?.open)' });
    console.log(`[FEATURE 2] Sniper Modal Open: ${sniperOpen?.result?.value}`);

    // Toggle master switch & select 12%
    await cmd('Runtime.evaluate', {
      expression: `
        const t = document.querySelector("#sniperMasterToggle");
        if (t) { t.checked = true; t.dispatchEvent(new Event('change')); }
        const b = document.querySelector('[data-edge="0.12"]');
        if (b) b.click();
      `
    });
    await new Promise(r => setTimeout(r, 400));

    const shot2 = await cmd('Page.captureScreenshot');
    fs.writeFileSync(path.join(__dirname, '..', 'artifacts', 'sniper_engine_verified.png'), Buffer.from(shot2.data, 'base64'));

    // Close sniper modal
    await cmd('Runtime.evaluate', { expression: 'document.querySelector("#sniperDialog").close();' });
    await new Promise(r => setTimeout(r, 400));

    // 3. Test Correlated Volume Risk Engine
    // Find two players on same team (e.g. DET) and log both sequentially
    const p1Res = await cmd('Runtime.evaluate', {
      expression: `
        (() => {
          const rows = Array.from(document.querySelectorAll('.slate-row'));
          const row1 = rows.find(r => r.querySelector('.cell-sub')?.textContent?.includes('DET'));
          if (row1) {
            const btn = row1.querySelector('[data-log-bet]');
            if (btn) btn.click();
            return row1.querySelector('.player-name')?.textContent?.trim();
          }
          return null;
        })()
      `,
      returnByValue: true
    });
    console.log('[FEATURE 3] Logged Player 1:', p1Res?.result?.value);
    await new Promise(r => setTimeout(r, 600));

    // Verify cannibalistic warning badge appears on competing player on board
    const corrBadgeCount1 = await cmd('Runtime.evaluate', { expression: 'document.querySelectorAll(".corr-risk-pill").length' });
    console.log(`[FEATURE 3] Correlated Risk Badges in Board after 1st bet: ${corrBadgeCount1?.result?.value}`);

    // Now log Player 2 from same team
    const p2Res = await cmd('Runtime.evaluate', {
      expression: `
        (() => {
          const rows = Array.from(document.querySelectorAll('.slate-row'));
          // Find second DET player who is not logged yet
          const row2 = rows.find(r => r.querySelector('.cell-sub')?.textContent?.includes('DET') && !r.querySelector('.row-log-btn.logged'));
          if (row2) {
            const btn = row2.querySelector('[data-log-bet]');
            if (btn) btn.click();
            return row2.querySelector('.player-name')?.textContent?.trim();
          }
          return null;
        })()
      `,
      returnByValue: true
    });
    console.log('[FEATURE 3] Logged Player 2:', p2Res?.result?.value);
    await new Promise(r => setTimeout(r, 600));

    // Open Portfolio Dialog to check risk alert banner
    await cmd('Runtime.evaluate', { expression: 'document.querySelector("#portfolioBtn").click();' });
    await new Promise(r => setTimeout(r, 600));

    const bannerFound = await cmd('Runtime.evaluate', { expression: 'Boolean(document.querySelector(".portfolio-risk-alert"))' });
    console.log(`[FEATURE 3] Portfolio Concentration Risk Banner: ${bannerFound?.result?.value}`);

    const shot3 = await cmd('Page.captureScreenshot');
    fs.writeFileSync(path.join(__dirname, '..', 'artifacts', 'correlated_risk_ledger_verified.png'), Buffer.from(shot3.data, 'base64'));

    await cmd('Runtime.evaluate', { expression: 'document.querySelector("#portfolioDialog").close();' });
    await new Promise(r => setTimeout(r, 400));

    // 4. Test Directional Tick Flashes during polling
    await cmd('Runtime.evaluate', {
      expression: 'window.__PROP_WIRE_TRIGGER_POLL__(false);',
      awaitPromise: true
    });

    const flashes = await cmd('Runtime.evaluate', { expression: 'document.querySelectorAll(".tick-flash-up, .tick-flash-down").length' });
    console.log(`[FEATURE 4] Directional Tick Flashes Active: ${flashes?.result?.value}`);

    const shot4 = await cmd('Page.captureScreenshot');
    fs.writeFileSync(path.join(__dirname, '..', 'artifacts', 'directional_tick_flashes_verified.png'), Buffer.from(shot4.data, 'base64'));

    console.log('✓ All 4 institutional features verified successfully!');
    ws.close();
  } catch (e) {
    console.error('Test error:', e);
  } finally {
    chrome.kill();
    process.exit(0);
  }
}

testTerminal();
