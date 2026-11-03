/**
 * PropStein UFC fight-card view (self-contained; NOT a PropWireSports props
 * adapter, because app.js treats registered adapters as player-prop slates).
 * Reads /feeds/slate-index.json -> sports.ufc.default_card -> /ufc_card_<date>.json.
 *
 * CARD PARITY (2026-10-31): fight cards render with the SAME today-game-card
 * markup and classes as the NFL/NBA schedule cards (viewer/js/today-schedule.js),
 * so one visual system covers all three sports: trigger face (centered meta row
 * with right-aligned status, mirrored matchup blocks around a VS center,
 * centered market context row, action bar with chevron) plus an expandable
 * detail panel (fighter rows with model projection + market line boxes).
 * viewer/ufc.css carries only the UFC deltas (status colors, winner check,
 * void dimming, NO EDGE tint, link resets) — the card chrome itself comes from
 * style.css, which keeps all three sports in sync by construction.
 *
 * The expand/collapse click is intercepted in the CAPTURE phase on document so
 * today-schedule.js's delegated `.today-game-trigger` handler (which resolves
 * NFL/NBA game indexes and would reject on UFC data) never sees these clicks.
 *
 * Honesty: every card face shows fight.edge (NO EDGE); the banner above the
 * list keeps the unbacktested-model warning and the receipt count. Nothing
 * hides, collapses away, or gets restyled into obscurity.
 */
