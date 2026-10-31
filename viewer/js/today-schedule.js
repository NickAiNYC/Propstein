(() => {
  'use strict';

  const schedule = document.getElementById('todaySchedule');
  const gamesEl = document.getElementById('todayScheduleGames');
  const leagueNavs = [document.getElementById('sportSwitcher'), document.getElementById('mobileSportSwitcher')].filter(Boolean);
  if (!schedule || !gamesEl || !leagueNavs.length) return;

  const leagueNames = { nba: 'NBA', nfl: 'NFL' };
  const leaguePaths = { nba: 'basketball/nba', nfl: 'football/nfl' };
  const timeZoneSelect = document.getElementById('todayScheduleTimezone');
  const selectedTimeZone = () => timeZoneSelect?.value === 'et' ? 'America/New_York' : Intl.DateTimeFormat().resolvedOptions().timeZone;
  const teamAliases = { LAR: 'LA', WSH: 'WAS', NY: 'NYK', GS: 'GSW', SA: 'SAS', NO: 'NOP' };
  const activeSport = () => localStorage.getItem('propwire_active_sport') === 'nba' ? 'nba' : 'nfl';
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

  function easternDate(date = new Date()) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(date);
    const part = (type) => parts.find((item) => item.type === type).value;
    return `${part('year')}${part('month')}${part('day')}`;
  }

  const teamCode = (value) => teamAliases[value] || value;
  const eventTeams = (event) => {
    const competitors = event.competitions?.[0]?.competitors || [];
    return {
      away: teamCode(competitors.find((team) => team.homeAway === 'away')?.team?.abbreviation),
      home: teamCode(competitors.find((team) => team.homeAway === 'home')?.team?.abbreviation)
    };
  };

  function gameCard(event, index) {
    const competition = event.competitions?.[0] || {};
    const teams = competition.competitors || [];
    const away = teams.find((team) => team.homeAway === 'away') || {};
    const home = teams.find((team) => team.homeAway === 'home') || {};
    const status = competition.status || event.status || {};
    const state = status.type?.state || 'pre';
    const statusText = state === 'pre' ? 'Scheduled' : (status.type?.shortDetail || status.type?.detail || '');
    const date = new Date(event.date || competition.date);
    const time = Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('en-US', {
      timeZone: selectedTimeZone(), weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
    }).format(date);
    const team = (entry) => {
      const name = escapeHtml(entry.team?.shortDisplayName || entry.team?.displayName || 'TBD');
      const initials = escapeHtml(entry.team?.abbreviation || '—');
      const logo = entry.team?.logo || entry.team?.logos?.[0]?.href;
      const safeLogo = /^https:\/\/a\.espncdn\.com\//.test(logo || '') ? logo : '';
      return `<div class="today-team"><span class="today-team-logo">${safeLogo ? `<img src="${escapeHtml(safeLogo)}" alt="" loading="lazy">` : `<span>${initials}</span>`}</span><span class="today-team-name"><b>${initials}</b><strong>${name}</strong></span></div>`;
    };
    const odds = competition.odds?.[0];
    const spread = odds?.details ? `<span>SPREAD ${escapeHtml(odds.details)}</span>` : '';
    const total = Number.isFinite(Number(odds?.overUnder)) && odds?.overUnder != null
      ? `<span>O/U ${Number(odds.overUnder).toFixed(1)}</span>` : '';
    const context = spread || total ? `<div class="today-game-context">${spread}${total}</div>` : '';
    const score = state === 'pre' ? '<span class="today-versus">VS</span>' :
      `<span class="today-score">${escapeHtml(away.score ?? '0')} <span>–</span> ${escapeHtml(home.score ?? '0')}</span>`;
    return `<article class="today-game-card">
      <button class="today-game-trigger" type="button" data-game-index="${index}" aria-expanded="false" aria-controls="todayGameProps${index}" aria-label="${escapeHtml(away.team?.displayName || 'Away team')} at ${escapeHtml(home.team?.displayName || 'home team')}: show player prop projections">
        <div class="today-game-top"><span>${escapeHtml(time)}</span><span class="today-game-status ${state === 'in' ? 'is-live' : ''}">${escapeHtml(statusText || (state === 'post' ? 'Final' : 'Scheduled'))}</span></div>
        <div class="today-game-matchup">${team(away)}<div class="today-game-center">${score}</div>${team(home)}</div>
        ${context}
        <div class="today-game-action"><span data-prop-count>PLAYER PROPS</span><span class="today-game-chevron" aria-hidden="true">⌄</span></div>
      </button>
      <div class="today-game-props" id="todayGameProps${index}" hidden></div>
    </article>`;
  }

  let requestNumber = 0;
  let currentEvents = [];
  const modelCache = new Map();
  let supportingDataPromise;
  const fetchJson = async (path) => {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) {
      const error = new Error(`Model data unavailable: ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  };

  async function modelSources(sport, dateKey) {
    const key = `${sport}:${dateKey}`;
    if (!modelCache.has(key)) {
      modelCache.set(key, (async () => {
        if (sport === 'nba') {
          const date = `${dateKey.slice(0, 4)}-${dateKey.slice(4, 6)}-${dateKey.slice(6)}`;
          try {
            const [games, slate] = await Promise.all([
              fetchJson(`/nba_games_${date}.json`), fetchJson(`/nba_slate_${date}.json`)
            ]);
            return [{ games, slate }];
          } catch (error) {
            if (error.status === 404) return [];
            throw error;
          }
        }
        const index = await fetchJson('/feeds/slate-index.json');
        const slates = Object.values(index.sports?.nfl?.slates || {}).filter((item) => !item.historical && item.games && item.slate);
        return Promise.all(slates.map(async (item) => {
          const [games, slate] = await Promise.all([fetchJson(`/${item.games}`), fetchJson(`/${item.slate}`)]);
          return { games, slate };
        }));
      })().catch((error) => { modelCache.delete(key); throw error; }));
    }
    return modelCache.get(key);
  }

  function supportingData() {
    if (!supportingDataPromise) {
      supportingDataPromise = Promise.allSettled([
        fetchJson('/feeds/player_photos.json'), fetchJson('/live_odds_feed.json')
      ]).then(([photos, odds]) => ({
        photos: photos.status === 'fulfilled' ? photos.value : {},
        quotes: odds.status === 'fulfilled' && Array.isArray(odds.value.quotes) ? odds.value.quotes : []
      }));
    }
    return supportingDataPromise;
  }

  const normalizedName = (name) => String(name || '').toLowerCase().normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '').replace(/[.,'’]/g, '').replace(/-/g, ' ')
    .split(/\s+/).filter((part) => part && !['jr', 'sr', 'ii', 'iii', 'iv', 'v'].includes(part)).join(' ').trim();

  function playerPhoto(row, photoMap) {
    const key = photoMap.by_name?.[normalizedName(row.player_display_name)] || row.player_id;
    const url = photoMap.photos?.[String(key)]?.url || '';
    const safeUrl = /^https:\/\/(?:a\.espncdn\.com\/i\/headshots\/|cdn\.nba\.com\/headshots\/)/.test(url) ? url : '';
    const initials = String(row.player_display_name || '').split(/\s+/).map((part) => part[0] || '').join('').slice(0, 2).toUpperCase();
    return `<span class="today-prop-photo"><span>${escapeHtml(initials)}</span>${safeUrl ? `<img src="${escapeHtml(safeUrl)}" alt="" loading="lazy">` : ''}</span>`;
  }

  function matchingLine(row, game, sport, dateKey, quotes) {
    const market = sport === 'nba' ? 'points' : 'receiving_yards';
    const projection = Number(sport === 'nba' ? row.proj_pts : row.proj_yards);
    const candidates = quotes.filter((quote) => quote.game_id === game.game_id && quote.market === market
      && (String(quote.player_id) === String(row.player_id) || normalizedName(quote.player_name) === normalizedName(row.player_display_name))
      && !/synthetic|fixture/i.test(`${quote.book || ''} ${quote.source || ''}`)
      && /^https:\/\//.test(quote.source_url || '')
      && Number.isFinite(Number(quote.line)) && Number.isFinite(Number(quote.over_odds)) && Number.isFinite(Number(quote.under_odds))
      && !Number.isNaN(Date.parse(quote.observed_at)) && easternDate(new Date(quote.observed_at)) === dateKey);
    candidates.sort((a, b) => Number(b.verified === true) - Number(a.verified === true)
      || Math.abs(Number(a.line) - projection) - Math.abs(Number(b.line) - projection));
    return candidates[0] || null;
  }

  function lineBoxes(quote, projection) {
    if (!quote) return '<p class="today-no-line">No listed Over/Under line for this player today.</p>';
    const line = Number(quote.line).toFixed(1);
    const odds = (value) => Number(value) > 0 ? `+${Number(value)}` : String(Number(value));
    const lean = projection > Number(quote.line) ? 'over' : projection < Number(quote.line) ? 'under' : '';
    const observed = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' }).format(new Date(quote.observed_at));
    return `<div class="today-line-boxes" aria-label="Last listed Over and Under prices">
      <span class="today-line-box over${lean === 'over' ? ' model-lean' : ''}"><b><span class="today-line-arrow" aria-hidden="true">↑</span> OVER ${line}</b><small>${escapeHtml(odds(quote.over_odds))}</small></span>
      <span class="today-line-box under${lean === 'under' ? ' model-lean' : ''}"><b><span class="today-line-arrow" aria-hidden="true">↓</span> UNDER ${line}</b><small>${escapeHtml(odds(quote.under_odds))}</small></span>
    </div><p class="today-line-source">${escapeHtml(quote.book)} · last seen ${escapeHtml(observed)} ET · ${quote.verified === true ? 'receipt verified' : 'unverified line'}</p>`;
  }

  function projectionRow(row, sport, game, dateKey, photos, quotes) {
    const projection = Number(sport === 'nba' ? row.proj_pts : row.proj_yards);
    const secondary = sport === 'nba' ? `${Number(row.proj_reb).toFixed(1)} REB · ${Number(row.proj_ast).toFixed(1)} AST` : `${Number(row.proj_rec).toFixed(1)} receptions projected`;
    const line = matchingLine(row, game, sport, dateKey, quotes);
    return `<div class="today-prop-row">
      <div class="today-prop-summary">${playerPhoto(row, photos)}<div class="today-prop-player"><strong>${escapeHtml(row.player_display_name)}</strong><span>${escapeHtml(row.team)} · ${escapeHtml(row.position || row.position_hist || '')} · ${escapeHtml(secondary)}</span></div><div class="today-prop-projection"><b>${Number.isFinite(projection) ? projection.toFixed(1) : '—'}</b><small>${sport === 'nba' ? 'PTS PROJ' : 'YDS PROJ'}</small></div></div>
      ${lineBoxes(line, projection)}
    </div>`;
  }

  async function showGameProps(button) {
    const panel = document.getElementById(button.getAttribute('aria-controls'));
    if (button.getAttribute('aria-expanded') === 'true') {
      button.setAttribute('aria-expanded', 'false');
      panel.hidden = true;
      return;
    }
    button.setAttribute('aria-expanded', 'true');
    panel.hidden = false;
    if (panel.dataset.loaded) return;
    panel.innerHTML = '<p class="today-prop-message">Loading player projections…</p>';
    const event = currentEvents[Number(button.dataset.gameIndex)];
    const sport = activeSport();
    const dateKey = easternDate(new Date(event.date));
    try {
      const [sources, extras] = await Promise.all([modelSources(sport, dateKey), supportingData()]);
      if (!button.isConnected) return;
      const { away, home } = eventTeams(event);
      const match = sources.flatMap((source) => (Array.isArray(source.games) ? source.games : []).map((game) => ({ game, slate: source.slate })))
        .find(({ game }) => game.gameday?.replaceAll('-', '') === dateKey && teamCode(game.away_team) === away && teamCode(game.home_team) === home && !game._fixture);
      const rows = match && Array.isArray(match.slate)
        ? match.slate.filter((row) => row.game_id === match.game.game_id && !row._fixture && (row.status === 'ACT' || row.status === 'ACTIVE') && !row.excl_reason)
        : [];
      rows.sort((a, b) => Number(b.proj_yards ?? b.proj_pts ?? 0) - Number(a.proj_yards ?? a.proj_pts ?? 0));
      panel.innerHTML = rows.length
        ? `<div class="today-prop-heading"><strong>${rows.length} player props</strong><span>Model estimates · line snapshots, not picks</span></div><div class="today-prop-list">${rows.map((row) => projectionRow(row, sport, match.game, dateKey, extras.photos, extras.quotes)).join('')}</div>`
        : '<p class="today-prop-message">No PropStein player projections are available for this matchup yet.</p>';
      panel.dataset.loaded = 'true';
    } catch (error) {
      if (!button.isConnected) return;
      panel.innerHTML = '<p class="today-prop-message">Player projections are unavailable right now. Close and reopen the game to retry.</p>';
      console.warn('[PropStein] Game projections unavailable:', error);
    }
  }
  async function loadTodayGames() {
    modelCache.clear();
    supportingDataPromise = null;
    const sport = activeSport();
    const dateKey = easternDate();
    const dateLabel = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'
    }).format(new Date());
    document.getElementById('todayScheduleTitle').textContent = `${leagueNames[sport]} games today`;
    document.getElementById('todayScheduleDate').textContent = `${dateLabel} · Eastern schedule date`;
    gamesEl.innerHTML = '<p class="today-schedule-message">Loading today’s games…</p>';
    document.getElementById('todayScheduleSource').textContent = '';
    const currentRequest = ++requestNumber;
    try {
      const url = `https://site.api.espn.com/apis/site/v2/sports/${leaguePaths[sport]}/scoreboard?dates=${dateKey}&limit=1000`;
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Schedule request failed: ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.events)) throw new Error('Invalid schedule response');
      if (currentRequest !== requestNumber) return;
      const games = data.events.filter((event) => {
        const date = new Date(event.date);
        return !Number.isNaN(date.getTime()) && easternDate(date) === dateKey;
      }).sort((a, b) => new Date(a.date) - new Date(b.date));
      currentEvents = games;
      gamesEl.innerHTML = games.length ? games.map(gameCard).join('') : `<p class="today-schedule-message">No ${leagueNames[sport]} games are scheduled for today.</p>`;
      document.getElementById('todayScheduleSource').textContent = `Schedule and scores: ESPN · Times shown in ${timeZoneSelect?.value === 'et' ? 'Eastern' : 'your local'} time · ${games.length} game${games.length === 1 ? '' : 's'}`;
      modelSources(sport, dateKey).then((sources) => {
        if (currentRequest !== requestNumber) return;
        games.forEach((event, index) => {
          const { away, home } = eventTeams(event);
          const match = sources.flatMap((source) => (Array.isArray(source.games) ? source.games : []).map((game) => ({ game, slate: source.slate })))
            .find(({ game }) => game.gameday?.replaceAll('-', '') === dateKey && teamCode(game.away_team) === away && teamCode(game.home_team) === home && !game._fixture);
          const count = match && Array.isArray(match.slate)
            ? match.slate.filter((row) => row.game_id === match.game.game_id && !row._fixture && (row.status === 'ACT' || row.status === 'ACTIVE') && !row.excl_reason).length : 0;
          const label = gamesEl.querySelector(`[data-game-index="${index}"] [data-prop-count]`);
          if (label && count) label.textContent = `PLAYER PROPS (${count})`;
        });
      }).catch(() => {});
    } catch (error) {
      if (currentRequest !== requestNumber) return;
      gamesEl.innerHTML = '<p class="today-schedule-message">Today’s schedule is unavailable. Tap Refresh to try again.</p>';
      document.getElementById('todayScheduleSource').textContent = '';
      console.warn('[PropWire] Today schedule unavailable:', error);
    }
  }

  let ufcActive = false;

  function showComingSoon(sport) {
    ufcActive = false;
    document.body.classList.remove('ufc-active');
    const label = sport.toUpperCase();
    document.getElementById('comingSoonLogo').src = `/league-logos/${sport === 'ufc' ? 'ufc.svg' : 'nhl.png'}`;
    document.getElementById('comingSoonTitle').textContent = `${label} coming soon`;
    document.getElementById('comingSoonMessage').textContent = `${label} schedules and research are on the way. Select NBA or NFL to see today’s games.`;
    document.getElementById('comingSoonPage').hidden = false;
    document.body.classList.add('coming-soon-active');
    document.querySelectorAll('#sportSwitcher [data-sport], #mobileSportSwitcher [data-sport]').forEach((button) => {
      const selected = button.dataset.sport === sport;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-checked', String(selected));
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function showUfc() {
    document.getElementById('comingSoonPage').hidden = true;
    document.body.classList.remove('coming-soon-active');
    document.querySelectorAll('#sportSwitcher [data-sport], #mobileSportSwitcher [data-sport]').forEach((button) => {
      const selected = button.dataset.sport === 'ufc';
      button.classList.toggle('active', selected);
      button.setAttribute('aria-checked', String(selected));
    });
    ufcActive = true;
    document.body.classList.add('ufc-active');
    requestNumber += 1; // cancel any in-flight league schedule render
    document.getElementById('todayScheduleDate').textContent = 'Next UFC card · fight winner and total rounds';
    if (window.PropSteinUFC) {
      window.PropSteinUFC.render(gamesEl, document.getElementById('todayScheduleTitle'), document.getElementById('todayScheduleSource'));
    } else {
      gamesEl.innerHTML = '<p class="today-schedule-message">The UFC card is unavailable right now.</p>';
    }
    document.getElementById('todaySchedule')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function showSchedule() {
    ufcActive = false;
    document.body.classList.remove('ufc-active');
    gamesEl.classList.remove('ufc-scope');
    document.getElementById('comingSoonPage').hidden = true;
    document.body.classList.remove('coming-soon-active');
    document.querySelectorAll('#sportSwitcher [data-sport], #mobileSportSwitcher [data-sport]').forEach((button) => {
      const selected = button.dataset.sport === activeSport();
      button.classList.toggle('active', selected);
      button.setAttribute('aria-checked', String(selected));
    });
    loadTodayGames();
  }

  leagueNavs.forEach((leagueNav) => leagueNav.addEventListener('click', (event) => {
    const button = event.target.closest('[data-sport]');
    if (!button) return;
    if (button.dataset.sport === 'ufc') showUfc();
    else if (button.dataset.sport === 'nhl') showComingSoon(button.dataset.sport);
    else if (button.dataset.sport === activeSport()) showSchedule();
  }));
  document.getElementById('comingSoonBack').addEventListener('click', showSchedule);
  document.getElementById('todayScheduleRefresh').addEventListener('click', () => (ufcActive ? showUfc() : loadTodayGames()));
  timeZoneSelect?.addEventListener('change', () => (ufcActive ? showUfc() : loadTodayGames()));
  gamesEl.addEventListener('click', (event) => {
    const button = event.target.closest('.today-game-trigger');
    if (button) showGameProps(button);
  });
  gamesEl.addEventListener('error', (event) => {
    if (event.target.matches('.today-team-logo img')) event.target.replaceWith(document.createTextNode('—'));
    if (event.target.matches('.today-prop-photo img')) event.target.remove();
  }, true);
  loadTodayGames();
})();
