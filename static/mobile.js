(() => {
  const by = (s, root=document) => root.querySelector(s);
  const all = (s, root=document) => [...root.querySelectorAll(s)];
  const widthMQ = window.matchMedia('(max-width: 820px)');
  const coarseMQ = window.matchMedia('(pointer: coarse)');

  function mobileMode() {
    const touch = coarseMQ.matches || navigator.maxTouchPoints > 0 || /Android|iPhone|iPod|Mobile/i.test(navigator.userAgent || '');
    return widthMQ.matches && touch;
  }

  function ensureShell() {
    if (!by('#novecMobileHeader')) {
      const header = document.createElement('header');
      header.id = 'novecMobileHeader';
      header.className = 'novec-mobile-header';
      header.innerHTML = `<div class="novec-mobile-brand"><span class="mark">N</span><div>NOVEC<small id="novecMobileTitle">App Store</small></div></div><small id="novecMobileCount"></small>`;
      document.body.appendChild(header);
    }
    if (!by('#novecMobileDetailBackdrop')) {
      const b = document.createElement('div');
      b.id='novecMobileDetailBackdrop'; b.className='novec-mobile-detail-backdrop';
      b.onclick=closeDetail; document.body.appendChild(b);
    }
    if (!by('#novecMobileMoreBackdrop')) {
      const b=document.createElement('div'); b.id='novecMobileMoreBackdrop'; b.className='novec-mobile-more-backdrop'; b.onclick=closeMore; document.body.appendChild(b);
    }
    if (!by('#novecMobileMore')) {
      const more=document.createElement('section');
      more.id='novecMobileMore'; more.className='novec-mobile-more';
      more.innerHTML=`<h3>More tools</h3><div class="novec-mobile-more-grid">
        <button data-nav="Domains">◎ Domains</button>
        <button data-nav="Volumes">▤ Volumes</button>
        <button data-nav="Catalog Sync">⟳ Catalog Sync</button>
        <button data-nav="Settings">⚙ Settings</button>
      </div>`;
      more.addEventListener('click',e=>{const b=e.target.closest('[data-nav]');if(!b)return;closeMore();navigate(b.dataset.nav);});
      document.body.appendChild(more);
    }
    if (!by('#novecMobileNav')) {
      const nav=document.createElement('nav'); nav.id='novecMobileNav'; nav.className='novec-mobile-nav';
      nav.innerHTML=`
        <button data-nav="App Store" class="active"><i>▣</i><span>Store</span></button>
        <button data-nav="Deployments"><i>▦</i><span>Deploy</span></button>
        <button data-nav="Monitoring"><i>⌁</i><span>Monitor</span></button>
        <button data-nav="Backups"><i>▧</i><span>Backups</span></button>
        <button data-more><i>•••</i><span>More</span></button>`;
      nav.addEventListener('click',e=>{
        const more=e.target.closest('[data-more]'); if(more){openMore();return;}
        const b=e.target.closest('[data-nav]'); if(!b)return; navigate(b.dataset.nav);
      });
      document.body.appendChild(nav);
    }
  }

  function setTitle(title) {
    const t=by('#novecMobileTitle'); if(t)t.textContent=title || 'App Store';
    const nav=by('#novecMobileNav'); if(!nav)return;
    const map={Store:'App Store',Deploy:'Deployments',Monitor:'Monitoring',Backups:'Backups'};
    all('button',nav).forEach(b=>b.classList.remove('active'));
    const expected = Object.entries(map).find(([_,v])=>v===title)?.[0];
    if(expected){const b=all('button',nav).find(x=>x.textContent.includes(expected)); if(b)b.classList.add('active');}
  }

  function baseNav(label) {
    return all('.nav a').find(a => (a.textContent || '').toLowerCase().includes(label.toLowerCase()));
  }

  function showStoreFallback() {
    const admin=by('#novecAdminPage'); if(admin)admin.hidden=true;
    const deps=by('#novecDeploymentsView'); if(deps)deps.hidden=true;
  }

  function navigate(label) {
    closeMore(); closeDetail();
    if(label==='App Store') showStoreFallback();
    const a=baseNav(label); if(a) a.click();
    setTimeout(()=>syncSectionTitle(label),30);
    window.scrollTo({top:0,behavior:'smooth'});
  }

  function syncSectionTitle(fallback='App Store') {
    const admin=by('#novecAdminPage');
    if(admin && !admin.hidden){setTitle(by('h1',admin)?.textContent?.trim() || fallback); annotateTables(admin); return;}
    const dep=by('#novecDeploymentsView');
    if(dep && !dep.hidden){setTitle('Deployments'); return;}
    setTitle('App Store');
    const count=by('#novecMobileCount');
    const total=by('#total'); if(count&&total) count.textContent=(total.textContent||'').trim() ? `${total.textContent.trim()} apps` : '';
  }

  function openMore(){document.body.classList.add('novec-more-open');closeDetail();}
  function closeMore(){document.body.classList.remove('novec-more-open');}
  function openDetail(){if(!document.body.classList.contains('novec-mobile'))return;document.body.classList.add('novec-detail-open');}
  function closeDetail(){document.body.classList.remove('novec-detail-open');}

  function annotateTables(root=document) {
    all('.novec-table',root).forEach(table=>{
      const labels=all('thead th',table).map(th=>(th.textContent||'').trim());
      all('tbody tr',table).forEach(tr=>all('td',tr).forEach((td,i)=>{if(!td.hasAttribute('colspan'))td.dataset.label=labels[i]||'';}));
    });
  }

  function applyMode() {
    const on=mobileMode();
    document.body.classList.toggle('novec-mobile',on);
    if(on){ensureShell();annotateTables();syncSectionTitle();}
    else{document.body.classList.remove('novec-detail-open','novec-more-open');}
  }

  document.addEventListener('click',e=>{
    if(!document.body.classList.contains('novec-mobile'))return;
    if(e.target.closest('.card')) setTimeout(openDetail,0);
    if(e.target.closest('.top input,.top select')) closeDetail();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeDetail();closeMore();}});

  const observer=new MutationObserver(()=>{
    if(!document.body.classList.contains('novec-mobile'))return;
    annotateTables();
    syncSectionTitle();
  });
  observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class']});

  const refresh=()=>applyMode();
  widthMQ.addEventListener?.('change',refresh); coarseMQ.addEventListener?.('change',refresh);
  window.addEventListener('resize',()=>{clearTimeout(window.__novecMobileResize);window.__novecMobileResize=setTimeout(refresh,120);});
  applyMode();
})();
