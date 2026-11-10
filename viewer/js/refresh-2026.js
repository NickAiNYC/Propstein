/* PropStein 2026 refresh — small behaviours that pair with refresh-2026.css.
   Mobile: condense the sticky header while scrolling down, restore on
   scroll up. No dependencies; safe to remove with the stylesheet. */
(() => {
  'use strict';
  const header = document.querySelector('.pw-terminal-chrome');
  if (!header) return;
  const mq = window.matchMedia('(max-width: 768px)');
  let lastY = window.scrollY;
  let ticking = false;

  function update() {
    ticking = false;
    const y = window.scrollY;
    if (!mq.matches || y < 120) {
      header.classList.remove('rf-condensed');
    } else if (y > lastY + 6) {
      header.classList.add('rf-condensed');
    } else if (y < lastY - 6) {
      header.classList.remove('rf-condensed');
    }
    lastY = y;
  }

  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
  }, { passive: true });
  mq.addEventListener?.('change', update);
})();
