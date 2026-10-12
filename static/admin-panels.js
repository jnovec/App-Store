(() => {
  const q = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  let currentSection = '';
  let snapshotCache = null;
  let monitorTimer = null;

  function pin() { return sessionStorage.getItem('novecAdminPin') || ''; }
  function savePin(value) { if (value) sessionStorage.setItem('novecAdminPin', value); }
  function clearPin() { sessionStorage.removeItem('novecAdminPin'); }
  function fmtBytes(n) { n = Number(n || 0); if (!n) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++;} return (n>=10||i===0?n.toFixed(0):n.toFixed(1))+' '+u[i]; }
  function fmtTime(ts) { if (!ts) return '—'; const d=new Date(Number(ts)*1000); return d.toLocaleString(); }
  function statusPill(ok, text, warn=false) { return `<span class="novec-pill ${ok?'ok':warn?'warn':'bad'}">${esc(text)}</span>`; }

  function ensureAuthModal() {
    if (q('#novecAdminAuth')) return;
    const wrap=document.createElement('div');
    wrap.id='novecAdminAuth';wrap.className='novec-input-backdrop';wrap.hidden=true;
    wrap.innerHTML=`<div class="novec-input-card"><div class="novec-input-head"><div><small>NOVEC ADMIN</small><h2>Unlock management</h2><p>Enter the admin PIN to manage infrastructure.</p></div><button type="button" data-close>×</button></div><form><div class="novec-field"><label>Admin PIN</label><input type="password" autocomplete="current-password" placeholder="NOVEC admin PIN"><div class="novec-input-error" hidden></div></div><div class="novec-input-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">Unlock</button></div></form></div>`;
    document.body.appendChild(wrap);
  }

  function askPin() {
    if (pin()) return Promise.resolve(pin());
    ensureAuthModal();
    const wrap=q('#novecAdminAuth'), input=wrap.querySelector('input'), err=wrap.querySelector('.novec-input-error');
    wrap.hidden=false; input.value=''; err.hidden=true; setTimeout(()=>input.focus(),20);
    return new Promise((resolve)=>{
      const finish=(value)=>{wrap.hidden=true;wrap.querySelector('form').onsubmit=null;wrap.querySelectorAll('[data-close]').forEach(b=>b.onclick=null);resolve(value);};
      wrap.querySelector('form').onsubmit=(e)=>{e.preventDefault();const value=input.value.trim();if(!value){err.textContent='PIN is required.';err.hidden=false;return;}savePin(value);finish(value);};
      wrap.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>finish(''));
    });
  }

  function ensureConfirm() {
    if(q('#novecAdminConfirm')) return;
    const wrap=document.createElement('div');wrap.id='novecAdminConfirm';wrap.className='novec-input-backdrop';wrap.hidden=true;
    wrap.innerHTML=`<div class="novec-input-card"><div class="novec-input-head"><div><small>NOVEC ADMIN</small><h2></h2><p></p></div><button type="button" data-no>×</button></div><div class="novec-input-actions"><button class="btn" data-no>Cancel</button><button class="btn danger" data-yes>Continue</button></div></div>`;
    document.body.appendChild(wrap);
  }
  function confirmAction(title,text,label='Continue'){
    ensureConfirm();const wrap=q('#novecAdminConfirm');wrap.querySelector('h2').textContent=title;wrap.querySelector('p').textContent=text;wrap.querySelector('[data-yes]').textContent=label;wrap.hidden=false;
    return new Promise(resolve=>{const done=v=>{wrap.hidden=true;resolve(v)};wrap.querySelectorAll('[data-no]').forEach(b=>b.onclick=()=>done(false));wrap.querySelector('[data-yes]').onclick=()=>done(true);});
  }

  async function api(url, options={}) {
    const p = await askPin(); if (!p) throw new Error('Admin PIN required');
    options.headers = {...(options.headers||{}), 'X-NOVEC-Admin-Pin':p};
    const r=await fetch(url,{...options,cache:'no-store'});let body={};try{body=await r.json();}catch(_){}
    if(r.status===401){clearPin();throw new Error('Invalid admin PIN');}
    if(!r.ok) throw new Error(body.detail||body.error||('Request failed ('+r.status+')'));
    return body;
  }

  function makePage(){
    if(q('#novecAdminPage')) return;
    const el=document.createElement('div');el.id='novecAdminPage';el.className='novec-admin-page';el.hidden=true;document.body.appendChild(el);
  }
  function hideAdmin(){makePage();q('#novecAdminPage').hidden=true;currentSection='';if(monitorTimer){clearInterval(monitorTimer);monitorTimer=null;}}
  function showShell(title,subtitle,actions=''){
    makePage();const page=q('#novecAdminPage');page.hidden=false;page.innerHTML=`<div class="novec-admin-head"><div><small>NOVEC CONTROL CENTER</small><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="novec-admin-actions">${actions}</div></div><div id="novecAdminBody" class="novec-admin-loading">Loading…</div>`;
    const dep=q('#novecDeploymentsView');if(dep)dep.hidden=true;
    return q('#novecAdminBody');
  }

  async function snapshot(force=false){if(snapshotCache&&!force)return snapshotCache;snapshotCache=await api('/api/admin/snapshot');return snapshotCache;}
  function invalidate(){snapshotCache=null;}

  async function domains(){
    currentSection='domains';const body=showShell('Domains','Public hostnames routed through your NOVEC infrastructure.','<button class="btn primary" id="admRefresh">Refresh</button>');
    try{const d=await snapshot(true);const rows=d.domains||[];body.className='';body.innerHTML=`<div class="novec-admin-stats"><div class="novec-admin-stat"><b>${rows.length}</b><small>deployment domains</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.dns_ok).length}</b><small>DNS resolving</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.http_ok).length}</b><small>HTTP reachable</small></div><div class="novec-admin-stat"><b>Cloudflare</b><small>tunnel routing</small></div></div><div class="novec-table-wrap"><table class="novec-table"><thead><tr><th>Hostname</th><th>App</th><th>DNS</th><th>HTTP</th><th>Local port</th></tr></thead><tbody>${rows.map(x=>`<tr><td><a target="_blank" rel="noopener" href="${esc(x.url)}">${esc(x.hostname)}</a></td><td>${esc(x.name||x.app_id)}</td><td>${statusPill(x.dns_ok,x.dns_ok?'Resolved':'No DNS')}</td><td>${statusPill(x.http_ok,x.http_status?('HTTP '+x.http_status):'Unreachable')}</td><td>${esc(x.port||'—')}</td></tr>`).join('')||'<tr><td colspan="5">No deployment domains.</td></tr>'}</tbody></table></div>`;}catch(e){body.className='novec-admin-empty';body.textContent=e.message;}
    q('#admRefresh').onclick=domains;
  }

  async function volumes(){
    currentSection='volumes';const body=showShell('Volumes','Persistent Docker storage used by your deployed applications.','<button class="btn primary" id="admRefresh">Refresh</button>');
    try{const d=await snapshot(true);const rows=d.volumes||[];body.className='';body.innerHTML=`<div class="novec-admin-stats"><div class="novec-admin-stat"><b>${rows.length}</b><small>Docker volumes</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>!x.orphan).length}</b><small>attached</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.orphan).length}</b><small>orphan volumes</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.size).length}</b><small>size reported by Docker</small></div></div><div class="novec-table-wrap"><table class="novec-table"><thead><tr><th>Volume</th><th>Attached to</th><th>Driver</th><th>State</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td><code>${esc(x.name)}</code></td><td>${esc((x.attached_to||[]).join(', ')||'—')}</td><td>${esc(x.driver)}</td><td>${x.orphan?statusPill(false,'Orphan',true):statusPill(true,'In use')}</td><td>${x.orphan?`<button class="btn danger adm-vol-delete" data-name="${esc(x.name)}">Delete</button>`:''}</td></tr>`).join('')||'<tr><td colspan="5">No volumes.</td></tr>'}</tbody></table></div>`;document.querySelectorAll('.adm-vol-delete').forEach(b=>b.onclick=async()=>{if(!await confirmAction('Delete orphan volume?',b.dataset.name+' will be permanently removed.','Delete volume'))return;try{await api('/api/admin/delete-volume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:b.dataset.name})});invalidate();await volumes();}catch(e){alert(e.message);}});}catch(e){body.className='novec-admin-empty';body.textContent=e.message;}
    q('#admRefresh').onclick=volumes;
  }

  function showJobConsole(title, host, jobId){
    const wrap=q('#novecDeployConsole');if(!wrap)return;wrap.hidden=false;q('#novecConsoleEyebrow').textContent='NOVEC BACKUP ENGINE';q('#novecConsoleTitle').textContent=title;q('#novecConsoleHost').textContent=host;q('#novecConsoleStatus').textContent='Backup queued…';q('#novecConsoleTime').textContent='0s';q('#novecConsoleBar').style.width='5%';q('#novecConsoleLog').textContent='Backup queued.\nJob ID: '+jobId+'\n';q('#novecConsoleSpinner').className='';q('#novecConsoleOpen').hidden=true;q('#novecConsoleDone').hidden=true;
    const start=Date.now();
    (async()=>{while(true){try{const job=await api('/api/admin/job/'+encodeURIComponent(jobId));const lines=job.log||[];q('#novecConsoleLog').textContent=lines.join('\n')+'\n';q('#novecConsoleLog').scrollTop=q('#novecConsoleLog').scrollHeight;q('#novecConsoleTime').textContent=Math.round((Date.now()-start)/1000)+'s';q('#novecConsoleStatus').textContent=job.status==='success'?'Backup complete':job.status==='error'?'Backup failed':job.status==='running'?'Backing up…':'Queued…';q('#novecConsoleBar').style.width=job.status==='success'?'100%':job.status==='running'?'65%':'12%';if(job.status==='success'||job.status==='error'){q('#novecConsoleSpinner').className=job.status==='success'?'ok':'bad';q('#novecConsoleDone').hidden=false;invalidate();return;}}catch(e){q('#novecConsoleLog').textContent+='\n'+e.message+'\n';}await new Promise(r=>setTimeout(r,1500));}})();
  }

  async function backups(){
    currentSection='backups';const body=showShell('Backups','Create and review volume backups for deployed applications.','<button class="btn primary" id="admRefresh">Refresh</button>');
    try{const d=await snapshot(true);const deps=d.domains||[], rows=d.backups||[];body.className='';body.innerHTML=`<div class="novec-admin-stats"><div class="novec-admin-stat"><b>${rows.length}</b><small>backup sets</small></div><div class="novec-admin-stat"><b>${fmtBytes(rows.reduce((a,x)=>a+Number(x.bytes||0),0))}</b><small>stored archives</small></div><div class="novec-admin-stat"><b>${deps.length}</b><small>apps available</small></div><div class="novec-admin-stat"><b>${rows[0]?fmtTime(rows[0].created_at):'—'}</b><small>latest backup</small></div></div><div class="novec-admin-grid">${deps.map(x=>`<article class="novec-admin-card"><h3>${esc(x.name||x.app_id)}</h3><p>${esc(x.hostname)}</p><code>${esc(x.container)}</code><div class="actions"><button class="btn primary adm-backup" data-host="${esc(x.hostname)}">Create backup</button></div></article>`).join('')||'<div class="novec-admin-empty">No deployments to back up.</div>'}</div><div class="head"><h2>Backup history</h2></div><div class="novec-table-wrap"><table class="novec-table"><thead><tr><th>Created</th><th>Hostname</th><th>Volumes</th><th>Size</th><th>Status</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(fmtTime(x.created_at))}</td><td>${esc(x.hostname)}</td><td>${esc(x.volume_count||0)}</td><td>${esc(fmtBytes(x.bytes))}</td><td>${statusPill(x.status==='success',x.status||'unknown')}</td></tr>`).join('')||'<tr><td colspan="5">No backups yet.</td></tr>'}</tbody></table></div>`;document.querySelectorAll('.adm-backup').forEach(b=>b.onclick=async()=>{try{const r=await api('/api/admin/backup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hostname:b.dataset.host})});showJobConsole('Backing up '+b.dataset.host,b.dataset.host,r.job_id);}catch(e){alert(e.message);}});}catch(e){body.className='novec-admin-empty';body.textContent=e.message;}
    q('#admRefresh').onclick=backups;
  }

  async function monitoring(){
    currentSection='monitoring';const body=showShell('Monitoring','Live container health and public HTTP availability.','<button class="btn primary" id="admRefresh">Refresh</button>');
    try{const d=await snapshot(true);const rows=d.monitoring||[];body.className='';body.innerHTML=`<div class="novec-admin-stats"><div class="novec-admin-stat"><b>${rows.length}</b><small>monitored apps</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.running).length}</b><small>containers running</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.http_ok).length}</b><small>public endpoints reachable</small></div><div class="novec-admin-stat"><b>${rows.filter(x=>x.health==='healthy').length}</b><small>Docker healthy</small></div></div><div class="novec-table-wrap"><table class="novec-table"><thead><tr><th>App</th><th>Container</th><th>Docker</th><th>Health</th><th>HTTP</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td><b>${esc(x.name||x.app_id)}</b><br><a href="${esc(x.url)}" target="_blank">${esc(x.hostname)}</a></td><td><code>${esc(x.container)}</code></td><td>${statusPill(x.running,x.status||'unknown')}</td><td>${statusPill(x.health==='healthy'||x.health==='none',x.health||'none',x.health==='none')}</td><td>${statusPill(x.http_ok,x.http_status?('HTTP '+x.http_status):'offline')}</td><td><button class="btn adm-restart" data-host="${esc(x.hostname)}">Restart</button></td></tr>`).join('')||'<tr><td colspan="6">No deployed apps.</td></tr>'}</tbody></table></div>`;document.querySelectorAll('.adm-restart').forEach(b=>b.onclick=async()=>{if(!await confirmAction('Restart application?',b.dataset.host+' will be restarted.','Restart'))return;try{await api('/api/admin/restart',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hostname:b.dataset.host})});invalidate();setTimeout(monitoring,1200);}catch(e){alert(e.message);}});}catch(e){body.className='novec-admin-empty';body.textContent=e.message;}
    q('#admRefresh').onclick=monitoring;if(monitorTimer)clearInterval(monitorTimer);monitorTimer=setInterval(()=>{if(currentSection==='monitoring')monitoring();},30000);
  }

  async function catalog(){
    currentSection='catalog';const body=showShell('Catalog Sync','Sources feeding the NOVEC App Store catalog.','<button class="btn primary" id="admSync">Sync all sources</button>');
    try{const d=await api('/api/admin/catalog');body.className='';body.innerHTML=`<div class="novec-admin-stats"><div class="novec-admin-stat"><b>${Number(d.total_apps||0).toLocaleString()}</b><small>total apps</small></div><div class="novec-admin-stat"><b>${Number(d.awesome_selfhosted||0).toLocaleString()}</b><small>Awesome Selfhosted</small></div><div class="novec-admin-stat"><b>${Number(d.one_click||0).toLocaleString()}</b><small>one-click apps</small></div><div class="novec-admin-stat"><b>${Number(d.safe_templates||0).toLocaleString()}</b><small>safe templates</small></div></div><div class="novec-source-list">${(d.sources||[]).map(s=>`<div class="novec-source"><div><strong>${esc(s.name)}</strong><small>${esc(s.type)}</small></div>${statusPill(s.status==='connected',s.status)}</div>`).join('')}</div><div class="novec-admin-card" style="margin-top:14px"><div class="row"><span class="label">Last Awesome Selfhosted sync</span><b>${esc(fmtTime(d.synced_at))}</b></div><div class="row"><span class="label">Portainer template cache</span><b>${esc(fmtTime(d.portainer_cache_updated))}</b></div><div class="row"><span class="label">Cached icons</span><b>${Number(d.cached_icons||0).toLocaleString()}</b></div></div>`;}catch(e){body.className='novec-admin-empty';body.textContent=e.message;}
    q('#admSync').onclick=async()=>{const b=q('#admSync');b.disabled=true;b.textContent='Syncing…';try{await api('/api/admin/catalog-sync',{method:'POST'});invalidate();await catalog();}catch(e){alert(e.message);}finally{if(q('#admSync')){q('#admSync').disabled=false;q('#admSync').textContent='Sync all sources';}}};
  }

  async function settings(){
    currentSection='settings';const body=showShell('Settings','NOVEC App Store system configuration and security.','<button class="btn primary" id="admRefresh">Refresh</button>');
    try{const d=await snapshot(true),s=d.system||{};const diskPct=s.disk_total?Math.round((s.disk_used/s.disk_total)*100):0;body.className='';body.innerHTML=`<div class="novec-settings-grid"><section class="novec-setting"><h3>System</h3><div class="row"><span class="label">Docker</span><b>${s.docker_ok?'Online':'Unavailable'} ${esc(s.docker_version||'')}</b></div><div class="row"><span class="label">Deployments</span><b>${esc(s.deployments||0)}</b></div><p>Mac storage</p><div class="novec-progress"><i style="width:${diskPct}%"></i></div><small>${fmtBytes(s.disk_used)} used of ${fmtBytes(s.disk_total)} · ${fmtBytes(s.disk_free)} free</small></section><section class="novec-setting"><h3>Admin security</h3><p>Rotate the management PIN. The new PIN is shown once and replaces the current one immediately.</p><button class="btn danger" id="admRotatePin">Rotate admin PIN</button><div id="admNewPin" class="novec-inline-pin" hidden><span>New PIN</span><code></code></div></section><section class="novec-setting"><h3>Agents</h3><p>Deploy and undeploy agents run locally on the Mac and are not exposed as public services.</p><div class="row"><span class="label">Deploy agent</span>${statusPill(true,'Connected')}</div><div class="row"><span class="label">Management API</span>${statusPill(true,'Connected')}</div></section><section class="novec-setting"><h3>App Store</h3><p>Catalog, deployment management, backups, storage and monitoring are managed from this control center.</p><div class="row"><span class="label">Public URL</span><b>store.novec.online</b></div><div class="row"><span class="label">Catalog apps</span><b>${q('#health')?esc(q('#health').textContent):'—'}</b></div></section></div>`;q('#admRotatePin').onclick=async()=>{if(!await confirmAction('Rotate admin PIN?','The old PIN will stop working immediately.','Rotate PIN'))return;try{const r=await api('/api/admin/rotate-pin',{method:'POST'});savePin(r.pin);q('#admNewPin').hidden=false;q('#admNewPin code').textContent=r.pin;}catch(e){alert(e.message);}};}catch(e){body.className='novec-admin-empty';body.textContent=e.message;}
    q('#admRefresh').onclick=settings;
  }

  const pages={Domains:domains,Volumes:volumes,Backups:backups,Monitoring:monitoring,'Catalog Sync':catalog,Settings:settings};
  function bindNav(){
    document.querySelectorAll('.nav a').forEach(a=>{
      const text=(a.textContent||'').trim();
      Object.entries(pages).forEach(([name,fn])=>{if(text.includes(name)){a.style.cursor='pointer';a.onclick=()=>{document.querySelectorAll('.nav a').forEach(x=>x.classList.remove('active'));a.classList.add('active');fn();};}});
      if(text.includes('App Store')||text.includes('Deployments'))a.addEventListener('click',hideAdmin);
    });
  }
  function start(){makePage();bindNav();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();