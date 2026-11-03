/**
 * PropWire Sport Registry
 *
 * Single registration point for sport adapters. Each adapter fully describes
 * one sport's markets, positions/roles, slate naming, period label, feed
 * filenames, grading hooks, correlation rules, storage namespaces, and UI
 * labels — so viewer code never branches on a hardcoded sport again.
 *
 * Load order (all `defer`, executed in document order):
 *   1. /js/sports/registry.js  (this file)
 *   2. /js/sports/<sport>.js   (each adapter self-registers)
 *   3. /app.js                 (reads the active adapter; never hardcodes)
 */
(() => {
  'use strict';

  const adapters = new Map();

  const PropWireSports = {
    /** Register an adapter. Throws on duplicates or missing required fields. */
    register(adapter) {
      if (!adapter || typeof adapter !== 'object') {
        throw new Error('[PropWireSports] register(object) required');
      }
      if (!adapter.id || typeof adapter.id !== 'string') {
        throw new Error('[PropWireSports] adapter.id (string) required');
      }
      if (adapters.has(adapter.id)) {
        throw new Error(`[PropWireSports] duplicate adapter id: ${adapter.id}`);
      }
      const required = ['label', 'periodNoun', 'markets', 'defaultMarket', 'slates'];
      for (const field of required) {
        if (!(field in adapter)) {
          throw new Error(`[PropWireSports] adapter "${adapter.id}" missing required field: ${field}`);
        }
      }
      adapters.set(adapter.id, Object.freeze(adapter));
      return adapter;
    },

    /** Get an adapter by id, or null if unknown. */
    get(id) {
      return adapters.get(String(id)) || null;
    },

    /** Get an adapter by id or throw — use where a sport MUST exist. */
    require(id) {
      const adapter = adapters.get(String(id));
      if (!adapter) {
        throw new Error(`[PropWireSports] unknown sport "${String(id)}". Registered: [${[...adapters.keys()].join(', ')}]`);
      }
      return adapter;
    },

    /** All registered sport ids in registration order. */
    ids() {
      return [...adapters.keys()];
    },

    /**
     * Boot sport: the per-device preference written by the sport switcher
     * (propwire_active_sport), validated against registered adapters.
     * Anything invalid/unknown/tampered falls back to NFL. Called by app.js
     * after all adapters have registered, so the validation is meaningful.
     */
    defaultId() {
      try {
        const stored = localStorage.getItem('propwire_active_sport');
        if (stored && adapters.has(stored)) return stored;
      } catch (_) { /* storage unavailable */ }
      return 'nfl';
    },
  };

  Object.freeze(PropWireSports);
  window.PropSteinSports = PropWireSports;
  window.PropWireSports = PropWireSports;
})();
