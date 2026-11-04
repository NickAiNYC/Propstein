(() => {
  'use strict';

  const menu = document.getElementById('frontMenuDialog');
  const menuButton = document.getElementById('frontMenuBtn');
  const exploreButton = document.getElementById('explorePropsBtn');
  const board = document.getElementById('fullPlayerBoard');
  if (!menu || !menuButton || !exploreButton || !board) return;

  function setBoardOpen(open, scroll = false) {
    document.body.classList.toggle('front-board-open', open);
    if (open) document.getElementById('modeAllBtn')?.click();
    exploreButton.setAttribute('aria-expanded', String(open));
    exploreButton.firstChild.textContent = open ? 'Hide full player board ' : 'Explore all player props ';
    if (scroll) (open ? board : document.getElementById('todaySchedule')).scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  menuButton.addEventListener('click', () => menu.showModal());
  document.getElementById('frontMenuClose').addEventListener('click', () => menu.close());
  menu.addEventListener('click', (event) => {
    if (event.target === menu) menu.close();
  });
  exploreButton.addEventListener('click', () => setBoardOpen(!document.body.classList.contains('front-board-open'), true));
  document.getElementById('homeEdgeOpenBoard')?.addEventListener('click', () => setBoardOpen(true, true));
  const inlineSearch = document.getElementById('frontInlineSearch');
  const boardSearch = document.getElementById('searchInput');
  const cmdDialog = document.getElementById('commandPaletteDialog');
  const cmdInput = document.getElementById('cmdPaletteInput');
  const cmdResults = document.getElementById('cmdPaletteResults');

  inlineSearch?.addEventListener('input', () => {
    const query = inlineSearch.value.toLowerCase();
    const market = /receiving yards|\byards\b/.test(query) ? 'receiving_yards'
      : /\breceptions?\b/.test(query) ? 'receptions'
      : /\bpoints?\b/.test(query) ? 'points'
      : /anytime (touchdown|td)|\btouchdowns?\b/.test(query) ? 'anytime_td' : null;
    if (market) document.querySelector(`#marketChipGroup [data-market="${market}"]`)?.click();
    if (boardSearch) {
      boardSearch.value = inlineSearch.value;
      boardSearch.dispatchEvent(new Event('input', { bubbles: true }));
    }
    if (inlineSearch.value.trim() && !document.body.classList.contains('front-board-open')) setBoardOpen(true);
  });
  boardSearch?.addEventListener('input', () => {
    if (inlineSearch && inlineSearch.value !== boardSearch.value) inlineSearch.value = boardSearch.value;
  });
  document.getElementById('homeEdgeAudit')?.addEventListener('click', () => document.getElementById('clvReportBtn')?.click());

  const STATIC_COMMANDS = [
    // Markets
    { category: 'Markets', title: 'NFL Receiving Yards', desc: 'Pre-kickoff compound distribution & vig boundaries', action: () => { setBoardOpen(true, true); document.querySelector('#marketChipGroup [data-market="receiving_yards"]')?.click(); } },
    { category: 'Markets', title: 'NFL Receptions', desc: 'Discrete NegBin count model & push margins', action: () => { setBoardOpen(true, true); document.querySelector('#marketChipGroup [data-market="receptions"]')?.click(); } },
    { category: 'Markets', title: 'NFL Anytime Touchdown', desc: 'Arrival probabilities & scoring edges', action: () => { setBoardOpen(true, true); document.querySelector('#marketChipGroup [data-market="anytime_td"]')?.click(); } },
    { category: 'Markets', title: 'NBA Points', desc: 'Basketball player prop lines & FanDuel feeds', action: () => { document.querySelector('.sport-switch-btn[data-sport="nba"]')?.click(); setBoardOpen(true, true); } },

    // Research & Evidence
    { category: 'Research', title: 'Track Record & Evidence Audit (/performance/)', desc: 'Graded decisions, CLV beat-close rate & sample size gate', url: '/performance/' },
    { category: 'Research', title: 'Model Methodology (/methodology/)', desc: 'NegBin-Gamma distribution math, parameters & holdout', url: '/methodology/' },
    { category: 'Research', title: 'Holdout CLV Audit Report', desc: 'View complete cryptographic root ledger and close line deltas', action: () => document.getElementById('clvReportBtn')?.click() },
    { category: 'Research', title: 'Availability & Injury Context Drawer', desc: 'Teammate injury absorption and vacated target models', action: () => { setBoardOpen(true); document.getElementById('availabilityToggle')?.click(); document.getElementById('availabilityDetails')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } },
    { category: 'Research', title: 'Personal CLV Slip & Ledger', desc: 'Review logged positions and tracking records', action: () => document.getElementById('portfolioBtn')?.click() },

    // Pages & Compliance
    { category: 'Pages', title: 'Terminal Overview (Home)', desc: 'Main research terminal view & game slate', action: () => { setBoardOpen(false, true); window.scrollTo({ top: 0, behavior: 'smooth' }); } },
    { category: 'Pages', title: 'Terms of Service (/legal/terms/)', desc: 'Institutional research terms and platform disclaimer', url: '/legal/terms/' },
    { category: 'Pages', title: 'Privacy Policy (/legal/privacy/)', desc: 'Data governance, zero third-party cookie policy', url: '/legal/privacy/' },
    { category: 'Pages', title: 'Responsible Gaming (/legal/responsible-gaming/)', desc: '1-800-GAMBLER resources and self-exclusion guidance', url: '/legal/responsible-gaming/' },
  ];

  let currentItems = [];
  let activeIndex = 0;

  function renderPaletteResults(query = '') {
    if (!cmdResults) return;
    const q = query.trim().toLowerCase();
    let items = [];

    if (!q) {
      items = [...STATIC_COMMANDS];
    } else {
      items = STATIC_COMMANDS.filter((cmd) => cmd.title.toLowerCase().includes(q) || cmd.desc.toLowerCase().includes(q) || cmd.category.toLowerCase().includes(q));
    }

    if (q && window.app && window.app.state && Array.isArray(window.app.state.slate)) {
      const matchedPlayers = [];
      const seen = new Set();
      for (const row of window.app.state.slate) {
        if (!row || !row.player_name) continue;
        if (seen.has(row.player_name)) continue;
        if (row.player_name.toLowerCase().includes(q) || (row.team && row.team.toLowerCase().includes(q))) {
          seen.add(row.player_name);
          const pos = row.position || '';
          const team = row.team || '';
          const opp = row.opponent || '';
          const fair = row.fair_line !== undefined ? ` · Fair: ${row.fair_line}` : '';
          matchedPlayers.push({
            category: 'Players',
            title: row.player_name,
            desc: `${pos} ${team}${opp ? ' vs ' + opp : ''}${fair}`,
            action: () => {
              setBoardOpen(true, true);
              if (boardSearch) {
                boardSearch.value = row.player_name;
                boardSearch.dispatchEvent(new Event('input', { bubbles: true }));
              }
            },
          });
          if (matchedPlayers.length >= 8) break;
        }
      }
      items = [...matchedPlayers, ...items];
    }

    currentItems = items;
    activeIndex = 0;

    if (items.length === 0) {
      cmdResults.innerHTML = `<div class="cmd-no-results">No matching commands or players for "${q}"</div>`;
      return;
    }

    const groups = {};
    items.forEach((item, idx) => {
      if (!groups[item.category]) groups[item.category] = [];
      groups[item.category].push({ item, idx });
    });

    let html = '';
    for (const [cat, catItems] of Object.entries(groups)) {
      html += `<div class="cmd-group-label">${cat}</div>`;
      for (const { item, idx } of catItems) {
        const activeCls = idx === activeIndex ? ' cmd-item-active' : '';
        html += `<div class="cmd-item${activeCls}" data-idx="${idx}" role="option" aria-selected="${idx === activeIndex}">
          <div class="cmd-item-title">
            <span>${item.title}</span>
            <span class="cmd-item-badge">${item.category}</span>
          </div>
          <div class="cmd-item-desc">${item.desc}</div>
        </div>`;
      }
    }
    cmdResults.innerHTML = html;
  }

  function highlightActive() {
    if (!cmdResults) return;
    const itemEls = cmdResults.querySelectorAll('.cmd-item');
    itemEls.forEach((el) => {
      const idx = parseInt(el.dataset.idx, 10);
      const isAct = idx === activeIndex;
      el.classList.toggle('cmd-item-active', isAct);
      el.setAttribute('aria-selected', String(isAct));
      if (isAct) el.scrollIntoView({ block: 'nearest' });
    });
  }

  function executeActive() {
    const item = currentItems[activeIndex];
    if (!item) return;
    if (cmdDialog) cmdDialog.close();
    if (item.url) {
      window.location.href = item.url;
    } else if (item.action) {
      item.action();
    }
  }

  function openCommandPalette() {
    if (!cmdDialog) {
      inlineSearch?.focus();
      inlineSearch?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    renderPaletteResults('');
    cmdDialog.showModal();
    if (cmdInput) {
      cmdInput.value = '';
      cmdInput.focus();
    }
  }

  cmdInput?.addEventListener('input', () => {
    renderPaletteResults(cmdInput.value);
  });

  cmdInput?.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (currentItems.length > 0) {
        activeIndex = (activeIndex + 1) % currentItems.length;
        highlightActive();
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (currentItems.length > 0) {
        activeIndex = (activeIndex - 1 + currentItems.length) % currentItems.length;
        highlightActive();
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      executeActive();
    }
  });

  cmdResults?.addEventListener('click', (e) => {
    const target = e.target.closest('.cmd-item');
    if (!target) return;
    const idx = parseInt(target.dataset.idx, 10);
    if (!isNaN(idx) && currentItems[idx]) {
      activeIndex = idx;
      executeActive();
    }
  });

  cmdDialog?.addEventListener('click', (e) => {
    if (e.target === cmdDialog) cmdDialog.close();
  });

  document.getElementById('headerSearchTrigger')?.addEventListener('click', openCommandPalette);
  document.getElementById('bottomNavSlate')?.addEventListener('click', () => setBoardOpen(true, true));
  document.getElementById('bottomNavWatchlist')?.addEventListener('click', () => setBoardOpen(true, true));
  document.getElementById('navMarkets')?.addEventListener('click', (e) => {
    e.preventDefault();
    setBoardOpen(true, true);
    document.getElementById('marketChipGroup')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.getElementById('navOverview')?.addEventListener('click', (e) => {
    e.preventDefault();
    document.getElementById('slateBoard')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      openCommandPalette();
    }
  });
  menu.querySelector('.front-menu-actions').addEventListener('click', (event) => {
    const action = event.target.closest('[data-front-action]')?.dataset.frontAction;
    if (!action) return;
    menu.close();
    if (action === 'props') setBoardOpen(true, true);
    if (action === 'search') {
      openCommandPalette();
    }
    if (action === 'saved') document.getElementById('portfolioBtn')?.click();
    if (action === 'alerts') {
      setBoardOpen(true);
      document.getElementById('availabilityToggle')?.click();
      document.getElementById('availabilityDetails')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    if (action === 'settings') document.getElementById('mobileMenuBtn')?.click();
    if (action === 'membership') document.getElementById('pricingBtn')?.click();
  });
})();
