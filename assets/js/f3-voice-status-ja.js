(() => {
  'use strict';

  const MAIN_MANIFEST = 'audio/manifest.json';
  const ROLLING_MANIFEST = 'audio/rolling-manifest.json';
  const WORKFLOW_API = 'https://api.github.com/repos/kanuli/daily-brief-newspaper-japanese/actions/workflows/rebuild-f3-pacing.yml/runs?branch=main&per_page=6';
  const MAIN_MANIFEST_COMMITS = 'https://api.github.com/repos/kanuli/daily-brief-newspaper-japanese/commits?path=audio%2Fmanifest.json&per_page=1';
  const ROLLING_MANIFEST_COMMITS = 'https://api.github.com/repos/kanuli/daily-brief-newspaper-japanese/commits?path=audio%2Frolling-manifest.json&per_page=1';
  const MAX_PARALLEL = 3;
  const MANIFEST_REFRESH_MS = 15000;
  const WORKFLOW_REFRESH_MS = 45000;
  const LAST_VOICE_REFRESH_MS = 5 * 60 * 1000;
  const PENDING = '⏳ 日本語F3音声準備中';
  const ACTIVE = new Set(['in_progress', 'queued', 'waiting', 'pending', 'requested']);

  let mainManifest = {};
  let rollingManifest = {};
  let latestRuns = [];
  let wanted = { daily: new Set(), live: new Set(), rolling: new Set() };
  let lastVoice = '未生成';
  let manifestLoaded = false;
  let refreshQueued = false;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function ensureStyles() {
    if ($('#f3-voice-status-ja-style')) return;
    const style = document.createElement('style');
    style.id = 'f3-voice-status-ja-style';
    style.textContent = `
      .voice-production-row .voice-production-copy{min-width:0;flex:1}
      .voice-progress-top{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
      .voice-progress-percent{font-size:12px;font-weight:900;color:#79000e;white-space:nowrap}
      .voice-progress-track{height:8px;margin:6px 0 5px;border:1px solid #111;background:#ddd5c7;overflow:hidden}
      .voice-progress-fill{display:block;height:100%;width:0;background:#198754;transition:width .25s ease}
      .voice-progress-stats{display:flex!important;flex-wrap:wrap;gap:4px 10px;color:#312d27!important;font-weight:800}
      .voice-progress-stats span{white-space:nowrap}
      .voice-progress-detail{margin-top:4px!important}
      .voice-production-row.status-warn .voice-progress-fill{background:#c17b00}
      .voice-production-row.status-fail .voice-progress-fill{background:#b00016}
      .f3-pending-button{border:1px solid #222;background:#eee;color:#555;padding:7px 10px;font:700 12px/1.2 "Noto Sans JP",sans-serif;border-radius:3px;cursor:default}
      .audio-row[data-f3-voice-state="pending"] .synced-audio{display:none!important}
      .audio-row[data-f3-voice-state="ready"] .f3-pending-button{display:none!important}
    `;
    document.head.appendChild(style);
  }

  async function fetchJson(url, optional = false) {
    try {
      const target = new URL(url, document.baseURI);
      target.searchParams.set('voiceStatus', String(Date.now()));
      const response = await fetch(target.href, { cache: 'no-store', headers: { Accept: 'application/vnd.github+json' } });
      if (optional && response.status === 404) return null;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      if (!optional) console.warn('Japanese F3 status source unavailable', url, error);
      return null;
    }
  }

  function storyLike(value) {
    return value && typeof value === 'object' && !Array.isArray(value) && value.id && value.title && (value.dek || value.summary || value.body);
  }

  function collectStoryIds(value, output = new Set()) {
    if (storyLike(value)) output.add(String(value.id));
    if (Array.isArray(value)) value.forEach(child => collectStoryIds(child, output));
    else if (value && typeof value === 'object') Object.values(value).forEach(child => collectStoryIds(child, output));
    return output;
  }

  async function loadWanted() {
    const latest = await fetchJson('data/latest.json');
    const live = await fetchJson('data/live.json');
    const date = String(latest?.date || '').trim();
    const [desk, stocks, topicMore] = await Promise.all([
      fetchJson('data/desk-latest.json', true),
      fetchJson('data/stocks-latest.json', true),
      /^\d{4}-\d{2}-\d{2}$/.test(date) ? fetchJson(`data/topic-more/${date}.json`, true) : Promise.resolve(null),
    ]);

    const daily = new Set((Array.isArray(latest?.articles) ? latest.articles : []).map(item => String(item?.id || '')).filter(Boolean));
    const liveIds = new Set((Array.isArray(live?.items) ? live.items : []).map(item => String(item?.id || '')).filter(Boolean));
    const rolling = new Set();
    [desk, stocks, topicMore].filter(Boolean).forEach(payload => collectStoryIds(payload, rolling));
    wanted = { daily, live: liveIds, rolling };
    render();
  }

  function audioIdentity(audio) {
    const id = String(audio?.dataset?.syncArticle || '').trim();
    const raw = String(audio?.getAttribute?.('src') || audio?.src || '');
    if (!id || !raw) return null;
    let path = raw;
    try { path = new URL(raw, document.baseURI).pathname; } catch (_) {}
    if (path.includes('/audio/daily/')) return { group: 'daily', id, key: `daily:${id}` };
    if (path.includes('/audio/live/')) return { group: 'live', id, key: `live:${id}` };
    if (path.includes('/audio/rolling/')) return { group: 'rolling', id, key: id };
    return null;
  }

  function isReady(identity) {
    if (!identity) return false;
    if (identity.group === 'rolling') return Object.prototype.hasOwnProperty.call(rollingManifest, identity.key);
    return Object.prototype.hasOwnProperty.call(mainManifest, identity.key);
  }

  function ensurePendingButton(row) {
    let button = $('.f3-pending-button', row);
    if (button) return button;
    button = document.createElement('button');
    button.type = 'button';
    button.className = 'audio-btn f3-pending-button';
    button.disabled = true;
    button.textContent = PENDING;
    button.title = 'Supertonic 3 F3 の日本語ニュース音声を生成中です。音声manifestを15秒ごとに自動確認します。';
    row.prepend(button);
    return button;
  }

  function configureVisibleVoices() {
    ensureStyles();
    $$('.synced-audio').forEach(audio => {
      const row = audio.closest('.audio-row');
      if (!row) return;
      const identity = audioIdentity(audio);
      const ready = manifestLoaded && isReady(identity);
      row.dataset.f3VoiceState = ready ? 'ready' : 'pending';
      row.dataset.f3ArticleId = identity?.id || '';
      const button = ensurePendingButton(row);
      button.textContent = PENDING;
      button.disabled = true;
      if (ready) {
        audio.hidden = false;
        button.hidden = true;
        button.style.display = 'none';
      } else {
        try { audio.pause(); } catch (_) {}
        audio.hidden = true;
        button.hidden = false;
        button.style.display = '';
      }
    });

    $$('.audio-row .audio-btn:not(.f3-pending-button)').forEach(button => {
      const row = button.closest('.audio-row');
      if (!row || $('.synced-audio', row)) return;
      row.dataset.f3VoiceState = 'pending';
      button.disabled = true;
      button.textContent = PENDING;
      button.title = 'Supertonic 3 F3 の日本語ニュース音声を生成中です。';
    });
    render();
  }

  function visibleSnapshot() {
    const rows = $$('.audio-row[data-f3-voice-state]');
    if (!rows.length) return null;
    const ready = rows.filter(row => row.dataset.f3VoiceState === 'ready').length;
    const total = rows.length;
    return { done: ready, total, pending: Math.max(0, total - ready), percent: total ? ready / total * 100 : 0 };
  }

  function manifestSnapshot() {
    let total = 0;
    let done = 0;
    wanted.daily.forEach(id => { total += 1; if (Object.prototype.hasOwnProperty.call(mainManifest, `daily:${id}`)) done += 1; });
    wanted.live.forEach(id => { total += 1; if (Object.prototype.hasOwnProperty.call(mainManifest, `live:${id}`)) done += 1; });
    wanted.rolling.forEach(id => { total += 1; if (Object.prototype.hasOwnProperty.call(rollingManifest, id)) done += 1; });
    return { done, total, pending: Math.max(0, total - done), percent: total ? done / total * 100 : 0 };
  }

  function runState() {
    const active = latestRuns.find(run => ACTIVE.has(run?.status));
    if (active) return active.status === 'in_progress'
      ? { state: 'active', label: 'Supertonic 3 F3 worker active' }
      : { state: 'queued', label: 'Supertonic 3 F3 worker queued / starting' };
    const run = latestRuns[0];
    if (!run) return { state: 'unknown', label: 'Checking Supertonic 3 F3 workers' };
    if (run.status === 'completed' && run.conclusion === 'success') return { state: 'idle', label: 'Latest Supertonic 3 F3 worker run completed' };
    if (run.status === 'completed' && run.conclusion === 'cancelled') return { state: 'queued', label: 'Previous F3 run replaced; next run pending' };
    if (run.status === 'completed' && run.conclusion) return { state: 'failed', label: `Supertonic 3 F3 worker ${run.conclusion}` };
    return { state: 'unknown', label: run.status || 'Checking Supertonic 3 F3 workers' };
  }

  function ensureSystemRow() {
    const panel = $('#system-status-panel');
    if (!panel) return null;
    let row = $('#voice-production-status-row');
    if (row) return row;
    ensureStyles();
    row = document.createElement('div');
    row.id = 'voice-production-status-row';
    row.className = 'system-panel-row status-check voice-production-row';
    row.innerHTML = `<span class="status-dot" aria-hidden="true"></span><div class="voice-production-copy"><div class="voice-progress-top"><strong>Voice Creation</strong><span class="voice-progress-percent">—</span></div><div class="voice-progress-track" role="progressbar" aria-label="Supertonic 3 F3 Japanese voice production and visible playback progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span class="voice-progress-fill"></span></div><small class="voice-progress-stats"><span class="voice-done">Playable —/— visible</span><span class="voice-creating">Manifest —/— · Creating —/— pending</span></small><small class="voice-progress-detail">Supertonic 3 F3 の生成状況を確認中…</small></div>`;
    const audioRow = $('#status-audio');
    if (audioRow) audioRow.insertAdjacentElement('afterend', row);
    else panel.appendChild(row);
    return row;
  }

  function render() {
    const row = ensureSystemRow();
    if (!row) return;
    const global = manifestSnapshot();
    const visible = visibleSnapshot();
    const shown = visible?.total ? visible : global;
    const workflow = runState();
    let state = workflow.state;
    let label = workflow.label;

    if (!manifestLoaded) {
      state = 'queued';
      label = 'F3 manifestを確認中';
    } else if (visible?.pending > 0) {
      state = workflow.state === 'active' ? 'active' : 'queued';
      label = `${visible.pending} visible article voice${visible.pending === 1 ? '' : 's'} not playable yet`;
    } else if (global.total > 0 && global.pending === 0) {
      state = 'complete';
      label = visible ? 'Visible page playable · current manifest snapshot complete' : 'Current manifest snapshot complete';
    } else if (global.pending > 0 && workflow.state === 'idle') {
      state = 'queued';
      label = 'Current F3 manifest backlog remains · automatic continuation enabled';
    }

    row.classList.remove('status-ok', 'status-check', 'status-warn', 'status-fail');
    row.classList.add(state === 'complete' || state === 'active' ? 'status-ok' : state === 'failed' ? 'status-fail' : 'status-warn');
    const percent = Number.isFinite(shown.percent) ? shown.percent : 0;
    $('.voice-progress-percent', row).textContent = `${percent.toFixed(1)}%`;
    $('.voice-progress-track', row)?.setAttribute('aria-valuenow', percent.toFixed(1));
    $('.voice-progress-fill', row).style.width = `${percent.toFixed(2)}%`;
    $('.voice-done', row).textContent = visible?.total ? `Playable ${visible.done}/${visible.total} visible` : `Playable ${global.done}/${global.total} current`;
    const creating = workflow.state === 'active' ? Math.min(MAX_PARALLEL, global.pending) : 0;
    $('.voice-creating', row).textContent = `Manifest ${global.done}/${global.total} · Creating ${creating}/${global.pending} pending`;
    $('.voice-progress-detail', row).textContent = `${label} · Supertonic 3 F3 · Japanese TV-news reporter tone · Last voice ${lastVoice}`;
  }

  async function loadManifests() {
    const [main, rolling] = await Promise.all([
      fetchJson(MAIN_MANIFEST, true),
      fetchJson(ROLLING_MANIFEST, true),
    ]);
    mainManifest = main && typeof main === 'object' && !Array.isArray(main) ? main : {};
    rollingManifest = rolling && typeof rolling === 'object' && !Array.isArray(rolling) ? rolling : {};
    manifestLoaded = true;
    configureVisibleVoices();
  }

  async function loadWorkflow() {
    const data = await fetchJson(WORKFLOW_API, true);
    latestRuns = Array.isArray(data?.workflow_runs) ? data.workflow_runs : [];
    render();
  }

  function commitDate(payload) {
    const first = Array.isArray(payload) ? payload[0] : null;
    return String(first?.commit?.committer?.date || first?.commit?.author?.date || '').trim();
  }

  async function loadLastVoice() {
    const [main, rolling] = await Promise.all([
      fetchJson(MAIN_MANIFEST_COMMITS, true),
      fetchJson(ROLLING_MANIFEST_COMMITS, true),
    ]);
    const dates = [commitDate(main), commitDate(rolling)].filter(Boolean).sort();
    if (dates.length) lastVoice = dates[dates.length - 1];
    render();
  }

  function queueVisibleRefresh() {
    if (refreshQueued) return;
    refreshQueued = true;
    (window.requestAnimationFrame || (callback => setTimeout(callback, 0)))(() => {
      refreshQueued = false;
      if (manifestLoaded) configureVisibleVoices();
    });
  }

  function boot() {
    ensureStyles();
    ensureSystemRow();
    loadWanted();
    loadManifests();
    loadWorkflow();
    loadLastVoice();
    setInterval(loadManifests, MANIFEST_REFRESH_MS);
    setInterval(loadWorkflow, WORKFLOW_REFRESH_MS);
    setInterval(loadWanted, WORKFLOW_REFRESH_MS);
    setInterval(loadLastVoice, LAST_VOICE_REFRESH_MS);
    new MutationObserver(queueVisibleRefresh).observe(document.body, { childList: true, subtree: true });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        loadWanted();
        loadManifests();
        loadWorkflow();
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
