(() => {
  const ONE_CLICK = new Set(['uptime-kuma','it-tools','stirling-pdf','mealie','nocodb','gitea','vaultwarden','open-webui','metabase']);
  const $ = (s) => document.querySelector(s);

  function pin() {
    let p = sessionStorage.getItem('novecAdminPin') || '';
    if (!p) {
      p = prompt('Admin PIN pro NOVEC App Store:') || '';
      if (p) sessionStorage.setItem('novecAdminPin', p.trim());
    }
    return p.trim();
  }

  async function deploy(app) {
    const sub = (prompt('Subdoména pro aplikaci:', app.id) || '').trim().toLowerCase();
    if (!sub) return;
    const adminPin = pin();
    if (!adminPin) return;

    const button = document.querySelector('#detail .deploy-live-btn');
    if (button) {
      button.disabled = true;
      button.textContent = 'Deploying…';
    }

    try {
      const r = await fetch('/api/deploy', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-NOVEC-Admin-Pin': adminPin
        },
        body: JSON.stringify({ app_id: app.id, subdomain: sub })
      });
      let data = {};
      try { data = await r.json(); } catch (_) {}
      if (r.status === 401) {
        sessionStorage.removeItem('novecAdminPin');
        throw new Error('Neplatný admin PIN. Zkus Deploy znovu.');
      }
      if (!r.ok) {
        throw new Error(data.detail || data.error || `Deployment failed (${r.status})`);
      }
      if (button) button.textContent = 'Deployed ✓';
      if (confirm(`Hotovo. ${app.name} běží na:\n${data.url}\n\nOtevřít teď?`)) {
        window.open(data.url, '_blank', 'noopener');
      }
    } catch (e) {
      alert(e.message || String(e));
      if (button) {
        button.disabled = false;
        button.textContent = 'Deploy';
      }
    }
  }

  function enhanceDetail() {
    if (typeof selected === 'undefined' || !selected) return;
    const detail = $('#detail');
    if (!detail) return;
    const original = detail.querySelector('button.btn.primary');
    if (!original) return;
    if (original.classList.contains('deploy-live-btn')) return;

    const clone = original.cloneNode(true);
    original.replaceWith(clone);
    clone.classList.add('deploy-live-btn');
    clone.removeAttribute('onclick');

    if (ONE_CLICK.has(selected.id)) {
      clone.textContent = 'Deploy';
      clone.disabled = false;
      clone.onclick = () => deploy(selected);
      const badgeBox = detail.querySelector('.badges');
      if (badgeBox && !badgeBox.querySelector('.one-click-badge')) {
        const b = document.createElement('span');
        b.className = 'badge ready one-click-badge';
        b.textContent = 'One-click ready';
        badgeBox.appendChild(b);
      }
    } else {
      clone.textContent = 'Needs review';
      clone.disabled = true;
      clone.title = 'Pro tuto aplikaci ještě není ověřená one-click šablona.';
    }
  }

  const observer = new MutationObserver(() => requestAnimationFrame(enhanceDetail));
  const start = () => {
    const detail = $('#detail');
    if (detail) observer.observe(detail, { childList: true, subtree: true });
    enhanceDetail();
    setTimeout(enhanceDetail, 500);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
