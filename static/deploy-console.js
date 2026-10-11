(() => {
  const q = (s) => document.querySelector(s);
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function adminPin() {
    let value = sessionStorage.getItem('novecAdminPin') || '';
    if (!value) {
      value = (prompt('Admin PIN pro NOVEC App Store:') || '').trim();
      if (value) sessionStorage.setItem('novecAdminPin', value);
    }
    return value;
  }

  function makeConsole() {
    if (q('#novecDeployConsole')) return;
    const wrap = document.createElement('div');
    wrap.id = 'novecDeployConsole';
    wrap.className = 'novec-console-backdrop';
    wrap.hidden = true;
    wrap.innerHTML = `
      <div class="novec-console-card">
        <div class="novec-console-title"><div><small>NOVEC DEPLOY ENGINE</small><h2 id="novecConsoleTitle">Deployment</h2><p id="novecConsoleHost"></p></div><button id="novecConsoleClose">×</button></div>
        <div class="novec-console-state"><span id="novecConsoleSpinner"></span><div><b id="novecConsoleStatus">Preparing…</b><small id="novecConsoleTime">0s</small></div></div>
        <div class="novec-console-progress"><i id="novecConsoleBar"></i></div>
        <div class="novec-terminal"><div class="novec-terminal-top"><span></span><span></span><span></span><b>Live terminal output</b></div><pre id="novecConsoleLog">Waiting for deployment job…</pre></div>
        <div class="novec-console-actions"><button id="novecConsoleOpen" class="btn primary" hidden>Open application</button><button id="novecConsoleDone" class="btn" hidden>Close</button></div>
      </div>`;
    document.body.appendChild(wrap);
    q('#novecConsoleClose').onclick = () => { wrap.hidden = true; };
    q('#novecConsoleDone').onclick = () => { wrap.hidden = true; };
  }

  function showConsole(app, subdomain) {
    makeConsole();
    q('#novecDeployConsole').hidden = false;
    q('#novecConsoleTitle').textContent = 'Deploying ' + app.name;
    q('#novecConsoleHost').textContent = subdomain + '.novec.online';
    q('#novecConsoleStatus').textContent = 'Submitting job…';
    q('#novecConsoleTime').textContent = '0s';
    q('#novecConsoleBar').style.width = '4%';
    q('#novecConsoleLog').textContent = 'Submitting deployment job…\n';
    q('#novecConsoleSpinner').className = '';
    q('#novecConsoleOpen').hidden = true;
    q('#novecConsoleDone').hidden = true;
  }

  function drawJob(job, startedAt) {
    const log = Array.isArray(job.log) ? job.log : [];
    const terminal = q('#novecConsoleLog');
    terminal.textContent = log.join('\n') + (log.length ? '\n' : '');
    terminal.scrollTop = terminal.scrollHeight;
    q('#novecConsoleTime').textContent = Math.max(0, Math.round((Date.now() - startedAt) / 1000)) + 's';
    let progress = 8;
    log.forEach((line) => {
      const match = String(line).match(/\[(\d+)\/(\d+)\]/);
      if (match) progress = Math.max(progress, Math.round((Number(match[1]) / Number(match[2])) * 92));
    });
    if (job.status === 'success') progress = 100;
    q('#novecConsoleBar').style.width = progress + '%';
    const labels = {queued:'Queued…',running:'Deploying…',success:'Deployment complete',error:'Deployment failed'};
    q('#novecConsoleStatus').textContent = labels[job.status] || job.status || 'Deploying…';
    if (job.status === 'success') {
      q('#novecConsoleSpinner').className = 'ok';
      q('#novecConsoleDone').hidden = false;
      if (job.result && job.result.url) {
        const open = q('#novecConsoleOpen');
        open.hidden = false;
        open.onclick = () => window.open(job.result.url, '_blank', 'noopener');
      }
    }
    if (job.status === 'error') {
      q('#novecConsoleSpinner').className = 'bad';
      q('#novecConsoleDone').hidden = false;
    }
  }

  async function watchJob(jobId, pin, startedAt) {
    while (true) {
      const response = await fetch('/api/deploy-status/' + encodeURIComponent(jobId), {headers:{'X-NOVEC-Admin-Pin':pin}, cache:'no-store'});
      let job = {};
      try { job = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error(job.detail || ('Status failed (' + response.status + ')'));
      drawJob(job, startedAt);
      if (job.status === 'success' || job.status === 'error') return job;
      await delay(1500);
    }
  }

  async function deploySelected(app) {
    if (!app || !app.one_click) return;
    const suggestion = String(app.id || app.name || 'app').toLowerCase().replace(/[^a-z0-9-]+/g,'-').replace(/^-|-$/g,'').slice(0,40);
    const subdomain = (prompt('Subdoména pro aplikaci:', suggestion) || '').trim().toLowerCase();
    if (!subdomain) return;
    const pin = adminPin();
    if (!pin) return;
    showConsole(app, subdomain);
    const startedAt = Date.now();
    try {
      const response = await fetch('/api/deploy', {method:'POST',headers:{'Content-Type':'application/json','X-NOVEC-Admin-Pin':pin},body:JSON.stringify({app_id:app.id,subdomain})});
      let body = {};
      try { body = await response.json(); } catch (_) {}
      if (response.status === 401) sessionStorage.removeItem('novecAdminPin');
      if (!response.ok) throw new Error(body.detail || body.error || ('Deployment failed (' + response.status + ')'));
      q('#novecConsoleLog').textContent += 'Job ID: ' + body.deployment_id + '\nTemplate: ' + (body.template_key || 'auto') + '\n';
      const job = await watchJob(body.deployment_id, pin, startedAt);
      if (job.status === 'error') throw new Error(job.error || 'Deployment failed');
    } catch (error) {
      const terminal = q('#novecConsoleLog');
      terminal.textContent += '\nERROR: ' + (error.message || String(error)) + '\n';
      q('#novecConsoleStatus').textContent = error.message || 'Deployment failed';
      q('#novecConsoleSpinner').className = 'bad';
      q('#novecConsoleDone').hidden = false;
    }
  }

  function fixDeployButton() {
    if (typeof selected === 'undefined' || !selected) return;
    const button = q('#detail button.btn.primary');
    if (!button) return;
    button.classList.add('deploy-live-btn');
    button.removeAttribute('onclick');
    if (selected.one_click) {
      button.disabled = false;
      button.textContent = 'Deploy';
      button.onclick = () => deploySelected(selected);
      const badges = q('#detail .badges');
      if (badges && !badges.querySelector('.one-click-badge')) {
        const badge = document.createElement('span');
        badge.className = 'badge ready one-click-badge';
        badge.textContent = 'One-click ready';
        badges.appendChild(badge);
      }
    } else {
      button.disabled = true;
      button.textContent = 'Needs review';
    }
  }

  function addCardBadges() {
    if (typeof all === 'undefined') return;
    document.querySelectorAll('.card').forEach((card) => {
      const app = all.find((item) => item.id === card.dataset.id);
      const badges = card.querySelector('.badges');
      if (app && app.one_click && badges && !badges.querySelector('.one-click-badge')) {
        const badge = document.createElement('span');
        badge.className = 'badge ready one-click-badge';
        badge.textContent = 'One-click';
        badges.prepend(badge);
      }
    });
  }

  function makeDeploymentsView() {
    if (q('#novecDeploymentsView')) return;
    const view = document.createElement('div');
    view.id = 'novecDeploymentsView';
    view.hidden = true;
    view.innerHTML = `<div class="novec-deployments-page"><div class="novec-deployments-head"><div><small>NOVEC APP STORE</small><h1>Deployments</h1><p>Apps currently published through your NOVEC infrastructure.</p></div><button id="novecDeploymentsRefresh" class="btn primary">Refresh</button></div><div id="novecDeploymentsSummary" class="novec-deployments-summary"></div><div id="novecDeploymentsGrid" class="novec-deployments-grid"></div></div>`;
    document.body.appendChild(view);
    q('#novecDeploymentsRefresh').onclick = loadDeployments;
  }

  function deploymentCard(item) {
    const card = document.createElement('article');
    card.className = 'novec-deployment-card';
    const title = document.createElement('h3');
    title.textContent = item.name || item.app_id || 'App';
    const link = document.createElement('a');
    link.href = item.url || '#';
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = item.url || item.host || '';
    const meta = document.createElement('p');
    meta.textContent = (item.status || 'running') + ' • Port ' + (item.port || '—');
    const image = document.createElement('code');
    image.textContent = item.image || '';
    const open = document.createElement('button');
    open.className = 'btn primary';
    open.textContent = 'Open';
    open.onclick = () => window.open(item.url, '_blank', 'noopener');
    card.append(title, link, meta, image, open);
    return card;
  }

  async function loadDeployments() {
    makeDeploymentsView();
    const pin = adminPin();
    if (!pin) return;
    const grid = q('#novecDeploymentsGrid');
    grid.textContent = 'Loading deployments…';
    const response = await fetch('/api/deployments', {headers:{'X-NOVEC-Admin-Pin':pin},cache:'no-store'});
    let body = {};
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) sessionStorage.removeItem('novecAdminPin');
    if (!response.ok) { grid.textContent = body.detail || ('Failed (' + response.status + ')'); return; }
    const rows = Array.isArray(body.deployments) ? body.deployments : [];
    q('#novecDeploymentsSummary').textContent = rows.length + ' deployed apps';
    grid.innerHTML = '';
    if (!rows.length) { grid.textContent = 'No deployments yet.'; return; }
    rows.forEach((item) => grid.appendChild(deploymentCard(item)));
  }

  function bindNav() {
    makeDeploymentsView();
    document.querySelectorAll('.nav a').forEach((anchor) => {
      if ((anchor.textContent || '').includes('Deployments')) {
        anchor.style.cursor = 'pointer';
        anchor.onclick = () => {
          document.querySelectorAll('.nav a').forEach((a) => a.classList.remove('active'));
          anchor.classList.add('active');
          q('#novecDeploymentsView').hidden = false;
          loadDeployments();
        };
      }
      if ((anchor.textContent || '').includes('App Store')) {
        anchor.style.cursor = 'pointer';
        anchor.onclick = () => {
          document.querySelectorAll('.nav a').forEach((a) => a.classList.remove('active'));
          anchor.classList.add('active');
          q('#novecDeploymentsView').hidden = true;
        };
      }
    });
  }

  function refreshEnhancements() {
    fixDeployButton();
    addCardBadges();
  }

  function start() {
    makeConsole();
    makeDeploymentsView();
    bindNav();
    const observer = new MutationObserver(() => requestAnimationFrame(refreshEnhancements));
    if (q('#detail')) observer.observe(q('#detail'), {childList:true,subtree:true});
    if (q('#grid')) observer.observe(q('#grid'), {childList:true,subtree:true});
    refreshEnhancements();
    setTimeout(refreshEnhancements, 500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
