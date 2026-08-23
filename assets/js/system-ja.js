(() => {
  'use strict';

  const NAV = [
    ['live.html','速報','live-nav'],
    ['index.html','トップ',''],
    ['world.html','世界',''],
    ['asia.html','アジア',''],
    ['hong-kong.html','香港',''],
    ['japan.html','日本',''],
    ['finance.html','経済',''],
    ['stocks.html','株式ニュース',''],
    ['technology.html','AI・テクノロジー',''],
    ['manga-anime.html','漫画・アニメ',''],
    ['manchester-united.html','マンチェスター・U',''],
    ['football.html','サッカー',''],
    ['archive.html','アーカイブ','']
  ];

  function ensureStyle(){
    if(document.querySelector('link[data-system-ja]')) return;
    const link=document.createElement('link');
    link.rel='stylesheet';
    link.href='assets/css/system-ja.css?v=20260823-2044';
    link.dataset.systemJa='true';
    document.head.appendChild(link);
  }

  function currentPage(){
    return (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  }

  function normalizeNav(){
    const nav=document.querySelector('.section-nav');
    if(!nav) return;
    const page=currentPage();
    nav.setAttribute('aria-label','ニュース分野');
    nav.innerHTML=NAV.map(([href,label,cls])=>{
      const current=href.toLowerCase()===page;
      return `<a${cls?` class="${cls}"`:''} href="${href}"${current?' aria-current="page"':''}>${label}</a>`;
    }).join('');
  }

  function row(id,title,detail){
    return `<div id="${id}" class="system-panel-row status-check"><span class="status-dot" aria-hidden="true"></span><div><strong>${title}</strong><small>${detail}</small></div></div>`;
  }

  function mark(id,state,detail){
    const el=document.getElementById(id);
    if(!el) return;
    el.className=`system-panel-row status-${state}`;
    if(detail){const small=el.querySelector('small');if(small)small.textContent=detail;}
  }

  async function jsonHealth(path,test){
    try{
      const r=await fetch(`${path}?health=${Date.now()}`,{cache:'no-store'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      const data=await r.json();
      return test(data);
    }catch(e){return false;}
  }

  async function refreshHealth(){
    mark('status-site','ok','GitHub Pages からこのページを正常に表示中');
    const latest=await jsonHealth('data/latest.json',d=>d?.language==='ja'&&Array.isArray(d?.articles)&&d.articles.length>0);
    mark('status-daily',latest?'ok':'fail',latest?'latest.json：日本語記事を正常に取得':'latest.json：取得または日本語検証に失敗');
    const live=await jsonHealth('data/live.json',d=>d?.language==='ja'&&Array.isArray(d?.items));
    mark('status-live',live?'ok':'fail',live?'live.json：日本語速報データを正常に取得':'live.json：取得または日本語検証に失敗');
    const audio=await jsonHealth('audio/manifest.json',d=>d&&typeof d==='object'&&Object.keys(d).length>0);
    mark('status-audio',audio?'ok':'fail',audio?'Supertonic 3 F3：音声 manifest を確認':'Supertonic 3 F3：音声 manifest を確認できません');
  }

  function mountSystemPanel(){
    if(document.getElementById('system-status-button')) return;
    const button=document.createElement('button');
    button.id='system-status-button';
    button.className='system-status-button';
    button.type='button';
    button.setAttribute('aria-label','システム状態');
    button.setAttribute('aria-expanded','false');
    button.innerHTML='<span class="system-status-dot" aria-hidden="true"></span><span class="system-status-label">SYSTEM</span>';

    const panel=document.createElement('aside');
    panel.id='system-status-panel';
    panel.className='system-status-panel';
    panel.hidden=true;
    panel.innerHTML=`<div class="system-panel-head"><div><strong>システム状態</strong><span>日本語版・稼働確認</span></div><button type="button" class="system-panel-close" aria-label="閉じる">×</button></div>${row('status-site','ウェブサイト','確認中')}${row('status-daily','デイリー版','確認中')}${row('status-live','速報','確認中')}${row('status-audio','日本語音声','確認中')}<div class="system-panel-links"><a href="https://github.com/kanuli/daily-brief-newspaper-japanese/actions" target="_blank" rel="noopener noreferrer">GitHub Actions ↗</a><a href="https://github.com/kanuli/daily-brief-newspaper-japanese" target="_blank" rel="noopener noreferrer">Repository ↗</a></div>`;

    const setOpen=open=>{panel.hidden=!open;button.setAttribute('aria-expanded',String(open));if(open)refreshHealth();};
    button.addEventListener('click',()=>setOpen(panel.hidden));
    panel.querySelector('.system-panel-close')?.addEventListener('click',()=>setOpen(false));
    document.addEventListener('keydown',e=>{if(e.key==='Escape')setOpen(false);});
    document.body.append(button,panel);
  }

  function boot(){ensureStyle();normalizeNav();mountSystemPanel();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.addEventListener('pageshow',normalizeNav);
})();
