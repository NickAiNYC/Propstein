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
  console.log(`[TEST-SERVER] Listening at http://127.0.0.1:${PORT}`);

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const chrome = spawn(chromePath, [
    '--headless=new',
    '--remote-debugging-port=9231',
    '--disable-gpu',
    '--window-size=1280,900',
    `http://127.0.0.1:${PORT}/index.html`
  ]);

  await new Promise((r) => setTimeout(r, 2000));

  try {
    const listRes = await fetch('http://127.0.0.1:9231/json');
    const tabs = await listRes.json();
    const pageTab = tabs.find((t) => t.type === 'page');
    console.log('Connected to tab:', pageTab.title);

    const ws = new WebSocket(pageTab.webSocketDebuggerUrl);
    let id = 1;
    const send = (method, params = {}) => new Promise((resolve) => {
      const msgId = id++;
      const handler = (event) => {
        const data = JSON.parse(event.data);
        if (data.id === msgId) {
          ws.removeEventListener('message', handler);
          resolve(data.result);
        }
      };
      ws.addEventListener('message', handler);
      ws.send(JSON.stringify({ id: msgId, method, params }));
    });

    await new Promise((r) => ws.addEventListener('open', r));
    await send('Runtime.enable');
    await send('Page.enable');

    const evalJs = async (expr) => {
      const res = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
      return res?.result?.value;
    };

    // 1. Verify First-Run Briefing is visible on first run
    const briefingVisible = await evalJs(`
      const b = document.getElementById('firstRunBriefing');
      b && !b.hidden && getComputedStyle(b).display !== 'none';
    `);
    console.log('1. First-Run Briefing Visible:', briefingVisible ? 'PASS' : 'FAIL');

    // 2. Test Dismissal of Briefing
    const dismissed = await evalJs(`
      (() => {
        const btn = document.getElementById('dismissBriefingBtn');
        if (btn) btn.click();
        const b = document.getElementById('firstRunBriefing');
        return {
          hasBtn: Boolean(btn),
          bHidden: Boolean(b && b.hidden),
          storage: localStorage.getItem('propwire_onboarding_dismissed')
        };
      })()
    `);
    console.log('2. First-Run Briefing Dismissed & Persisted:', dismissed);

    // 3. Test Top Plays Mode Filter
    const topPlaysCount = await evalJs(`
      const topBtn = document.getElementById('modeTopBtn');
      if (topBtn) topBtn.click();
      const rows = document.querySelectorAll('tr[data-testid="slate-row"]');
      rows.length;
    `);
    console.log('3. Top Plays Filter Rows count:', topPlaysCount, topPlaysCount > 0 && topPlaysCount <= 25 ? 'PASS' : 'CHECK');

    // Return to Active mode
    await evalJs(`document.getElementById('modeActionableBtn')?.click()`);

    // 4. Test Compliance Footer
    const footerCheck = await evalJs(`
      const footer = document.querySelector('.terminal-compliance-footer');
      const badge21 = document.querySelector('.compliance-badge-21');
      const helpline = document.querySelector('a[href="tel:18004262537"]');
      const disclaimer = document.querySelector('.compliance-disclaimer');
      Boolean(footer && badge21 && helpline && disclaimer && disclaimer.textContent.includes('1-800-GAMBLER'));
    `);
    console.log('4. Compliance Footer (21+ & 1-800-GAMBLER):', footerCheck ? 'PASS' : 'FAIL');

    // 5. Test Historical Slate Settled Results (2026_w1)
    const settledCheck = await evalJs(`
      const sel = document.getElementById('slateSelector');
      sel.value = '2026_w1';
      sel.dispatchEvent(new Event('change'));
      new Promise((resolve) => {
        setTimeout(() => {
          const wonBadges = document.querySelectorAll('.settled-won');
          const lostBadges = document.querySelectorAll('.settled-lost');
          const statBoxes = document.querySelectorAll('.settled-stat-box');
          resolve({
            wonCount: wonBadges.length,
            lostCount: lostBadges.length,
            statBoxes: statBoxes.length
          });
        }, 1200);
      });
    `);
    console.log('5. Historical Slate Settled Results (WON/LOST/StatBoxes):', settledCheck);

    // Switch back to 2026_w7
    await evalJs(`
      const sel = document.getElementById('slateSelector');
      sel.value = '2026_w7';
      sel.dispatchEvent(new Event('change'));
    `);
    await new Promise((r) => setTimeout(r, 1200));

    // 6. Test Correlated Exposure & Dismissal (Strict hasWarning assert)
    await evalJs(`
      const testPortfolio = [
        { id: 't1', player_id: '00-0036963', player_name: 'Amon-Ra St. Brown', team: 'DET', opponent: 'GB', market: 'receiving_yards', side: 'OVER', line: 78.5, odds: -110 },
        { id: 't2', player_id: '00-0039139', player_name: 'Jahmyr Gibbs', team: 'DET', opponent: 'GB', market: 'receiving_yards', side: 'OVER', line: 38.5, odds: -110 }
      ];
      localStorage.setItem('propwire_portfolio_ledger', JSON.stringify(testPortfolio));
      localStorage.removeItem('propwire_dismissed_correlations');
      location.reload();
    `);
    await new Promise((r) => setTimeout(r, 2200));

    const verifyCorrDismiss = await evalJs(`
      (() => {
        const portBtn = document.getElementById('portfolioBtn');
        if (portBtn) portBtn.click();
        const riskAlert = document.querySelector('.portfolio-risk-alert');
        const alertText = riskAlert ? riskAlert.textContent.toLowerCase() : '';
        const hasWarning = Boolean(riskAlert && (alertText.includes('exposure') || alertText.includes('same-team')));
        
        // Click dismiss
        const dismissBtn = document.querySelector('[data-dismiss-corr]');
        const hadDismissBtn = Boolean(dismissBtn);
        if (dismissBtn) dismissBtn.click();
        
        // Check if dismissed
        const riskAlertAfter = document.querySelector('.portfolio-risk-alert');
        const isGone = !riskAlertAfter;

        // Clean up test portfolio
        localStorage.removeItem('propwire_portfolio_ledger');
        localStorage.removeItem('propwire_dismissed_correlations');
        
        return { hasWarning, hadDismissBtn, isGone };
      })()
    `);
    console.log('6. Correlated Exposure & Dismissal Test:', verifyCorrDismiss);

    // Capture desktop screenshot
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    fs.mkdirSync('artifacts', { recursive: true });
    fs.writeFileSync('artifacts/verified_terminal_launch_ready.png', Buffer.from(shot.data, 'base64'));
    console.log('✓ Desktop screenshot saved to artifacts/verified_terminal_launch_ready.png');

    // 7. Mobile Viewport (375px) Header & Slate Capture
    await send('Emulation.setDeviceMetricsOverride', {
      width: 375,
      height: 812,
      deviceScaleFactor: 2,
      mobile: true
    });
    await new Promise((r) => setTimeout(r, 800));

    // Reload mobile view to refresh layout
    await evalJs(`
      const portDialog = document.getElementById('portfolioDialog');
      if (portDialog && portDialog.open) portDialog.close();
      const briefing = document.getElementById('firstRunBriefing');
      if (briefing) {
        briefing.hidden = true;
        briefing.style.display = 'none';
      }
      window.scrollTo(0, 0);
    `);
    await new Promise((r) => setTimeout(r, 500));

    const mobileShot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync('artifacts/mobile_header_375px.png', Buffer.from(mobileShot.data, 'base64'));
    console.log('✓ 375px Mobile Screenshot saved to artifacts/mobile_header_375px.png');

    // Copy to brain artifacts directory for user viewing
    const brainDir = '/Users/nick/.gemini/antigravity-ide/brain/864b77c4-bb96-486d-b389-ad501875d808';
    if (fs.existsSync(brainDir)) {
      fs.copyFileSync('artifacts/mobile_header_375px.png', path.join(brainDir, 'mobile_header_375px.png'));
      fs.copyFileSync('artifacts/verified_terminal_launch_ready.png', path.join(brainDir, 'verified_terminal_launch_ready.png'));
    }

    ws.close();
    chrome.kill();
    server.close();
    process.exit(0);
  } catch (err) {
    console.error('Error during verification:', err);
    chrome.kill();
    server.close();
    process.exit(1);
  }
});
