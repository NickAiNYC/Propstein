(() => {
  'use strict';
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const root = document.getElementById('ufcFighter');
  const id = new URLSearchParams(location.search).get('id');
  const back = '<a class="ufc-back" href="/">← PropStein</a>';

  function draw(f, partial) {
    document.title = `${f.name} · UFC · PropStein`;
    const img = /^https:\/\/a\.espncdn\.com\//.test(f.headshot || '') ? f.headshot : '';
    const stat = (label, value) => `<div><span>${esc(label)}</span><b>${esc(value ?? '—')}</b></div>`;
    const recent = (f.recent || []).map((h) => `<div><small>${esc(h.date)}</small><span>${esc(h.opponent)}<br><small>${h.finish ? `Finish · R${esc(h.round)}` : 'Decision'}</small></span><span class="r-${esc(h.result)}">${esc(h.result)}</span></div>`).join('');
    root.innerHTML = `${back}
      <section class="ufc-hero"><span class="ufc-photo">${img ? `<img src="${esc(img)}" alt="" fetchpriority="high">` : ''}</span>
        <div><h1>${esc(f.name)}</h1><p>${[f.weight_class, f.record, f.stance].filter(Boolean).map(esc).join(' · ')}</p></div></section>
      <div class="ufc-stats">${stat('Elo rating', f.elo)}${stat('UFC fights (2020+)', f.ufc_fights)}${stat('Finish rate', f.finish_rate == null ? null : `${Math.round(f.finish_rate * 100)}%`)}${stat('Age', f.age)}${stat('Reach', f.reach_in ? `${f.reach_in}"` : null)}${stat('Height', f.height)}</div>
      <p class="ufc-note">NO EDGE · ratings are research only, not validated against closing lines.</p>
      <h2>Recent UFC fights</h2>
      <div class="ufc-history">${recent || (partial ? '<div class="ufc-skel" style="height:44px"></div>' : '<div><span></span><span>No UFC fights since 2020</span><span></span></div>')}</div>
      <p class="ufc-src">Bio and results: ESPN · Ratings: PropStein Elo</p>`;
    root.setAttribute('aria-busy', partial ? 'true' : 'false');
  }

  // Instant paint from the card the user tapped (written by js/sports/ufc.js).
  try {
    const cached = JSON.parse(sessionStorage.getItem(`ufc_fighter_${id}`) || 'null');
    if (cached) draw(cached, true);
  } catch (_) { /* storage unavailable */ }

  fetch('/ufc_fighters.json', { credentials: 'same-origin', mode: 'cors' }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }).then((all) => {
    const f = all[id];
    if (f) draw(f, false);
    else root.innerHTML = `${back}<p>Fighter not found.</p>`;
  }).catch(() => {
    if (root.getAttribute('aria-busy') !== 'false') root.innerHTML = `${back}<p>Fighter data unavailable. Try again shortly.</p>`;
  });
})();
