(() => {
  const escAttr = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function installIcon(el, app) {
    if (!el || !app || !app.icon) return;
    if (el.dataset.iconId === app.id) return;
    el.dataset.iconId = app.id;
    const initials = app.initials || '?';
    el.classList.add('has-app-icon');
    el.innerHTML = `<img class="app-icon-img" src="${escAttr(app.icon)}" alt="${escAttr(app.name)}" loading="lazy"><span class="icon-fallback">${escAttr(initials)}</span>`;
    const img = el.querySelector('img');
    if (!img) return;
    img.addEventListener('load', () => el.classList.add('icon-loaded'), { once: true });
    img.addEventListener('error', () => {
      el.classList.remove('icon-loaded');
      img.remove();
    }, { once: true });
  }

  function enhanceCards() {
    if (typeof all === 'undefined') return;
    document.querySelectorAll('.card[data-id]').forEach(card => {
      const app = all.find(a => a.id === card.dataset.id);
      installIcon(card.querySelector('.icon'), app);
    });
  }

  function enhanceDetail() {
    if (typeof selected === 'undefined' || !selected) return;
    installIcon(document.querySelector('#detail .icon'), selected);
  }

  function enhanceAll() {
    enhanceCards();
    enhanceDetail();
  }

  const observer = new MutationObserver(() => requestAnimationFrame(enhanceAll));
  const start = () => {
    const grid = document.querySelector('#grid');
    const detail = document.querySelector('#detail');
    if (grid) observer.observe(grid, { childList: true, subtree: true });
    if (detail) observer.observe(detail, { childList: true, subtree: true });
    enhanceAll();
    setTimeout(enhanceAll, 500);
    setTimeout(enhanceAll, 1500);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