(() => {
  'use strict';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const pct = (p) => (p == null ? '—' : `${Math.round(p * 1000) / 10}%`);
  const am = (o) => (o == null ? '—' : (o > 0 ? `+${o}` : `${o}`));
  const safeImg = (u) => (/^https:\/\/a\.espncdn\.com\//.test(u || '') ? u : '');
  const initials = (name) => String(name || '').replace(/[^A-Za-z0-9\s]/g, '').split(/\s+/).filter(Boolean).map((p) => p[0]).join('').slice(0, 2).toUpperCase();
  const STATUS_LABEL = { scheduled: '', replacement: 'Short-notice replacement', missed_weight: 'Missed weight', cancelled: 'Cancelled', scratched: 'Scratched', final: 'Final', draw: 'Draw / NC', no_contest: 'No contest' };

  // Time-zone parity with the NFL/NBA schedule cards: honor the same selector.
  const zone = () => (document.getElementById('todayScheduleTimezone')?.value === 'et'
    ? 'America/New_York' : Intl.DateTimeFormat().resolvedOptions().timeZone);
  const fightTime = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : new Intl.DateTimeFormat('en-US', { timeZone: zone(), weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(d);
  };

  /** Face matchup block — mirrors today-schedule.js team(): logo circle + stacked record/name. */
  function fighterFace(f, i, fight) {
    const img = safeImg(f?.headshot);
    const won = fight.result === 'win' && f?.winner;
    return `<div class="today-team${won ? ' is-winner' : ''}">
      <span class="today-team-logo">${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : `<span>${esc(initials(f?.name))}</span>`}</span>
      <span class="today-team-name"><b>${esc(f?.record || '—')}</b><strong>${esc(f?.name || 'TBD')}</strong></span>
    </div>`;
  }

  /** Face context row — bout info + market totals chip, like SPREAD / O/U on NFL cards. */
  function fightContext(fight) {
    const tot = (fight.totals || [])[0];
    const rounds = fight.sched_rounds || 3;
    const bout = `<span>${esc(fight.weight_class || 'MMA')} · ${esc(rounds)} RDS</span>`;
    const market = tot
      ? `<span>O/U ${esc(tot.line)} RDS</span>`
      : '<span>NO MARKET LINES</span>';
    return `${bout}${market}`;
  }

  /** Panel fighter row — links to the fighter page; model/market/best-price line boxes. */
  function fighterRow(f, i, fight) {
    const img = safeImg(f?.headshot);
    const model = fight.model?.p?.[i];
    const mkt = fight.market?.h2h_novig?.[i];
    const best = fight.market?.best?.[i];
    const meta = [f?.record, f?.age ? `${f.age}y` : '', f?.reach_in ? `${f.reach_in}" reach` : '', f?.stance].filter(Boolean).map(esc).join(' · ');
    const priceBox = best && best.price != null
      ? `<span class="today-line-box"><b>BEST</b><small>${esc(am(best.price))} · ${esc(best.book || 'unknown book')}</small></span>`
      : '<span class="today-line-box"><b>BEST</b><small>no line pulled</small></span>';
    return `<a class="today-prop-row ufc-prop-row" href="/ufc/fighter?id=${encodeURIComponent(f?.id || '')}" data-ufc-fighter="${esc(f?.id || '')}">
      <div class="today-prop-summary">
        <span class="today-prop-photo"><span>${esc(initials(f?.name))}</span>${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : ''}</span>
        <div class="today-prop-player"><strong>${esc(f?.name || 'TBD')}</strong><span>${meta || '—'}</span></div>
        <div class="today-prop-projection"><b>${pct(model)}</b><small>MODEL WIN</small></div>
      </div>
      <div class="today-line-boxes" aria-label="Market consensus and best available price">
        <span class="today-line-box"><b>MARKET NOVIG</b><small>${pct(mkt)}</small></span>
        ${priceBox}
      </div>
    </a>`;
  }

  /** Panel totals note — market vs model rounds + finish hazard. */
  function totalsNote(fight) {
    const tot = (fight.totals || [])[0];
    const m = fight.model || {};
    const bits = tot
      ? [`O/U ${esc(tot.line)} rds · market over ${pct(tot.p_over_novig)} · model ${pct(tot.model_p_over)}`]
      : [`No totals lines pulled · model over 1.5 rds ${pct(m.p_over_by_line?.['1.5'])} (model only, no market)`];
    bits.push(`model finish ${pct(m.p_finish)}`);
    return `<p class="today-line-source ufc-prop-totals">${bits.join(' · ')}</p>`;
  }

  function fightCard(fight) {
    const label = STATUS_LABEL[fight.status] || '';
    const id = String(fight.fight_id || '');
    const faces = (fight.fighters || []).map((f, i) => fighterFace(f, i, fight))
      .join('<div class="today-game-center"><span class="today-versus">VS</span></div>');
    const rows = (fight.fighters || []).map((f, i) => fighterRow(f, i, fight)).join('');
    const a = fight.fighters?.[0]?.name || 'Fighter';
    const b = fight.fighters?.[1]?.name || 'fighter';
    return `<article class="today-game-card ufc-fight${fight.void ? ' is-void' : ''}">
      <button class="today-game-trigger ufc-game-trigger" type="button" data-ufc-fight="${esc(id)}" aria-expanded="false" aria-controls="ufcFightProps${esc(id)}" aria-label="${esc(a)} vs ${esc(b)}: show model versus market detail">
        <div class="today-game-top"><span>${esc(fightTime(fight.start))}</span>${label ? `<span class="today-game-status ufc-status-${esc(fight.status)}">${esc(label)}</span>` : ''}</div>
        <div class="today-game-matchup">${faces}</div>
        <div class="today-game-context">${fightContext(fight)}</div>
        <div class="today-game-action"><span><b class="ufc-noedge">${esc(fight.edge || 'NO EDGE')}</b> · MODEL VS MARKET</span><span class="today-game-chevron" aria-hidden="true">⌄</span></div>
      </button>
      <div class="today-game-props" id="ufcFightProps${esc(id)}" hidden>
        <div class="today-prop-heading"><strong>Model vs market</strong><span>Metered odds pulls, not receipts · model unbacktested</span></div>
        <div class="today-prop-list">${rows}</div>
        ${totalsNote(fight)}
      </div>
    </article>`;
  }

  let lastCard = null;
  let renderNumber = 0;

  // Expand/collapse for UFC cards. CAPTURE phase on document: fires before
  // today-schedule.js's bubble-phase handler on #todayScheduleGames, and
  // stopPropagation() keeps that handler (built for NFL/NBA event indexes)
  // away from UFC fights entirely.
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest && event.target.closest('.ufc-game-trigger');
    if (!trigger) return;
    event.stopPropagation();
    const panel = document.getElementById(trigger.getAttribute('aria-controls') || '');
    if (!panel) return;
    const open = trigger.getAttribute('aria-expanded') === 'true';
    trigger.setAttribute('aria-expanded', String(!open));
    panel.hidden = open;
  }, true);

  // Stash the tapped fighter so /ufc/fighter paints instantly (plain link, no interception).
  document.addEventListener('pointerdown', (e) => {
    const a = e.target.closest && e.target.closest('a[data-ufc-fighter]');
    if (!a || !lastCard) return;
    const f = lastCard.fights.flatMap((x) => x.fighters.map((p) => ({ ...p, weight_class: x.weight_class }))).find((p) => p.id === a.dataset.ufcFighter);
    try { if (f) sessionStorage.setItem(`ufc_fighter_${f.id}`, JSON.stringify(f)); } catch (_) { /* ignore */ }
  }, { passive: true, capture: true });

  async function render(container, titleEl, sourceEl) {
    const currentRender = ++renderNumber;
    container.classList.add('ufc-scope');
    container.innerHTML = '<p class="today-schedule-message">Loading the next UFC card…</p>';
    try {
      const idx = await (await fetch('/feeds/slate-index.json', { cache: 'no-store' })).json();
      const ufc = idx?.sports?.ufc;
      const key = ufc?.default_card;
      if (!key) throw new Error('no UFC card in manifest');
      const card = await (await fetch(`/${ufc.cards[key].card}`, { cache: 'no-store' })).json();
      // A sport switch or re-render while fetching must not clobber the newer view.
      if (currentRender !== renderNumber) return;
      lastCard = card;
      if (titleEl) titleEl.textContent = card.event_name || 'Next UFC card';
      const fights = [...(card.fights || [])].reverse(); // main event first
      const stale = card.market_as_of ? `Odds as of ${new Date(card.market_as_of).toLocaleString('en-US', { timeZone: zone(), timeZoneName: 'short' })}` : 'No odds pulled yet';
      // Receipt state must stay visible on the UFC surface (charter: UNVERIFIED is never hidden).
      // card.receipts_verified is 0/absent until a receipt layer exists; generic toasts stay
      // suppressed on this tab because this banner is the sport-native home for the signal.
      const receipts = card.receipts_verified ?? 0;
      container.innerHTML = `<div class="ufc-honesty"><strong>${esc(card.honesty || 'NO EDGE')}</strong> · Results-only backtest: Brier ${esc(card.backtest?.brier ?? '—')} vs 0.25 coin flip (n=${esc(card.backtest?.n ?? 0)}) · Receipt-verified quotes: ${receipts} — displayed lines are metered pulls, not receipts</div>
        <div class="today-schedule-games ufc-card-list">${fights.map(fightCard).join('')}</div>`;
      if (sourceEl) sourceEl.textContent = `Card: ESPN · Odds: The Odds API (fight winner, total rounds) · ${stale} · Times in ${zone() === 'America/New_York' ? 'Eastern' : 'your local'} time · ${fights.length} fights`;
    } catch (error) {
      if (currentRender !== renderNumber) return;
      container.innerHTML = '<p class="today-schedule-message">The UFC card is unavailable right now. Tap Refresh to try again.</p>';
      if (sourceEl) sourceEl.textContent = '';
      console.warn('[PropStein] UFC card unavailable:', error);
    }
  }

  window.PropSteinUFC = Object.freeze({ render });
})();
