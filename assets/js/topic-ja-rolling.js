(() => {
  'use strict';
  if (document.body.dataset.page !== 'topic') return;
  if (![...document.querySelectorAll('link[rel="stylesheet"]')].some(link => String(link.href || '').includes('assets/css/topic-ja-rolling.css'))) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'assets/css/topic-ja-rolling.css';
    document.head.appendChild(link);
  }

  const TECH = new Set(['technology','ai-tech','science-new-tech','cybersecurity','software-apps']);
  const SAFE_LOWER = new Set(['vs','km','kg','cm','mm','ms','gb','tb','mb','kb','fps','bps','kbps','mbps','gbps','app','apps','web','live','online','email','alpha','beta','http','https','www','com','org','net']);

  function corruptText(value = '') {
    const text = String(value || '');
    if (!text) return false;
    if (/\uFFFD|[\u0000-\u0008\u000B\u000C\u000E-\u001F]/u.test(text)) return true;
    if (/[\u0400-\u04ff]/u.test(text)) return true;
    if (/の{5,}/u.test(text)) return true;
    if (/[ \t]{6,}/u.test(text)) return true;
    if (/(?:\(\s*\)){3,}|(?:（\s*）){3,}/u.test(text)) return true;
    if (/[━─═┅┄┈┉＿_~〜]{4,}/u.test(text)) return true;
    if (/(.{2,8})(?:\s+\1){2,}/u.test(text)) return true;
    if (/マンチケット|魔女tz|ヘルメットを被ったデカパン|0um32|クーデターum32/u.test(text)) return true;
    const lower = text.match(/(?<![A-Za-z])[a-z]{2,}(?![A-Za-z])/g) || [];
    if (lower.some(word => !SAFE_LOWER.has(word.toLowerCase()))) return true;
    return false;
  }

  function corruptStory(article = {}) {
    if (String(article?.qualityStatus || '') === 'QUARANTINED_GARBLED_TRANSLATION') return true;
    if (String(article?.title || '').trim() === '翻訳品質を再検証中のニュース') return true;
    return ['title','dek','summary','body','context','why','watchNext','timeLabel']
      .some(field => corruptText(article?.[field]));
  }

  async function optionalJson(path) {
    try {
      const response = await fetch(path, { cache: 'no-store' });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.warn('optional Japanese news layer unavailable', path, error);
      return null;
    }
  }

  function normalizedTitle(value = '') {
    return String(value).normalize('NFKC').toLowerCase().replace(/\d+(?:[.,]\d+)?/g, '').replace(/[\s\p{P}\p{S}]+/gu, '').replace(/(最新|正式|今日|今夜|速報|更新)/g, '').slice(0, 180);
  }

  function sameEvent(a, b) {
    if (!a || !b) return false;
    if (a.id && b.id && a.id === b.id) return true;
    const ak = normalizedTitle(a.title), bk = normalizedTitle(b.title);
    if (ak && bk && (ak === bk || (ak.length >= 16 && bk.length >= 16 && (ak.includes(bk) || bk.includes(ak))))) return true;
    const au = String(a.sourceUrl || '').split('?')[0], bu = String(b.sourceUrl || '').split('?')[0];
    return Boolean(au && bu && au === bu && ak && bk);
  }

  function storyLike(value) {
    return value && typeof value === 'object' && !Array.isArray(value) && value.id && value.title && (value.dek || value.summary || value.body);
  }

  function collectStories(value, out = []) {
    if (storyLike(value)) out.push(value);
    if (Array.isArray(value)) value.forEach(child => collectStories(child, out));
    else if (value && typeof value === 'object') Object.values(value).forEach(child => collectStories(child, out));
    return out;
  }

  function articleSlugs(article = {}) {
    const out = new Set();
    if (Array.isArray(article.deskSlugs)) article.deskSlugs.forEach(slug => out.add(String(slug)));
    if (article.desk) out.add(String(article.desk));
    try { out.add(deskOf(article)); } catch (_) {}
    return out;
  }

  function matchesDesk(article, wanted) {
    const slugs = articleSlugs(article);
    if (wanted === 'technology') return [...slugs].some(slug => TECH.has(slug));
    if (wanted === 'market-economy') return slugs.has('market-economy') || slugs.has('finance');
    if (wanted === 'stocks') return slugs.has('stocks') || slugs.has('stock-news');
    return slugs.has(wanted);
  }

  function mergeStory(list, article, layer, prepend = false) {
    if (!storyLike(article)) return;
    if (corruptStory(article)) {
      console.error('QUARANTINED_GARBLED_JAPANESE_STORY', article.id || '', layer);
      return;
    }
    const copy = { ...article, _jpLayer: layer };
    const index = list.findIndex(existing => sameEvent(existing, copy));
    if (index >= 0) {
      const previous = list[index];
      list[index] = { ...previous, ...copy, id: previous.id || copy.id };
      if (prepend && index > 0) list.unshift(list.splice(index, 1)[0]);
      return;
    }
    prepend ? list.unshift(copy) : list.push(copy);
  }

  function stockStories(payload) {
    const out = [];
    const tickers = payload?.tickers;
    if (!tickers || typeof tickers !== 'object') return out;
    Object.entries(tickers).forEach(([ticker, info]) => {
      (Array.isArray(info?.stories) ? info.stories : []).forEach(story => {
        if (!corruptStory(story)) out.push({ ...story, desk: 'stocks', deskSlugs: ['stocks'], section: story.section || `株式ニュース・${ticker}` });
      });
    });
    return out;
  }

  async function buildTopicStories(daily, wanted) {
    const list = [];
    (daily.articles || []).filter(article => matchesDesk(article, wanted)).forEach(article => mergeStory(list, article, 'daily', false));
    const [topicMore, deskLatest, stocksLatest, live] = await Promise.all([
      optionalJson(`data/topic-more/${daily.date}.json`),
      optionalJson('data/desk-latest.json'),
      wanted === 'stocks' ? optionalJson('data/stocks-latest.json') : Promise.resolve(null),
      optionalJson('data/live.json'),
    ]);
    collectStories(topicMore).filter(article => matchesDesk(article, wanted)).forEach(article => mergeStory(list, article, 'more', false));
    collectStories(deskLatest).filter(article => matchesDesk(article, wanted)).reverse().forEach(article => mergeStory(list, article, 'rolling', true));
    if (stocksLatest) stockStories(stocksLatest).reverse().forEach(article => mergeStory(list, article, 'rolling', true));
    (live?.items || []).filter(article => matchesDesk(article, wanted)).slice().reverse().forEach(article => mergeStory(list, article, 'live', true));
    return list;
  }

  function badge(article) {
    if (article._jpLayer === 'live') return '<span class="topic-live-badge">速報</span>';
    if (article._jpLayer === 'rolling') return '<span class="topic-latest-badge">最新</span>';
    if (article._jpLayer === 'more') return '<span class="topic-more-badge">追加</span>';
    return '';
  }

  function paragraph(label, article, field, cls) {
    const value = article?.[field];
    if (!value) return '';
    const inner = field === 'why' || field === 'watchNext' ? syncSpan(article, field === 'watchNext' ? 'watch' : field, ruby(article, field, value)) : ruby(article, field, value);
    return `<p class="${cls}"><strong>${label}</strong>${inner}</p>`;
  }

  function bodyMarkup(article) {
    const parts = rubyBodyParagraphs(article);
    if (!parts.length) return '';
    return `<div class="topic-full-body">${parts.map((part, index) => `<p>${syncSpan(article, `body-${index}`, part)}</p>`).join('')}</div>`;
  }

  function articleMarkup(article, featured = false) {
    const section = ruby(article, 'section', article.section || DESKS[deskOf(article)]?.[0] || 'ニュース');
    return `<article class="topic-story ${featured ? 'topic-feature' : ''} ${article._jpLayer === 'live' ? 'topic-live-story' : ''}"><div class="tag">${badge(article)}${section}</div><h2>${syncSpan(article, 'title', ruby(article, 'title', article.title || ''))}</h2>${article.dek ? `<p class="topic-dek">${syncSpan(article, 'dek', ruby(article, 'dek', article.dek))}</p>` : ''}<div class="story-meta">${esc(article.timeLabel || '')}${article.sourceName ? ` ・ ${esc(article.sourceName)}` : ''}</div>${audio(article)}<div class="topic-article-body">${article.summary ? paragraph('最新：', article, 'summary', 'topic-summary') : ''}${bodyMarkup(article)}${paragraph('背景：', article, 'context', 'topic-context')}${paragraph('重要な理由：', article, 'why', 'why-mini')}${paragraph('今後の注目：', article, 'watchNext', 'topic-next')}</div>${source(article)}</article>`;
  }

  function formatEditionDate(daily) {
    let value = String(daily?.dateLabel || daily?.date || '').trim();
    value = value.replace(/(\d{1,2}日)([月火水木金土日]曜日)/, '$1 $2');
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      const [y,m,d] = value.split('-').map(Number);
      const weekday = ['日曜日','月曜日','火曜日','水曜日','木曜日','金曜日','土曜日'][new Date(Date.UTC(y,m-1,d)).getUTCDay()];
      value = `${y}年${m}月${d}日 ${weekday}`;
    }
    return value;
  }

  function ensureMetaBar() {
    const head = document.querySelector('.topic-page-head');
    if (!head) return {};
    let bar = document.querySelector('.topic-page-meta');
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'topic-page-meta';
      bar.innerHTML = '<span id="topic-date">読み込み中…</span><span id="topic-count">本版を整理中…</span>';
      head.insertAdjacentElement('afterend', bar);
    }
    return { date: document.querySelector('#topic-date'), count: document.querySelector('#topic-count') };
  }

  async function renderRollingTopic() {
    const wanted = document.body.dataset.desk;
    const daily = await getJson('data/latest.json');
    setMeta(daily);
    const meta = DESKS[wanted] || [wanted, ''];
    const stories = await buildTopicStories(daily, wanted);
    const title = document.querySelector('#topic-title');
    const subtitle = document.querySelector('#topic-subtitle');
    const host = document.querySelector('#topic-items');
    const metaBar = ensureMetaBar();
    if (title) { title.classList.add('topic-page-title'); title.innerHTML = uiRuby(meta[0]); }
    if (subtitle) { subtitle.classList.add('topic-page-description'); if (!subtitle.textContent.trim()) subtitle.textContent = meta[1]; }
    if (metaBar.date) metaBar.date.textContent = formatEditionDate(daily);
    if (metaBar.count) metaBar.count.textContent = `${stories.length} stories · Daily + Rolling Desk + 速報`;
    if (!host) return;
    host.innerHTML = stories.length ? `<div class="topic-story-grid">${stories.map((article, index) => articleMarkup(article, index === 0)).join('')}</div>` : '<p class="empty">現在、この分野に掲載できる確認済み記事はありません。</p>';
    document.title = `${meta[0]}｜日刊速報`;
    initAudioSync();
  }

  renderRollingTopic().catch(error => {
    console.error('rolling topic render failed', error);
    const metaBar = ensureMetaBar();
    if (metaBar.count) metaBar.count.textContent = '記事数を取得できませんでした';
  });
})();
