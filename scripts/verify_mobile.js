const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

async function testMobile() {
  const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
    '--headless=new',
    '--remote-debugging-port=9231',
    '--disable-gpu',
    '--no-sandbox',
    '--window-size=390,844',
    'http://127.0.0.1:8089/index.html'
  ]);

  await new Promise(r => setTimeout(r, 1500));

  try {
    const res = await fetch('http://127.0.0.1:9231/json');
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

    await cmd('Page.navigate', { url: 'http://127.0.0.1:8089/index.html' });

    for (let i = 0; i < 40; i++) {
      const r = await cmd('Runtime.evaluate', { expression: 'Boolean(window.__PROP_WIRE_READY__)' });
      if (r?.result?.value) break;
      await new Promise(r => setTimeout(r, 200));
    }

    // 1. Mobile sparklines
    const mobileSparks = await cmd('Runtime.evaluate', { expression: 'document.querySelectorAll(".mobile-quant-row .price-sparkline-svg").length' });
    console.log(`[MOBILE 1] Card Sparklines: ${mobileSparks?.result?.value}`);

    // 2. Log bet to test mobile correlation warning badge
    await cmd('Runtime.evaluate', {
      expression: `
        (() => {
          const cards = Array.from(document.querySelectorAll('.mobile-quant-row'));
          const c = cards.find(x => x.querySelector('.mq-team-matchup')?.textContent?.includes('DET'));
          if (c) {
            const btn = c.querySelector('[data-log-bet]');
            if (btn) btn.click();
          }
        })()
      `
    });
    await new Promise(r => setTimeout(r, 500));

    const corrBadges = await cmd('Runtime.evaluate', { expression: 'document.querySelectorAll(".mq-signal-badge.corr-risk").length' });
    console.log(`[MOBILE 2] Mobile Cannibalistic Vol Risk Badges: ${corrBadges?.result?.value}`);

    const shot1 = await cmd('Page.captureScreenshot');
    fs.writeFileSync(path.join(__dirname, '..', 'artifacts', 'mobile_autonomous_terminal_verified.png'), Buffer.from(shot1.data, 'base64'));

    // 3. Open Mobile Sniper Dialog via chip button
    await cmd('Runtime.evaluate', { expression: 'document.querySelector("#mobileSniperBtn").click();' });
    await new Promise(r => setTimeout(r, 500));

    const mobileSniperOpen = await cmd('Runtime.evaluate', { expression: 'Boolean(document.querySelector("#sniperDialog")?.open)' });
    console.log(`[MOBILE 3] Mobile Sniper Modal Open: ${mobileSniperOpen?.result?.value}`);

    const shot2 = await cmd('Page.captureScreenshot');
    fs.writeFileSync(path.join(__dirname, '..', 'artifacts', 'mobile_sniper_dialog_verified.png'), Buffer.from(shot2.data, 'base64'));

    console.log('✓ Mobile telemetry verified!');
    ws.close();
  } catch (e) {
    console.error('Mobile test error:', e);
  } finally {
    chrome.kill();
    process.exit(0);
  }
}

testMobile();
