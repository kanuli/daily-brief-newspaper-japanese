(() => {
  'use strict';

  const ERROR_RE = /(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)/i;
  const CHINESE_PROSE_RE = /(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|白禮頓|阿士東|維拉)/;
  const HIRA_RE = /[\u3040-\u309f]/;
  const HAN_RE = /[\u3400-\u9fff]/;
  const CRITICAL_FIELDS = ['title','dek','summary','body','context','why','watchNext','timeLabel'];

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
      ['dek','summary','body','context','why','watchNext'].some(key => mixedProse(item[key]));
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

  function sanitizeRendered(itemsById = new Map(), liveData = null) {
    const updated = document.getElementById('live-updated');
    if (updated && (badError(updated.textContent) || !updated.textContent.trim() || updated.textContent.trim() === '—')) {
      updated.textContent = formatUpdated(liveData?.lastUpdated);
    }

    document.querySelectorAll('.live-card').forEach(card => {
      const audio = card.querySelector('.synced-audio');
      const id = audio?.dataset?.syncArticle || '';
      const item = id ? itemsById.get(id) : null;
      const title = card.querySelector('h3');
      const summary = card.querySelector('p');

      if (title && badError(title.textContent)) title.textContent = '翻訳を再処理中';
      if (summary && (badError(summary.textContent) || mixedProse(summary.textContent))) summary.textContent = '翻訳を再処理中です。次の同期後に自動更新されます。';

      if (item && unsafeItem(item)) {
        const block = card.querySelector('.audio-block, .audio-row');
        if (block) block.innerHTML = '<button class="audio-btn" disabled>音声再生成中</button><span class="audio-note">翻訳検証後にSupertonic 3 F3音声を再公開します</span>';
      }
    });
  }

  async function bootGuard() {
    setNextPublication();
    setInterval(setNextPublication, 30000);

    const target = document.getElementById('live-items');
    let data = null;
    let map = new Map();
    try {
      const r = await fetch(`data/live.json?integrity=${Date.now()}`, {cache:'no-store'});
      if (r.ok) {
        data = await r.json();
        map = new Map((Array.isArray(data?.items) ? data.items : []).map(item => [String(item.id || ''), item]));
      }
    } catch (err) {
      console.warn('live integrity guard data check failed', err);
    }

    const run = () => sanitizeRendered(map, data);
    run();
    if (target) {
      const observer = new MutationObserver(run);
      observer.observe(target, {childList:true, subtree:true, characterData:true});
    }
    const updated = document.getElementById('live-updated');
    if (updated) {
      const observer = new MutationObserver(run);
      observer.observe(updated, {childList:true, subtree:true, characterData:true});
    }
    setTimeout(run, 400);
    setTimeout(run, 1500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootGuard, {once:true});
  else bootGuard();
})();
