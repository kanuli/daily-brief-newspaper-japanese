(() => {
  'use strict';

  const ERROR_RE = /(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)/i;
  const CHINESE_PROSE_RE = /(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|白禮頓|阿士東|維拉)/;
  const HIRA_RE = /[\u3040-\u309f]/;
  const HAN_RE = /[\u3400-\u9fff]/;
  const CRITICAL_FIELDS = ['title','dek','summary','body','context','why','watchNext','timeLabel'];
  const PROSE_FIELDS = ['dek','summary','body','context','why','watchNext'];

  function badError(value='') {
    return ERROR_RE.test(String(value || ''));
  }

  function mixedProse(value='') {
    const text = String(value || '').trim();
    if (!text) return false;
    if (CHINESE_PROSE_RE.test(text)) return true;
    return text.length >= 28 && HAN_RE.test(text) && !HIRA_RE.test(text);
  }

  function unsafeItem(item={}) {
    return CRITICAL_FIELDS.some(key => badError(item[key])) ||
      PROSE_FIELDS.some(key => mixedProse(item[key]));
  }

  function hasErrorPayload(value) {
    if (typeof value === 'string') return badError(value);
    if (Array.isArray(value)) return value.some(hasErrorPayload);
    if (value && typeof value === 'object') return Object.values(value).some(hasErrorPayload);
    return false;
  }

  function hktParts(date = new Date()) {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Hong_Kong',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    }).formatToParts(date);
    return Object.fromEntries(parts.map(p => [p.type, p.value]));
  }

  function nextPublicationLabel() {
    const p = hktParts();
    const minutes = Number(p.hour) * 60 + Number(p.minute) + Number(p.second) / 60;
    // Same Live timetable as daily-brief-newspaper. 08:00 is the Daily Edition.
    const slots = [360, 420, 540, 600, 660, 720, 780, 840, 900, 960, 1020, 1080, 1140, 1200, 1260, 1320, 1380, 1440];
    const next = slots.find(v => v > minutes) ?? 360;
    if (next === 1440) return '24:00 HKT';
    const h = Math.floor(next / 60) % 24;
    return `${String(h).padStart(2,'0')}:00 HKT`;
  }

  function formatUpdated(value) {
    const date = new Date(value || '');
    if (Number.isNaN(date.getTime())) return '—';
    const p = hktParts(date);
    return `${p.year}年${Number(p.month)}月${Number(p.day)}日 ${p.hour}:${p.minute} HKT`;
  }

  function setNextPublication() {
    const node = document.getElementById('live-next-update');
    if (node) node.textContent = nextPublicationLabel();
  }

  function quarantineNotice() {
    const main = document.querySelector('main');
    if (!main || document.getElementById('integrity-quarantine-notice')) return;
    const notice = document.createElement('p');
    notice.id = 'integrity-quarantine-notice';
    notice.className = 'notice';
    notice.textContent = '一部の記事は翻訳検証中のため一時的に保護表示しています。エラー文字列や未検証音声は表示・再生しません。';
    main.insertBefore(notice, main.firstChild);
  }

  function disableAudio(container) {
    if (!container) return;
    container.querySelectorAll('.audio-block, .audio-row').forEach(block => {
      if (block.dataset.integrityBlocked === '1') return;
      block.dataset.integrityBlocked = '1';
      block.innerHTML = '<button class="audio-btn" disabled>音声再生成中</button><span class="audio-note">翻訳検証後にSupertonic 3 F3音声を再公開します</span>';
    });
  }

  function sanitizeTextNode(node, heading=false) {
    if (!node) return false;
    const text = String(node.textContent || '').trim();
    const unsafe = badError(text) || (!heading && mixedProse(text));
    if (!unsafe) return false;
    const replacement = heading ? '翻訳を再処理中' : '翻訳を再処理中です。次の同期後に自動更新されます。';
    if (node.textContent !== replacement) node.textContent = replacement;
    return true;
  }

  function articleId(container) {
    return container?.querySelector('.synced-audio')?.dataset?.syncArticle || '';
  }

  function sanitizeCards(unsafeIds = new Set()) {
    document.querySelectorAll('.lead-story,.story-card,.section-block,.live-card').forEach(card => {
      let changed = false;
      card.querySelectorAll('h2,h3').forEach(node => { if (sanitizeTextNode(node, true)) changed = true; });
      card.querySelectorAll('p,.lead-deck,.why-box,.watch-box').forEach(node => { if (sanitizeTextNode(node, false)) changed = true; });
      const id = articleId(card);
      if (changed || (id && unsafeIds.has(id))) disableAudio(card);
    });
  }

  function sanitizeLiveMetadata(data) {
    const updated = document.getElementById('live-updated');
    if (updated && (badError(updated.textContent) || !updated.textContent.trim() || updated.textContent.trim() === '—')) {
      updated.textContent = formatUpdated(data?.lastUpdated);
    }
    document.querySelectorAll('.live-time').forEach(node => {
      if (badError(node.textContent)) node.textContent = '更新時刻を再確認中';
    });
  }

  async function loadPublicationData() {
    const isLive = document.body?.dataset?.page === 'live';
    const path = isLive ? 'data/live.json' : 'data/latest.json';
    try {
      const r = await fetch(`${path}?integrity=${Date.now()}`, {cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch (err) {
      console.warn('publication integrity guard data check failed', err);
      return null;
    }
  }

  async function bootGuard() {
    setNextPublication();
    if (document.getElementById('live-next-update')) setInterval(setNextPublication, 30000);

    const data = await loadPublicationData();
    const items = document.body?.dataset?.page === 'live' ? (data?.items || []) : (data?.articles || []);
    const unsafeIds = new Set((Array.isArray(items) ? items : []).filter(unsafeItem).map(item => String(item.id || '')));
    const dirty = hasErrorPayload(data) || unsafeIds.size > 0;
    if (dirty) quarantineNotice();

    const run = () => {
      sanitizeCards(unsafeIds);
      sanitizeLiveMetadata(data);
      setNextPublication();
    };

    run();
    const main = document.querySelector('main');
    if (main) {
      const observer = new MutationObserver(run);
      observer.observe(main, {childList:true, subtree:true, characterData:true});
    }
    setTimeout(run, 300);
    setTimeout(run, 1200);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootGuard, {once:true});
  else bootGuard();
})();
