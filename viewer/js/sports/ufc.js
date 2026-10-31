/**
 * PropStein UFC fight-card view (self-contained; NOT a PropWireSports props
 * adapter, because app.js treats registered adapters as player-prop slates).
 * Reads /feeds/slate-index.json -> sports.ufc.default_card -> /ufc_card_<date>.json.
 * Honesty: every card shows NO EDGE until the UFC ledger proves otherwise.
 */
(() => {
  'use strict';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const pct = (p) => (p == null ? '—' : `${Math.round(p * 1000) / 10}%`);
  const am = (o) => (o == null ? '—' : (o > 0 ? `+${o}` : `${o}`));
  const safeImg = (u) => (/^https:\/\/a\.espncdn\.com\//.test(u || '') ? u : '');
  const etTime = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(d);
  };
  const STATUS_LABEL = { scheduled: '', replacement: 'Short-notice replacement', missed_weight: 'Missed weight', cancelled: 'Cancelled', scratched: 'Scratched', final: 'Final', draw: 'Draw / NC', no_contest: 'No contest' };

  function fighterCell(f, i, fight) {
    const img = safeImg(f.headshot);
    const model = fight.model?.p?.[i];
    const mkt = fight.market?.h2h_novig?.[i];
    const best = fight.market?.best?.[i];
    const won = fight.result === 'win' && f.winner;
    return `<a class="ufc-fighter ${won ? 'is-winner' : ''}" href="/ufc/fighter?id=${encodeURIComponent(f.id)}" data-ufc-fighter="${esc(f.id)}">
      <span class="ufc-photo">${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : ''}</span>
      <strong>${esc(f.name)}</strong><span class="ufc-rec">${esc(f.record || '')}${f.age ? ` · ${esc(f.age)}y` : ''}${f.reach_in ? ` · ${esc(f.reach_in)}" reach` : ''}</span>
      <span class="ufc-nums"><span title="Model fair probability">Model ${pct(model)}</span><span title="No-vig market consensus">Market ${pct(mkt)}</span>
      <span title="Best available price">${best ? `${esc(am(best.price))} · ${esc(best.book)}` : 'No line'}</span></span></a>`;
  }

  function fightCard(fight) {
    const st = STATUS_LABEL[fight.status] || '';
    const tot = (fight.totals || [])[0];
    const totals = tot
      ? `O/U ${esc(tot.line)} rds · Mkt over ${pct(tot.p_over_novig)} · Model ${pct(tot.model_p_over)}`
      : `Model: finish ${pct(fight.model?.p_finish)} · over 1.5 rds ${pct(fight.model?.p_over_by_line?.['1.5'])}`;
    return `<article class="ufc-fight ${fight.void ? 'is-void' : ''}">
      <div class="ufc-fight-top"><span>${esc(etTime(fight.start))}</span><span>${esc(fight.weight_class || '')} · ${esc(fight.sched_rounds)} rds</span>${st ? `<span class="ufc-badge ufc-badge-${esc(fight.status)}">${esc(st)}</span>` : ''}</div>
      <div class="ufc-fight-body">${fight.fighters.map((f, i) => fighterCell(f, i, fight)).join('<span class="ufc-vs">VS</span>')}</div>
      <div class="ufc-fight-foot"><span>${totals}</span><span class="ufc-noedge">${esc(fight.edge || 'NO EDGE')}</span></div>
    </article>`;
  }

  let lastCard = null;
  // Stash the tapped fighter so /ufc/fighter paints instantly (plain link, no interception).
  document.addEventListener('pointerdown', (e) => {
    const a = e.target.closest && e.target.closest('a[data-ufc-fighter]');
    if (!a || !lastCard) return;
    const f = lastCard.fights.flatMap((x) => x.fighters.map((p) => ({ ...p, weight_class: x.weight_class }))).find((p) => p.id === a.dataset.ufcFighter);
    try { if (f) sessionStorage.setItem(`ufc_fighter_${f.id}`, JSON.stringify(f)); } catch (_) { /* ignore */ }
  }, { passive: true, capture: true });

  async function render(container, titleEl, sourceEl) {
    container.classList.add('ufc-scope');
    container.innerHTML = '<p class="today-schedule-message">Loading the next UFC card…</p>';
    try {
      const idx = await (await fetch('/feeds/slate-index.json', { cache: 'no-store' })).json();
      const ufc = idx?.sports?.ufc;
      const key = ufc?.default_card;
      if (!key) throw new Error('no UFC card in manifest');
      const card = await (await fetch(`/${ufc.cards[key].card}`, { cache: 'no-store' })).json();
      lastCard = card;
      if (titleEl) titleEl.textContent = card.event_name || 'Next UFC card';
      const fights = [...(card.fights || [])].reverse(); // main event first
      const stale = card.market_as_of ? `Odds as of ${new Date(card.market_as_of).toLocaleString('en-US', { timeZone: 'America/New_York', timeZoneName: 'short' })}` : 'No odds pulled yet';
      container.innerHTML = `<div class="ufc-honesty"><strong>${esc(card.honesty || 'NO EDGE')}</strong> · Results-only backtest: Brier ${esc(card.backtest?.brier ?? '—')} vs 0.25 coin flip (n=${esc(card.backtest?.n ?? 0)})</div>
        <div class="ufc-card-list">${fights.map(fightCard).join('')}</div>`;
      if (sourceEl) sourceEl.textContent = `Card: ESPN · Odds: The Odds API (fight winner, total rounds) · ${stale} · Times in Eastern Time · ${fights.length} fights`;
    } catch (error) {
      container.innerHTML = '<p class="today-schedule-message">The UFC card is unavailable right now. Tap Refresh to try again.</p>';
      if (sourceEl) sourceEl.textContent = '';
      console.warn('[PropStein] UFC card unavailable:', error);
    }
  }

  window.PropSteinUFC = Object.freeze({ render });
})();
