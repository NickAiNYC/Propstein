// Visual parity check: UFC fight cards must match the NFL/NBA today-game-card look.
// Serves viewer/ statically, opens index.html, switches to the UFC tab, and
// screenshots collapsed + expanded states (mobile 390px and desktop 1280px).
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9700 + Math.floor(Math.random() * 200);
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
const server = createServer((req, res) => {
  const clean = decodeURIComponent(req.url.split('?')[0]);
  const rel = clean === '/' ? 'index.html' : clean.replace(/^\/+/, '');
  const file = join(ROOT, rel);
  if (!existsSync(file)) { res.writeHead(404); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(PORT, r));

const URL = `http://127.0.0.1:${PORT}/index.html`;
const browser = await chromium.launch();

async function shoot(width, height, tag, mobile) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile });
  await page.goto(URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  // Block nothing; wait for UFC card list after switching tabs.
  const switcher = mobile ? '#mobileSportSwitcher' : '#sportSwitcher';
  await page.evaluate((sel) => {
    const btn = document.querySelector(`${sel} [data-sport="ufc"]`) || document.querySelector('[data-sport="ufc"]');
    btn?.click();
  }, switcher);
  await page.waitForFunction(() => document.querySelectorAll('#todayScheduleGames .today-game-card').length > 0, { timeout: 20000 });
  await page.waitForTimeout(600);
  const cards = await page.evaluate(() => {
    document.querySelector('#todaySchedule')?.scrollIntoView({ block: 'start' });
    const list = document.querySelector('#todayScheduleGames');
    return { count: list.querySelectorAll('.today-game-card').length, banner: list.querySelector('.ufc-honesty')?.textContent || '' };
  });
  console.log(tag, 'cards:', JSON.stringify(cards));
  await page.screenshot({ path: `/home/z/my-project/download/ufc_parity_${tag}_collapsed.png` });
  // Expand the first fight's model-vs-market panel.
  await page.evaluate(() => document.querySelector('#todayScheduleGames .ufc-game-trigger')?.click());
  await page.waitForTimeout(400);
  await page.screenshot({ path: `/home/z/my-project/download/ufc_parity_${tag}_expanded.png` });
  await page.close();
}

try {
  await shoot(390, 900, 'mobile390', true);
  await shoot(1280, 900, 'desktop1280', false);
} finally {
  await browser.close();
  server.close();
}
console.log('saved: ufc_parity_mobile390_{collapsed,expanded}.png, ufc_parity_desktop1280_{collapsed,expanded}.png');
