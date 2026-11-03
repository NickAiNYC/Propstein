#!/usr/bin/env node
// Live-prod image probe: loads https://propwire.vercel.app/ in a FRESH
// headless browser (real SW + real cache behavior) and reports:
//   - every failed/4xx/5xx request (which images, why)
//   - every <img> that is complete but naturalWidth===0 (broken)
//   - console errors
//   - screenshots desktop + iPhone widths
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const SHOTS = '/home/z/my-project/download';
mkdirSync(SHOTS, { recursive: true });
const URLS = ['https://propwire.vercel.app/', 'https://propwire.vercel.app/ledger.html'];

const browser = await chromium.launch();

for (const target of URLS) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const failed = [];
  const bad4xx = [];
  const consoleErrors = [];
  page.on('requestfailed', (r) => failed.push(`${r.url()}  ::  ${r.failure()?.errorText}`));
  page.on('response', (r) => { if (r.status() >= 400) bad4xx.push(`${r.status()}  ${r.url()}`); });
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

  console.log('═'.repeat(70));
  console.log('PROBE', target);
  try {
    await page.goto(target, { waitUntil: 'networkidle', timeout: 45000 });
  } catch (e) {
    console.log('goto timeout (continuing with what loaded):', e.message.split('\n')[0]);
  }
  await page.waitForTimeout(4000);

  const imgs = await page.evaluate(() => {
    const out = [];
    for (const img of document.images) {
      out.push({ src: img.currentSrc || img.src, ok: !(img.complete && img.naturalWidth === 0), w: img.naturalWidth });
    }
    return out;
  });
  const broken = imgs.filter((i) => !i.ok);
  const bgs = await page.evaluate(() => {
    // elements with background-image that failed to resolve are hard to detect;
    // report how many elements use background-image at all for context
    let n = 0;
    for (const el of document.querySelectorAll('*')) {
      const bg = getComputedStyle(el).backgroundImage;
      if (bg && bg !== 'none') n++;
    }
    return n;
  });

  console.log(`imgs total: ${imgs.length}  broken: ${broken.length}`);
  for (const b of broken) console.log('  BROKEN IMG:', b.src, '(naturalWidth', b.w + ')');
  console.log(`elements with background-image: ${bgs}`);
  console.log(`requestfailed: ${failed.length}`);
  for (const f of failed.slice(0, 12)) console.log('  FAILED:', f);
  console.log(`4xx/5xx responses: ${bad4xx.length}`);
  for (const b of bad4xx.slice(0, 12)) console.log('  ', b);
  console.log(`console errors: ${consoleErrors.length}`);
  for (const c of consoleErrors.slice(0, 8)) console.log('  ERR:', c.slice(0, 160));

  const swState = await page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) return 'no SW';
    const regs = await navigator.serviceWorker.getRegistrations();
    const keys = await caches.keys();
    return `${regs.length} SW registration(s), caches: [${keys.join(', ')}]`;
  });
  console.log('SW/cache state:', swState);

  const slug = target.includes('ledger') ? 'ledger' : 'home';
  await page.screenshot({ path: `${SHOTS}/prod_probe_${slug}_1280.png`, clip: { x: 0, y: 0, width: 1280, height: 600 } });
  await page.close();
}

// iPhone pass on home
const ip = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1' });
const ifailed = [];
const i4xx = [];
ip.on('requestfailed', (r) => ifailed.push(`${r.url()}  ::  ${r.failure()?.errorText}`));
ip.on('response', (r) => { if (r.status() >= 400) i4xx.push(`${r.status()}  ${r.url()}`); });
await ip.goto('https://propwire.vercel.app/', { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
await ip.waitForTimeout(4000);
const iimgs = await ip.evaluate(() => {
  const out = [];
  for (const img of document.images) out.push({ src: (img.currentSrc || img.src).slice(-60), ok: !(img.complete && img.naturalWidth === 0) });
  return out;
});
console.log('═'.repeat(70));
console.log('PROBE iPhone 390 (Safari UA): imgs', iimgs.length, 'broken', iimgs.filter((i) => !i.ok).length);
for (const b of iimgs.filter((i) => !i.ok)) console.log('  BROKEN:', b.src);
console.log('requestfailed:', ifailed.length); for (const f of ifailed.slice(0, 10)) console.log('  FAILED:', f);
console.log('4xx/5xx:', i4xx.length); for (const b of i4xx.slice(0, 10)) console.log('  ', b);
await ip.screenshot({ path: `${SHOTS}/prod_probe_iphone_390.png`, clip: { x: 0, y: 0, width: 390, height: 700 } });
await browser.close();
console.log('done');
