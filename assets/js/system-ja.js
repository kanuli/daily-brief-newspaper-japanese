(() => {
  'use strict';

  const BUILD='20260828-newsroom-health';
  const HEALTH_MAX_AGE_MS=50*60*1000;
  const HEALTH_REFRESH_MS=60*1000;
  let healthTimer=null;

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

  const TOPICS = {
    world:{utility:'WORLD DESK · ROLLING NEWSPAPER',side:'欧州 · アフリカ<br>北米 · 中南米 · オセアニア',right:'WORLD NEWS<br>NON-ASIA DESK',kicker:'WORLD NEWS DESK',title:'世界',description:'アジア以外の欧州、アフリカ、北米、中南米、オセアニアを中心に、政治、社会、戦争・外交、公共安全、気候、経済など重要な国際ニュースを掲載します。'},
    asia:{utility:'ASIA DESK · ROLLING NEWSPAPER',side:'東アジア · 東南アジア<br>南アジア · 中央アジア · 西アジア',right:'ASIA NEWS<br>REGIONAL DESK',kicker:'ASIA NEWS DESK',title:'アジア',description:'中国、台湾、韓国、東南アジア、南アジア、中央アジア、西アジア・中東を含むアジア各地の重要ニュースを掲載します。'},
    'hong-kong':{utility:'HONG KONG DESK · ROLLING NEWSPAPER',side:'社会 · 司法<br>公共政策 · 暮らし · 文化',right:'HONG KONG NEWS<br>LOCAL DESK',kicker:'HONG KONG NEWS DESK',title:'香港',description:'香港の社会、政策、司法、交通、暮らし、文化など、日々の生活に関わるニュースを詳しく掲載します。'},
    japan:{utility:'JAPAN DESK · ROLLING NEWSPAPER',side:'社会 · 司法<br>政策 · 交通 · 教育 · 医療',right:'JAPAN NEWS<br>DOMESTIC DESK',kicker:'JAPAN NEWS DESK',title:'日本',description:'日本の社会、政策、司法、交通、教育、医療、暮らしなど、重要な国内ニュースを幅広く掲載します。'},
    'market-economy':{utility:'MARKET & ECONOMY · ROLLING NEWSPAPER',side:'米国 · 欧州 · 日本<br>香港 · 中国 · 世界市場',right:'MARKET NEWS<br>ECONOMY DESK',kicker:'MARKET & ECONOMY DESK',title:'経済・世界市場',description:'米国、欧州、日本、香港、中国などの経済、金利、為替、商品、市場動向をまとめます。'},
    technology:{utility:'TECHNOLOGY DESK · ROLLING NEWSPAPER',side:'AI · 半導体<br>科学 · サイバー · ソフトウェア',right:'AI & TECHNOLOGY<br>ROLLING DESK',kicker:'AI & TECHNOLOGY DESK',title:'AI・テクノロジー',description:'AI、半導体、科学・新技術、サイバーセキュリティ、ソフトウェア、アプリ、消費者向け技術を掲載します。'},
    'manga-anime':{utility:'MANGA / ANIME · ROLLING NEWSPAPER',side:'作品 · 産業<br>興行 · 声優 · 出版',right:'MANGA / ANIME<br>CULTURE DESK',kicker:'MANGA / ANIME DESK',title:'漫画・アニメ',description:'漫画・アニメの作品、産業、興行、出版、声優などのニュースを掲載します。'},
    'manchester-united':{utility:'MANCHESTER UNITED · ROLLING NEWSPAPER',side:'Club · Squad<br>Transfers · Matches',right:'MANCHESTER UNITED<br>CLUB DESK',kicker:'MANCHESTER UNITED DESK',title:'マンチェスター・ユナイテッド',description:'クラブ、選手、移籍、試合、監督・経営に関するマンチェスター・ユナイテッドの最新ニュースを掲載します。'},
    football:{utility:'FOOTBALL DESK · ROLLING NEWSPAPER',side:'Europe · UEFA<br>International · J-League · HK',right:'FOOTBALL NEWS<br>WORLDWIDE DESK',kicker:'FOOTBALL DESK',title:'サッカー',description:'欧州主要リーグ、UEFA、代表戦、Jリーグ、香港、世界各地のサッカーニュースと試合結果を掲載します。'}
  };

  const ERROR_RE=/(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)/i;
  const CHINESE_PROSE_RE=/(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|白禮頓|阿士東|維拉)/;
  const HIRA_RE=/[\u3040-\u309f]/g;
  const HAN_RE=/[\u3400-\u9fff]/g;
  const PROSE_FIELDS=['dek','summary','body','context','why','watchNext'];

  function currentPage(){ return (location.pathname.split('/').pop() || 'index.html').toLowerCase(); }
  function assetBase(value){ return String(value||'').split('?',1)[0].split('#',1)[0]; }
  function hasAsset(fragment){
    const needle=assetBase(fragment);
    return [...document.querySelectorAll('script[src],link[href]')].some(el=>assetBase(el.getAttribute('src')||el.getAttribute('href')||'').includes(needle));
  }
  function addCss(path,key){ if(hasAsset(path))return;const link=document.createElement('link');link.rel='stylesheet';link.href=path;link.dataset[key||'jpAsset']='true';document.head.appendChild(link); }
  function addScript(path,key){ if(hasAsset(path))return;const script=document.createElement('script');script.src=path;script.defer=true;script.dataset[key||'jpAsset']='true';document.body.appendChild(script); }

  function ensureBaseStyles(){
    if(!hasAsset('assets/css/newspaper.css'))addCss('assets/css/newspaper.css','newspaperJa');
    if(!hasAsset('assets/css/system-ja.css'))addCss('assets/css/system-ja.css','systemJa');
  }

  function ensurePageAssets(){
    const page=document.body.dataset.page||'home',desk=document.body.dataset.desk||'';
    if(page==='home'){
      addCss(`assets/css/live-ja.css?v=${BUILD}`);
      addCss(`assets/css/home-parity-ja.css?v=${BUILD}`);
      addScript(`assets/js/home-extras-ja.js?v=${BUILD}`);
    }
    if(page==='live'){
      addCss(`assets/css/live-ja.css?v=${BUILD}`);
      addScript(`assets/js/live-article-ja.js?v=${BUILD}`);
    }
    if(page==='topic'&&desk!=='stocks'){
      addCss(`assets/css/topic-ja-rolling.css?v=${BUILD}`);
      addScript(`assets/js/topic-ja-rolling.js?v=${BUILD}`);
    }
    if(page==='stocks'||(page==='topic'&&desk==='stocks')){
      addCss(`assets/css/stocks-ja.css?v=${BUILD}`);
      addScript(`assets/js/stocks-ja.js?v=${BUILD}`);
    }
  }

  function normalizeNav(){
    const nav=document.querySelector('.section-nav');if(!nav)return;const page=currentPage();nav.setAttribute('aria-label','ニュース分野');
    nav.innerHTML=NAV.map(([href,label,cls])=>`<a${cls?` class="${cls}"`:''} href="${href}"${href.toLowerCase()===page?' aria-current="page"':''}>${label}</a>`).join('');
  }

  function normalizeTopicShell(){
    if(document.body.dataset.page!=='topic')return;
    let desk=document.body.dataset.desk||'';if(desk==='finance')desk='market-economy';if(desk==='stocks')return;
    const meta=TOPICS[desk];if(!meta)return;
    const utility=document.querySelector('.utility-bar');if(utility)utility.innerHTML=`<span>${meta.utility}</span><span>DAILY + ROLLING + LIVE</span>`;
    const masthead=document.querySelector('.masthead');if(masthead)masthead.innerHTML=`<div class="masthead-side">${meta.side}</div><div class="brand"><div class="brand-kicker">個 人 向 け 電 子 新 聞</div><h1>日刊速報</h1><div class="brand-sub">DAILY BRIEF</div></div><div class="masthead-side right">${meta.right}</div>`;
    const main=document.querySelector('main');if(!main)return;
    const existingFatal=document.querySelector('#fatal');const existingItems=document.querySelector('#topic-items');
    if(!main.querySelector('.topic-page-head')){
      main.innerHTML=`<section class="topic-page-head"><div class="topic-page-kicker">${meta.kicker}</div><h1 class="topic-title" id="topic-title">${meta.title}</h1><p id="topic-subtitle">${meta.description}</p></section><p id="fatal" class="notice"></p><div id="topic-items"><p class="notice">デイリー版、追加記事、ローリングニュース、速報を統合しています…</p></div>`;
      if(existingFatal?.textContent)document.querySelector('#fatal').textContent=existingFatal.textContent;
      if(existingItems?.innerHTML&&existingItems.children.length)document.querySelector('#topic-items').innerHTML=existingItems.innerHTML;
    }else{
      const title=document.querySelector('#topic-title');if(title)title.textContent=meta.title;
      const subtitle=document.querySelector('#topic-subtitle');if(subtitle&&!subtitle.textContent.trim())subtitle.textContent=meta.description;
    }
    const footer=document.querySelector('.footer');if(footer)footer.innerHTML=`<span>日刊速報 · ${meta.title}</span><span><a href="live.html">速報</a> · <a href="index.html">一面トップ</a> · <a href="archive.html">アーカイブ</a></span>`;
  }

  function applyStaticRuby(){document.querySelectorAll('.brand h1').forEach(h=>{if(h.textContent.trim()==='日刊速報')h.innerHTML='<ruby>日刊速報<rt>にっかんそくほう</rt></ruby>';});}

  function ensureIntegrityGuard(){if(hasAsset('assets/js/live-guard.js'))return;addScript(`assets/js/live-guard.js?v=${BUILD}`,'integrityGuard');}
  function ensureVoiceProductionStatus(){if(hasAsset('assets/js/f3-voice-status-ja.js'))return;addScript(`assets/js/f3-voice-status-ja.js?v=${BUILD}`,'f3VoiceStatusJa');}
  function row(id,title,detail){return `<div id="${id}" class="system-panel-row status-check"><span class="status-dot" aria-hidden="true"></span><div><strong>${title}</strong><small>${detail}</small></div></div>`;}
  function mark(id,state,detail){const el=document.getElementById(id);if(!el)return;el.className=`system-panel-row status-${state}`;if(detail){const small=el.querySelector('small');if(small)small.textContent=detail;}}
  function setSystemState(state,detail=''){
    const button=document.getElementById('system-status-button');
    const dot=button?.querySelector('.system-status-dot');
    if(!button||!dot)return;
    const palette={ok:'#198754',warn:'#b26a00',fail:'#b00020',check:'#6c757d'};
    dot.style.background=palette[state]||palette.check;
    dot.style.boxShadow='none';
    button.dataset.healthState=state;
    const label=state==='ok'?'正常':state==='warn'?'注意':state==='fail'?'異常':'確認中';
    const text=`SYSTEM ${label}${detail?` — ${detail}`:''}`;
    button.title=text;
    button.setAttribute('aria-label',text);
  }
  function mixedJapaneseProse(value=''){const text=String(value||'').trim();if(!text)return false;if(CHINESE_PROSE_RE.test(text))return true;if(text.length<28)return false;const han=(text.match(HAN_RE)||[]).length,hira=(text.match(HIRA_RE)||[]).length;return han>=8&&hira<Math.max(2,Math.floor(han*.06));}
  function hasErrorPayload(value){if(typeof value==='string')return ERROR_RE.test(value);if(Array.isArray(value))return value.some(hasErrorPayload);if(value&&typeof value==='object')return Object.values(value).some(hasErrorPayload);return false;}
  function publicationDataHealthy(data,mode){if(!data||data.language!=='ja'||hasErrorPayload(data))return false;const items=mode==='live'?data.items:data.articles;if(!Array.isArray(items)||!items.length)return false;if(items.some(item=>PROSE_FIELDS.some(key=>mixedJapaneseProse(item?.[key]))))return false;if(mode==='live'&&!/^次回発行予定 (?:[01]\d|2[0-4]):[0-5]\d HKT$/.test(String(data.nextUpdateLabel||'')))return false;return true;}
  async function jsonData(path){try{const r=await fetch(`${path}?health=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json();}catch(e){return null;}}
  function healthFresh(data){const ts=Date.parse(String(data?.assessedAt||''));return Number.isFinite(ts)&&Date.now()>=ts&&Date.now()-ts<=HEALTH_MAX_AGE_MS;}
  function layerOk(health,name){return health?.layers?.[name]?.current===true;}
  function layerDetail(health,name,label){
    const layer=health?.layers?.[name];
    if(!layer)return `${label}：総編集ロボットの判定なし`;
    if(layer.current===true)return `${label}：最新性確認済み`;
    const lag=Number.isFinite(Number(layer.lagMinutes))?`（遅延 ${Math.max(0,Math.round(Number(layer.lagMinutes)))}分）`:'';
    return `${label}：更新遅延${lag}`;
  }
  async function refreshHealth(){
    setSystemState('check','総編集ロボットを確認中');
    const [latestData,liveData,health,manifest]=await Promise.all([
      jsonData('data/latest.json'),jsonData('data/live.json'),jsonData('data/newsroom-health.json'),jsonData('audio/manifest.json')
    ]);
    const latest=publicationDataHealthy(latestData,'daily');
    const live=publicationDataHealthy(liveData,'live');
    const fresh=healthFresh(health);
    const required=['daily','live','desk','stocks','structural'];
    const robotGreen=fresh&&health?.state==='GREEN'&&required.every(name=>layerOk(health,name));
    const structural=fresh&&layerOk(health,'structural');
    const dailyCurrent=fresh&&layerOk(health,'daily');
    const liveCurrent=fresh&&layerOk(health,'live');
    const deskCurrent=fresh&&layerOk(health,'desk');
    const stocksCurrent=fresh&&layerOk(health,'stocks');

    mark('status-robot',robotGreen?'ok':'fail',!fresh?'総編集ロボット：health snapshot が欠落または50分超過':robotGreen?'総編集ロボット：全ニュース層 current':'総編集ロボット：RECOVERY / RED');
    mark('status-site',structural?'ok':'fail',structural?'13読者ページの構造確認済み':'ページ構造または robot snapshot に異常');
    mark('status-daily',dailyCurrent&&latest?'ok':'fail',dailyCurrent&&latest?'デイリー版：最新性・日本語品質正常':layerDetail(health,'daily','デイリー版'));
    mark('status-live',liveCurrent&&live?'ok':'fail',liveCurrent&&live?'速報：最新性・日本語品質正常':layerDetail(health,'live','速報'));
    mark('status-rolling',deskCurrent?'ok':'fail',layerDetail(health,'desk','ローリング分類'));
    mark('status-stocks',stocksCurrent?'ok':'fail',layerDetail(health,'stocks','株式ニュース'));
    const audio=latest&&live&&manifest&&typeof manifest==='object'&&Object.keys(manifest).length>0;
    mark('status-audio',audio?'ok':'warn',audio?'Supertonic 3 F3：音声manifest確認':'Supertonic 3 F3：音声準備中または再確認が必要');

    const newsHealthy=robotGreen&&latest&&live;
    if(!newsHealthy){
      const summary=!fresh?'robot health missing/stale':String(health?.summary||'news layer stale');
      setSystemState('fail',summary);
    }else if(!audio){
      setSystemState('warn','ニュース正常・音声準備中');
    }else{
      setSystemState('ok','全ニュース層 current');
    }
  }
  function mountSystemPanel(){
    if(document.getElementById('system-status-button'))return;
    const button=document.createElement('button');button.id='system-status-button';button.className='system-status-button';button.type='button';button.setAttribute('aria-label','SYSTEM 確認中');button.setAttribute('aria-expanded','false');button.innerHTML='<span class="system-status-dot" aria-hidden="true"></span><span class="system-status-label">SYSTEM</span>';
    const panel=document.createElement('aside');panel.id='system-status-panel';panel.className='system-status-panel';panel.hidden=true;panel.innerHTML=`<div class="system-panel-head"><div><strong><ruby>システム状態<rt>じょうたい</rt></ruby></strong><span><ruby>日本語版<rt>にほんごばん</rt></ruby>・<ruby>稼働確認<rt>かどうかくにん</rt></ruby></span></div><button type="button" class="system-panel-close" aria-label="閉じる">×</button></div>${row('status-robot','総編集ロボット','確認中')}${row('status-site','ウェブサイト','確認中')}${row('status-daily','デイリー版','確認中')}${row('status-live','<ruby>速報<rt>そくほう</rt></ruby>','確認中')}${row('status-rolling','ローリング分類','確認中')}${row('status-stocks','株式ニュース','確認中')}${row('status-audio','<ruby>日本語音声<rt>にほんごおんせい</rt></ruby>','確認中')}<div class="system-panel-links"><a href="https://github.com/kanuli/daily-brief-newspaper-japanese/actions" target="_blank" rel="noopener noreferrer">GitHub Actions ↗</a><a href="https://github.com/kanuli/daily-brief-newspaper-japanese" target="_blank" rel="noopener noreferrer">Repository ↗</a></div>`;
    const setOpen=open=>{panel.hidden=!open;button.setAttribute('aria-expanded',String(open));if(open)refreshHealth();};button.addEventListener('click',()=>setOpen(panel.hidden));panel.querySelector('.system-panel-close')?.addEventListener('click',()=>setOpen(false));document.addEventListener('keydown',e=>{if(e.key==='Escape')setOpen(false);});document.body.append(button,panel);
    setSystemState('check','総編集ロボットを確認中');
    refreshHealth();
    if(!healthTimer)healthTimer=setInterval(refreshHealth,HEALTH_REFRESH_MS);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshHealth();});
  }

  function boot(){ensureBaseStyles();normalizeNav();normalizeTopicShell();applyStaticRuby();ensurePageAssets();mountSystemPanel();ensureVoiceProductionStatus();ensureIntegrityGuard();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.addEventListener('pageshow',()=>{ensureBaseStyles();normalizeNav();normalizeTopicShell();applyStaticRuby();ensurePageAssets();mountSystemPanel();ensureVoiceProductionStatus();ensureIntegrityGuard();refreshHealth();});
})();
