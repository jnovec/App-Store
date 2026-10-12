(() => {
  const PAGE_SIZE = 100;
  let page = 1;

  function ensurePager() {
    let pager = document.querySelector('#novecPagination');
    if (pager) return pager;
    const empty = document.querySelector('#empty');
    if (!empty || !empty.parentNode) return null;
    pager = document.createElement('div');
    pager.id = 'novecPagination';
    pager.className = 'novec-pagination';
    empty.parentNode.insertBefore(pager, empty.nextSibling);
    return pager;
  }

  function filteredRows() {
    const qv = $('#q').value.toLowerCase();
    const cat = $('#cat').value;
    const st = $('#status').value;
    return all.filter(a =>
      (!qv || (a.name + ' ' + a.description + ' ' + a.tags.join(' ')).toLowerCase().includes(qv)) &&
      (!cat || a.tags.includes(cat)) &&
      (!st || (st === 'ready' ? a.ready : !a.ready))
    );
  }

  function renderPager(total, totalPages) {
    const pager = ensurePager();
    if (!pager) return;
    if (totalPages <= 1) {
      pager.innerHTML = '';
      pager.hidden = true;
      return;
    }
    pager.hidden = false;
    const parts = [];
    parts.push(`<button class="btn novec-page-btn" data-page="1" ${page === 1 ? 'disabled' : ''}>« First</button>`);
    parts.push(`<button class="btn novec-page-btn" data-page="${page - 1}" ${page === 1 ? 'disabled' : ''}>‹ Previous</button>`);

    let from = Math.max(1, page - 2);
    let to = Math.min(totalPages, page + 2);
    if (page <= 3) to = Math.min(totalPages, 5);
    if (page >= totalPages - 2) from = Math.max(1, totalPages - 4);
    if (from > 1) parts.push('<span class="novec-page-gap">…</span>');
    for (let p = from; p <= to; p++) {
      parts.push(`<button class="btn novec-page-btn ${p === page ? 'primary' : ''}" data-page="${p}">${p}</button>`);
    }
    if (to < totalPages) parts.push('<span class="novec-page-gap">…</span>');

    parts.push(`<button class="btn novec-page-btn" data-page="${page + 1}" ${page === totalPages ? 'disabled' : ''}>Next ›</button>`);
    parts.push(`<button class="btn novec-page-btn" data-page="${totalPages}" ${page === totalPages ? 'disabled' : ''}>Last »</button>`);
    parts.push(`<span class="novec-page-meta">Page ${page} of ${totalPages}</span>`);
    pager.innerHTML = parts.join('');
    pager.querySelectorAll('[data-page]').forEach(btn => {
      btn.addEventListener('click', () => {
        page = Math.min(totalPages, Math.max(1, Number(btn.dataset.page) || 1));
        draw();
        const grid = document.querySelector('#grid');
        if (grid) grid.scrollIntoView({behavior:'smooth', block:'start'});
      });
    });
  }

  draw = function() {
    const filtered = filteredRows();
    const total = filtered.length;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > totalPages) page = totalPages;
    if (page < 1) page = 1;
    const start = (page - 1) * PAGE_SIZE;
    const rows = filtered.slice(start, start + PAGE_SIZE);
    const first = total ? start + 1 : 0;
    const last = total ? start + rows.length : 0;

    $('#shown').textContent = total ? `${first.toLocaleString()}–${last.toLocaleString()} of ${total.toLocaleString()}` : '0 shown';
    $('#empty').hidden = rows.length > 0;
    $('#grid').innerHTML = rows.map(a => `<article class="card ${selected?.id===a.id?'sel':''}" data-id="${esc(a.id)}"><div class="icon">${esc(a.initials||'?')}</div><div><div class="name">${esc(a.name)}</div><div class="desc">${esc(a.description)}</div><div class="badges">${a.ready?'<span class="badge ready">Docker ready</span>':'<span class="badge review">Review</span>'}<span class="badge">${esc((a.tags&&a.tags[0])||'Self-hosted')}</span>${a.stars?`<span class="badge">★ ${Number(a.stars).toLocaleString()}</span>`:''}</div></div></article>`).join('');
    document.querySelectorAll('.card').forEach(c => c.onclick = () => select(c.dataset.id));
    renderPager(total, totalPages);
  };

  function resetPageAndDraw() {
    page = 1;
    draw();
  }

  function start() {
    ensurePager();
    const q = document.querySelector('#q');
    const cat = document.querySelector('#cat');
    const status = document.querySelector('#status');
    if (q) q.addEventListener('input', () => { page = 1; });
    if (cat) cat.addEventListener('change', resetPageAndDraw);
    if (status) status.addEventListener('change', resetPageAndDraw);
    setTimeout(() => { page = 1; draw(); }, 50);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
