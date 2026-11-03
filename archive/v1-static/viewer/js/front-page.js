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
  function openSearch() {
    inlineSearch?.focus();
    inlineSearch?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      openSearch();
    }
  });
  menu.querySelector('.front-menu-actions').addEventListener('click', (event) => {
    const action = event.target.closest('[data-front-action]')?.dataset.frontAction;
    if (!action) return;
    menu.close();
    if (action === 'props') setBoardOpen(true, true);
    if (action === 'search') {
      openSearch();
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
