(() => {
  'use strict';

  const NAV = [
    ['live.html','<ruby>速報<rt>そくほう</rt></ruby>','live-nav'],
    ['index.html','<ruby>一面<rt>いちめん</rt></ruby>トップ',''],
    ['world.html','<ruby>世界<rt>せかい</rt></ruby>',''],
    ['asia.html','アジア',''],
    ['hong-kong.html','<ruby>香港<rt>ほんこん</rt></ruby>',''],
    ['japan.html','<ruby>日本<rt>にほん</rt></ruby>',''],
    ['finance.html','<ruby>経済<rt>けいざい</rt></ruby>',''],
    ['stocks.html','<ruby>株式<rt>かぶしき</rt></ruby>ニュース',''],
    ['technology.html','AI・テクノロジー',''],
    ['manga-anime.html','<ruby>漫画<rt>まんが</rt></ruby>・アニメ',''],
    ['manchester-united.html','マンチェスター・U',''],
    ['football.html','サッカー',''],
    ['archive.html','アーカイブ','']
  ];

  const NEWSPAPER_CSS='assets/css/newspaper.css?v=20260825-cantonese-layout2';
  const ERROR_RE=/(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)/i;
  const CHINESE_PROSE_RE=/(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|白禮頓|阿士東|維拉)/;
  const HIRA_RE=/[\u3040-\u309f]/g;
  const HAN_RE=/[\u3400-\u9fff]/g;
  const PROSE_FIELDS=['dek','summary','body','context','why','watchNext'];

  function ensureNewspaperStyle(){
    const current=[...document.querySelectorAll('link[rel="stylesheet"]')].find(link=>String(link.getAttribute('href')||'').includes('assets/css/newspaper.css'));
    if(current){
      if(current.getAttribute('href')!==NEWSPAPER_CSS)current.setAttribute('href',NEWSPAPER_CSS);
      return;
    }
    const link=document.createElement('link');
    link.rel='stylesheet';
    link.href=NEWSPAPER_CSS;
    document.head.prepend(link);
  }

  function ensureStyle(){
    if(document.querySelector('link[data-system-ja]')) return;
    const link=document.createElement('link');
    link.rel='stylesheet';
    link.href='assets/css/system-ja.css?v=20260823-2044';
    link.dataset.systemJa='true';
    document.head.appendChild(link);
  }

  function ensureIntegrityGuard(){
    const present=[...document.scripts].some(s=>String(s.src||'').includes('assets/js/live-guard.js'));
    if(present||document.querySelector('script[data-integrity-guard]'))return;
    const script=document.createElement('script');
    script.src='assets/js/live-guard.js?v=20260824-furigana4';
    script.dataset.integrityGuard='true';
    document.head.appendChild(script);
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

    document.querySelectorAll('a[href="index.html"]').forEach(a=>{
      if(a.closest('.section-nav')) return;
      const text=a.textContent.trim();
      if(text==='トップへ'||text==='一面トップへ') a.innerHTML='<ruby>一面<rt>いちめん</rt></ruby>トップへ';
      else if(text==='トップ'||text==='一面トップ') a.innerHTML='<ruby>一面<rt>いちめん</rt></ruby>トップ';
    });
  }

  function applyStaticRuby(){
    document.querySelectorAll('.brand h1').forEach(h=>{
      if(h.textContent.trim()==='日刊速報')h.innerHTML='<ruby>日刊速報<rt>にっかんそくほう</rt></ruby>';
    });
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

  function mixedJapaneseProse(value=''){
    const text=String(value||'').trim();
    if(!text)return false;
    if(CHINESE_PROSE_RE.test(text))return true;
    if(text.length<28)return false;
    const han=(text.match(HAN_RE)||[]).length;
    const hira=(text.match(HIRA_RE)||[]).length;
    return han>=8&&hira<Math.max(2,Math.floor(han*.06));
  }

  function hasErrorPayload(value){
    if(typeof value==='string')return ERROR_RE.test(value);
    if(Array.isArray(value))return value.some(hasErrorPayload);
    if(value&&typeof value==='object')return Object.values(value).some(hasErrorPayload);
    return false;
  }

  function publicationDataHealthy(data,mode){
    if(!data||data.language!=='ja'||hasErrorPayload(data))return false;
    const items=mode==='live'?data.items:data.articles;
    if(!Array.isArray(items)||items.length===0)return false;
    if(items.some(item=>PROSE_FIELDS.some(key=>mixedJapaneseProse(item?.[key]))))return false;
    if(mode==='live'&&!/^次回発行予定 (?:[01]\d|2[0-4]):[0-5]\d HKT$/.test(String(data.nextUpdateLabel||'')))return false;
    return true;
  }

  async function jsonData(path){
    try{
      const r=await fetch(`${path}?health=${Date.now()}`,{cache:'no-store'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    }catch(e){return null;}
  }

  async function refreshHealth(){
    mark('status-site','ok','静的ページと共通ナビゲーションを正常に表示中');
    const latestData=await jsonData('data/latest.json');
    const latest=publicationDataHealthy(latestData,'daily');
    mark('status-daily',latest?'ok':'fail',latest?'latest.json：日本語本文・エラー混入チェック正常':'latest.json：翻訳エラーまたは未完了データを検出');
    const liveData=await jsonData('data/live.json');
    const live=publicationDataHealthy(liveData,'live');
    mark('status-live',live?'ok':'fail',live?'live.json：日本語速報・次回発行時刻チェック正常':'live.json：翻訳エラー、未完了データ、または発行時刻異常を検出');
    const manifest=await jsonData('audio/manifest.json');
    const audio=latest&&live&&manifest&&typeof manifest==='object'&&Object.keys(manifest).length>0;
    mark('status-audio',audio?'ok':'fail',audio?'Supertonic 3 F3：クリーンな記事データと音声manifestを確認':'Supertonic 3 F3：記事データ正常化後に再確認が必要');
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
    panel.innerHTML=`<div class="system-panel-head"><div><strong><ruby>システム状態<rt>じょうたい</rt></ruby></strong><span><ruby>日本語版<rt>にほんごばん</rt></ruby>・<ruby>稼働確認<rt>かどうかくにん</rt></ruby></span></div><button type="button" class="system-panel-close" aria-label="閉じる">×</button></div>${row('status-site','ウェブサイト','確認中')}${row('status-daily','デイリー版','確認中')}${row('status-live','<ruby>速報<rt>そくほう</rt></ruby>','確認中')}${row('status-audio','<ruby>日本語音声<rt>にほんごおんせい</rt></ruby>','確認中')}<div class="system-panel-links"><a href="https://github.com/kanuli/daily-brief-newspaper-japanese/actions" target="_blank" rel="noopener noreferrer">GitHub Actions ↗</a><a href="https://github.com/kanuli/daily-brief-newspaper-japanese" target="_blank" rel="noopener noreferrer">Repository ↗</a></div>`;

    const setOpen=open=>{panel.hidden=!open;button.setAttribute('aria-expanded',String(open));if(open)refreshHealth();};
    button.addEventListener('click',()=>setOpen(panel.hidden));
    panel.querySelector('.system-panel-close')?.addEventListener('click',()=>setOpen(false));
    document.addEventListener('keydown',e=>{if(e.key==='Escape')setOpen(false);});
    document.body.append(button,panel);
  }

  function boot(){ensureNewspaperStyle();ensureStyle();normalizeNav();applyStaticRuby();mountSystemPanel();ensureIntegrityGuard();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.addEventListener('pageshow',()=>{ensureNewspaperStyle();normalizeNav();applyStaticRuby();ensureIntegrityGuard();});
})();
