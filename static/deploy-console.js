(() => {
  const q = (s) => document.querySelector(s);
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let modalResolve = null;

  function savedPin() {
    return sessionStorage.getItem('novecAdminPin') || '';
  }

  function savePin(value) {
    if (value) sessionStorage.setItem('novecAdminPin', value);
  }

  function clearPin() {
    sessionStorage.removeItem('novecAdminPin');
  }

  function makeInputModal() {
    if (q('#novecInputModal')) return;
    const wrap = document.createElement('div');
    wrap.id = 'novecInputModal';
    wrap.className = 'novec-input-backdrop';
    wrap.hidden = true;
    wrap.innerHTML = `
      <div class="novec-input-card">
        <div class="novec-input-head">
          <div><small>NOVEC APP STORE</small><h2 id="novecInputTitle">Deploy application</h2><p id="novecInputText"></p></div>
          <button id="novecInputClose" type="button">×</button>
        </div>
        <form id="novecInputForm">
          <div id="novecSubdomainField" class="novec-field">
            <label for="novecSubdomain">Subdomain</label>
            <div class="novec-subdomain-input"><input id="novecSubdomain" autocomplete="off" spellcheck="false"><span>.novec.online</span></div>
            <small>Only lowercase letters, numbers and hyphens.</small>
          </div>
          <div class="novec-field">
            <label for="novecPin">Admin PIN</label>
            <input id="novecPin" type="password" autocomplete="current-password" placeholder="NOVEC admin PIN">
            <small>The PIN stays only in this browser session.</small>
          </div>
          <div id="novecPurgeField" class="novec-purge" hidden>
            <label><input id="novecPurgeData" type="checkbox"><span><b>Delete persistent data too</b><small>Volumes are kept by default so the app can be restored later.</small></span></label>
          </div>
          <div id="novecInputError" class="novec-input-error" hidden></div>
          <div class="novec-input-actions"><button id="novecInputCancel" type="button" class="btn">Cancel</button><button id="novecInputSubmit" type="submit" class="btn primary">Deploy</button></div>
        </form>
      </div>`;
    document.body.appendChild(wrap);

    const finish = (value) => {
      wrap.hidden = true;
      const resolve = modalResolve;
      modalResolve = null;
      if (resolve) resolve(value);
    };
    q('#novecInputClose').onclick = () => finish(null);
    q('#novecInputCancel').onclick = () => finish(null);
    wrap.addEventListener('click', (event) => { if (event.target === wrap) finish(null); });
    q('#novecInputForm').onsubmit = (event) => {
      event.preventDefault();
      const mode = wrap.dataset.mode || 'deploy';
      const pin = q('#novecPin').value.trim();
      const error = q('#novecInputError');
      error.hidden = true;
      if (!pin) { error.textContent = 'Admin PIN is required.'; error.hidden = false; return; }
      if (mode === 'pin') { savePin(pin); finish({pin}); return; }
      if (mode === 'delete') { savePin(pin); finish({pin, purgeData:q('#novecPurgeData').checked}); return; }
      const subdomain = q('#novecSubdomain').value.trim().toLowerCase();
      if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(subdomain)) {
        error.textContent = 'Use only lowercase letters, numbers and hyphens.';
        error.hidden = false;
        return;
      }
      savePin(pin);
      finish({pin, subdomain});
    };
  }

  function openInputModal(options = {}) {
    makeInputModal();
    const wrap = q('#novecInputModal');
    const mode = options.mode || 'deploy';
    wrap.dataset.mode = mode;
    q('#novecInputTitle').textContent = options.title || (mode === 'delete' ? 'Remove deployment' : 'Deploy application');
    q('#novecInputText').textContent = options.text || '';
    q('#novecSubdomainField').hidden = mode !== 'deploy';
    q('#novecPurgeField').hidden = mode !== 'delete';
    q('#novecPurgeData').checked = false;
    q('#novecSubdomain').value = options.subdomain || '';
    q('#novecPin').value = savedPin();
    q('#novecInputError').hidden = true;
    q('#novecInputSubmit').textContent = mode === 'delete' ? 'Remove deployment' : (mode === 'pin' ? 'Unlock' : 'Deploy');
    q('#novecInputSubmit').classList.toggle('danger', mode === 'delete');
    wrap.hidden = false;
    setTimeout(() => {
      const target = mode === 'deploy' ? q('#novecSubdomain') : q('#novecPin');
      target.focus();
      if (target.select) target.select();
    }, 30);
    return new Promise((resolve) => { modalResolve = resolve; });
  }

  async function ensurePin() {
    const pin = savedPin();
    if (pin) return pin;
    const result = await openInputModal({mode:'pin', title:'Unlock NOVEC App Store', text:'Enter the admin PIN to manage deployments.'});
    return result ? result.pin : '';
  }

  function makeConsole() {
    if (q('#novecDeployConsole')) return;
    const wrap = document.createElement('div');
    wrap.id = 'novecDeployConsole';
    wrap.className = 'novec-console-backdrop';
    wrap.hidden = true;
    wrap.innerHTML = `
      <div class="novec-console-card">
        <div class="novec-console-title"><div><small id="novecConsoleEyebrow">NOVEC DEPLOY ENGINE</small><h2 id="novecConsoleTitle">Deployment</h2><p id="novecConsoleHost"></p></div><button id="novecConsoleClose">×</button></div>
        <div class="novec-console-state"><span id="novecConsoleSpinner"></span><div><b id="novecConsoleStatus">Preparing…</b><small id="novecConsoleTime">0s</small></div></div>
        <div class="novec-console-progress"><i id="novecConsoleBar"></i></div>
        <div class="novec-terminal"><div class="novec-terminal-top"><span></span><span></span><span></span><b>Live terminal output</b></div><pre id="novecConsoleLog">Waiting for job…</pre></div>
        <div class="novec-console-actions"><button id="novecConsoleOpen" class="btn primary" hidden>Open application</button><button id="novecConsoleDone" class="btn" hidden>Close</button></div>
      </div>`;
    document.body.appendChild(wrap);
    q('#novecConsoleClose').onclick = () => { wrap.hidden = true; };
    q('#novecConsoleDone').onclick = () => { wrap.hidden = true; };
  }

  function showConsole(title, host, action = 'deploy') {
    makeConsole();
    q('#novecDeployConsole').hidden = false;
    q('#novecDeployConsole').dataset.action = action;
    q('#novecConsoleEyebrow').textContent = action === 'undeploy' ? 'NOVEC REMOVE ENGINE' : 'NOVEC DEPLOY ENGINE';
    q('#novecConsoleTitle').textContent = title;
    q('#novecConsoleHost').textContent = host;
    q('#novecConsoleStatus').textContent = action === 'undeploy' ? 'Submitting removal…' : 'Submitting job…';
    q('#novecConsoleTime').textContent = '0s';
    q('#novecConsoleBar').style.width = '4%';
    q('#novecConsoleLog').textContent = action === 'undeploy' ? 'Submitting removal job…\n' : 'Submitting deployment job…\n';
    q('#novecConsoleSpinner').className = '';
    q('#novecConsoleOpen').hidden = true;
    q('#novecConsoleDone').hidden = true;
  }

  function drawJob(job, startedAt, action = 'deploy') {
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
    const labels = action === 'undeploy'
      ? {queued:'Queued…',running:'Removing…',success:'Removal complete',error:'Removal failed'}
      : {queued:'Queued…',running:'Deploying…',success:'Deployment complete',error:'Deployment failed'};
    q('#novecConsoleStatus').textContent = labels[job.status] || job.status || (action === 'undeploy' ? 'Removing…' : 'Deploying…');
    if (job.status === 'success') {
      q('#novecConsoleSpinner').className = 'ok';
      q('#novecConsoleDone').hidden = false;
      if (action === 'deploy' && job.result && job.result.url) {
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

  async function watchJob(jobId, pin, startedAt, action = 'deploy') {
    const endpoint = action === 'undeploy' ? '/api/undeploy-status/' : '/api/deploy-status/';
    while (true) {
      const response = await fetch(endpoint + encodeURIComponent(jobId), {headers:{'X-NOVEC-Admin-Pin':pin}, cache:'no-store'});
      let job = {};
      try { job = await response.json(); } catch (_) {}
      if (response.status === 401) clearPin();
      if (!response.ok) throw new Error(job.detail || ('Status failed (' + response.status + ')'));
      drawJob(job, startedAt, action);
      if (job.status === 'success' || job.status === 'error') return job;
      await delay(1500);
    }
  }

  async function deploySelected(app) {
    if (!app || !app.one_click) return;
    const suggestion = String(app.id || app.name || 'app').toLowerCase().replace(/^pt-/,'').replace(/[^a-z0-9-]+/g,'-').replace(/^-|-$/g,'').slice(0,40);
    const form = await openInputModal({mode:'deploy', title:'Deploy ' + app.name, text:'Choose the public address for this application.', subdomain:suggestion});
    if (!form) return;
    const {pin, subdomain} = form;
    showConsole('Deploying ' + app.name, subdomain + '.novec.online', 'deploy');
    const startedAt = Date.now();
    try {
      const response = await fetch('/api/deploy', {method:'POST',headers:{'Content-Type':'application/json','X-NOVEC-Admin-Pin':pin},body:JSON.stringify({app_id:app.id,subdomain})});
      let body = {};
      try { body = await response.json(); } catch (_) {}
      if (response.status === 401) clearPin();
      if (!response.ok) throw new Error(body.detail || body.error || ('Deployment failed (' + response.status + ')'));
      q('#novecConsoleLog').textContent += 'Job ID: ' + body.deployment_id + '\nTemplate: ' + (body.template_key || 'auto') + '\n';
      const job = await watchJob(body.deployment_id, pin, startedAt, 'deploy');
      if (job.status === 'error') throw new Error(job.error || 'Deployment failed');
    } catch (error) {
      const terminal = q('#novecConsoleLog');
      terminal.textContent += '\nERROR: ' + (error.message || String(error)) + '\n';
      q('#novecConsoleStatus').textContent = error.message || 'Deployment failed';
      q('#novecConsoleSpinner').className = 'bad';
      q('#novecConsoleDone').hidden = false;
    }
  }

  async function removeDeployment(item) {
    const result = await openInputModal({
      mode:'delete',
      title:'Remove ' + (item.name || item.app_id || 'deployment'),
      text:'This will stop the container and release ' + (item.host || item.url || '') + '. Persistent data is kept unless you choose otherwise.'
    });
    if (!result) return;
    showConsole('Removing ' + (item.name || item.app_id || 'deployment'), item.host || item.url || '', 'undeploy');
    const startedAt = Date.now();
    try {
      const response = await fetch('/api/undeploy', {
        method:'POST',
        headers:{'Content-Type':'application/json','X-NOVEC-Admin-Pin':result.pin},
        body:JSON.stringify({hostname:item.host,purge_data:result.purgeData})
      });
      let body = {};
      try { body = await response.json(); } catch (_) {}
      if (response.status === 401) clearPin();
      if (!response.ok) throw new Error(body.detail || body.error || ('Removal failed (' + response.status + ')'));
      q('#novecConsoleLog').textContent += 'Removal ID: ' + body.removal_id + '\n';
      const job = await watchJob(body.removal_id, result.pin, startedAt, 'undeploy');
      if (job.status === 'error') throw new Error(job.error || 'Removal failed');
      await loadDeployments();
    } catch (error) {
      const terminal = q('#novecConsoleLog');
      terminal.textContent += '\nERROR: ' + (error.message || String(error)) + '\n';
      q('#novecConsoleStatus').textContent = error.message || 'Removal failed';
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
    const actions = document.createElement('div');
    actions.className = 'novec-deployment-actions';
    const open = document.createElement('button');
    open.className = 'btn primary';
    open.textContent = 'Open';
    open.onclick = () => window.open(item.url, '_blank', 'noopener');
    const remove = document.createElement('button');
    remove.className = 'btn danger';
    remove.textContent = 'Delete';
    remove.onclick = () => removeDeployment(item);
    actions.append(open, remove);
    card.append(title, link, meta, image, actions);
    return card;
  }

  async function loadDeployments() {
    makeDeploymentsView();
    const pin = await ensurePin();
    if (!pin) return;
    const grid = q('#novecDeploymentsGrid');
    grid.textContent = 'Loading deployments…';
    const response = await fetch('/api/deployments', {headers:{'X-NOVEC-Admin-Pin':pin},cache:'no-store'});
    let body = {};
    try { body = await response.json(); } catch (_) {}
    if (response.status === 401) clearPin();
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
    makeInputModal();
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
