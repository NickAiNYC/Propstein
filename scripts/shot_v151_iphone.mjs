// Quick iPhone screenshot of the v151 W8 boot for the worklog/announcement.
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9400 + Math.floor(Math.random() * 300);
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle' });
await page.waitForFunction('window.__PROP_WIRE_READY__ === true', { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(800);
const state = await page.evaluate(() => ({
  slateKey: window.__PROP_WIRE_STATE__?.slateKey,
  rows: window.__PROP_WIRE_STATE__?.slate?.length,
}));
console.log('boot:', JSON.stringify(state));
await page.screenshot({ path: '/home/z/my-project/download/headless_v151_iphone_390_boot.png', clip: { x: 0, y: 0, width: 390, height: 620 } });
// research mode after CTA
await page.evaluate(() => document.querySelector('#antiToutViewAllBtn')?.click());
await page.waitForTimeout(500);
await page.screenshot({ path: '/home/z/my-project/download/headless_v151_iphone_390_research.png', clip: { x: 0, y: 0, width: 390, height: 844 } });
await browser.close();
server.close();
console.log('screenshots saved');
