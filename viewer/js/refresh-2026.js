/* PropStein 2026 refresh — small behaviours that pair with refresh-2026.css.
   Mobile: condense the sticky header while scrolling down, restore on
   scroll up. No dependencies; safe to remove with the stylesheet.

   Collapsing the header changes its height, which moves the page under the
   finger (and the browser may nudge scrollY to compensate). A per-frame
   6px direction check read that nudge as "scrolled up" and re-expanded the
   header, which flickered between states. So:
   - measure travel from the last turning point, not the previous frame
     (condense after CONDENSE_PX down, expand after EXPAND_PX up);
   - ignore scroll for LOCK_MS after each toggle so the layout shift and
     the 0.22s collapse transition can settle. */
(() => {
  'use strict';
  const header = document.querySelector('.pw-terminal-chrome');
  if (!header) return;
  const mq = window.matchMedia('(max-width: 768px)');
  const TOP_PX = 120;     // never condense above this
  const TOP_EXPAND_PX = 40; // always expand near the very top (lower than TOP_PX so the
                            // height change from condensing can't drop us straight back)
  const CONDENSE_PX = 48;
  const EXPAND_PX = 24;
  const LOCK_MS = 350;

  let condensed = header.classList.contains('rf-condensed');
  let anchorY = window.scrollY; // turning point we measure travel from
  let lockUntil = 0;
  let ticking = false;

  function set(next, y) {
    if (next === condensed) return;
    condensed = next;
    header.classList.toggle('rf-condensed', next);
    anchorY = y;
    lockUntil = performance.now() + LOCK_MS;
  }

  function update() {
    ticking = false;
    const y = window.scrollY;
    if (!mq.matches) {
      set(false, y);
      return;
    }
    if (performance.now() < lockUntil) {
      anchorY = y; // absorb the shift caused by our own toggle
      return;
    }
    if (y < TOP_EXPAND_PX) {
      set(false, y);
      anchorY = y;
      return;
    }
    if (condensed) {
      if (y > anchorY) anchorY = y; // still going down: move the turning point
      else if (anchorY - y > EXPAND_PX) set(false, y);
    } else {
      if (y < anchorY) anchorY = y; // still going up: move the turning point
      else if (y > TOP_PX && y - anchorY > CONDENSE_PX) set(true, y);
    }
  }

  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
  }, { passive: true });
  mq.addEventListener?.('change', update);
})();
