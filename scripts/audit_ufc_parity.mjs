// Computed-style parity audit: a UFC fight card vs an NFL game card in the same
// page session. Dumps the properties that define the today-game-card look so
// parity is checked numerically, not by eyeballing.
import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFileSync, existsSync } from 'fs';
import { join, extname } from 'path';

const ROOT = join(process.cwd(), 'viewer');
const PORT = 9900 + Math.floor(Math.random() * 100);
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png' };
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
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1200);

// NFL tab first (default). If ESPN is unreachable, note it and continue.
const nfl = await page.evaluate(() => new Promise((resolve) => {
  const started = Date.now();
  const timer = setInterval(() => {
    const card = document.querySelector('#todayScheduleGames .today-game-card');
    if (card || Date.now() - started > 9000) { clearInterval(timer); resolve(card ? 'cards' : 'none'); }
  }, 250);
}));

const styleOf = null;
const CARD_PROPS = ['border-radius', 'background-image', 'box-shadow', 'border-color', 'max-width', 'overflow'];
const TRIGGER_PROPS = ['min-height', 'padding', 'background-image', 'font-family'];
const ACTION_PROPS = ['padding', 'border-top-color', 'background-image', 'font-size', 'font-family', 'letter-spacing', 'color'];
const TOP_PROPS = ['font-size', 'font-weight', 'font-family', 'color'];
const LOGO_PROPS = ['width', 'height', 'border-radius', 'background-color', 'border-color'];
const CONTEXT_PROPS = ['font-size', 'font-family', 'color', 'justify-content'];
const GRID_PROPS = ['grid-template-columns', 'gap', 'align-items'];

const styleSrc = `(el, props) => { if (!el) return null; const cs = getComputedStyle(el); return Object.fromEntries(props.map((p) => [p, cs[p]])); }`;

const nflDump = await page.evaluate(({ CARD_PROPS, TRIGGER_PROPS, ACTION_PROPS, TOP_PROPS, LOGO_PROPS, CONTEXT_PROPS, GRID_PROPS, styleSrc }) => {
  const styleOf = eval('(' + styleSrc + ')');
  const card = document.querySelector('#todayScheduleGames .today-game-card');
  if (!card) return null;
  return {
    card: styleOf(card, CARD_PROPS),
    trigger: styleOf(card.querySelector('.today-game-trigger'), TRIGGER_PROPS),
    action: styleOf(card.querySelector('.today-game-action'), ACTION_PROPS),
    top: styleOf(card.querySelector('.today-game-top'), TOP_PROPS),
    logo: styleOf(card.querySelector('.today-team-logo'), LOGO_PROPS),
    context: styleOf(card.querySelector('.today-game-context'), CONTEXT_PROPS),
    grid: styleOf(document.querySelector('#todayScheduleGames'), GRID_PROPS)
  };
}, { CARD_PROPS, TRIGGER_PROPS, ACTION_PROPS, TOP_PROPS, LOGO_PROPS, CONTEXT_PROPS, GRID_PROPS, styleSrc });

// Switch to UFC.
await page.evaluate(() => document.querySelector('#sportSwitcher [data-sport="ufc"]')?.click() || document.querySelector('[data-sport="ufc"]')?.click());
await page.waitForFunction(() => document.querySelectorAll('#todayScheduleGames .ufc-fight').length > 0, { timeout: 20000 });
await page.waitForTimeout(500);

const ufcDump = await page.evaluate(({ CARD_PROPS, TRIGGER_PROPS, ACTION_PROPS, TOP_PROPS, LOGO_PROPS, CONTEXT_PROPS, GRID_PROPS, styleSrc }) => {
  const styleOf = eval('(' + styleSrc + ')');
  const card = document.querySelector('#todayScheduleGames .ufc-fight');
  if (!card) return null;
  return {
    card: styleOf(card, CARD_PROPS),
    trigger: styleOf(card.querySelector('.ufc-game-trigger'), TRIGGER_PROPS),
    action: styleOf(card.querySelector('.today-game-action'), ACTION_PROPS),
    top: styleOf(card.querySelector('.today-game-top'), TOP_PROPS),
    logo: styleOf(card.querySelector('.today-team-logo'), LOGO_PROPS),
    context: styleOf(card.querySelector('.today-game-context'), CONTEXT_PROPS),
    grid: styleOf(document.querySelector('.ufc-card-list'), GRID_PROPS),
    panelHidden: card.querySelector('.today-game-props')?.hidden,
    noedgeColor: getComputedStyle(card.querySelector('.ufc-noedge')).color
  };
}, { CARD_PROPS, TRIGGER_PROPS, ACTION_PROPS, TOP_PROPS, LOGO_PROPS, CONTEXT_PROPS, GRID_PROPS, styleSrc });

await browser.close();
server.close();

const norm = (v) => String(v).replace(/\s+/g, ' ').trim();
const compare = (label, a, b, skip = []) => {
  console.log(`\n== ${label} ==`);
  if (!a || !b) { console.log('  (one side unavailable)'); return; }
  for (const key of Object.keys(a)) {
    if (skip.includes(key)) continue;
    const same = norm(a[key]) === norm(b[key]);
    console.log(`  ${same ? 'MATCH' : 'DIFF '} ${key}: expected=${norm(a[key])} | ufc=${norm(b[key])}`);
  }
};

// Declared expectations from viewer/style.css (graphite override block, the
// look the NFL/NBA cards actually render with today). ESPN is unreachable from
// this sandbox, so the live NFL card cannot be sampled; the stylesheet values
// are the source of truth for the shared classes.
const EXPECT = {
  card: {
    'border-radius': '26px',
    'background-image': 'linear-gradient(150deg, rgb(41, 41, 45) 0%, rgb(26, 26, 29) 38%, rgb(16, 16, 18) 74%, rgb(36, 36, 39) 100%)',
    'box-shadow': 'rgb(255, 255, 255) 0px 1px 0px inset, rgba(0, 0, 0, 0.24) 0px 16px 32px'
  },
  trigger: {
    'min-height': '184px',
    'padding': '18px 15px 0px'
  },
  action: {
    'padding': '11px 17px',
    'font-size': '10px',
    'letter-spacing': '0.08em'
  },
  top: { 'font-size': '12px', 'font-weight': '600' },
  logo: { 'width': '44px', 'height': '44px', 'border-radius': '50%', 'background-color': 'rgb(41, 41, 45)' },
  context: { 'font-size': '10px', 'justify-content': 'center' }
};

console.log(`NFL schedule source available: ${nfl}`);
compare('card container', EXPECT.card, ufcDump.card, ['max-width']);
compare('trigger face', EXPECT.trigger, ufcDump.trigger, ['font-family']);
compare('action bar', EXPECT.action, ufcDump.action, ['font-family', 'background-image', 'border-top-color']);
compare('top row', EXPECT.top, ufcDump.top, ['font-family', 'color']);
compare('team logo circle', EXPECT.logo, ufcDump.logo, ['border-color']);
compare('context row', EXPECT.context, ufcDump.context, ['font-family', 'color']);
console.log('\nUFC extras -> panel hidden by default:', ufcDump.panelHidden, '| NO EDGE color:', ufcDump.noedgeColor, '| card max-width:', ufcDump.card['max-width']);
console.log('UFC card grid:', ufcDump.grid['grid-template-columns'], '| gap:', ufcDump.grid.gap, '| align:', ufcDump.grid['align-items']);
