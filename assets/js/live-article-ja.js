(() => {
  "use strict";

  const LIVE_JSON = "data/live.json";
  const REFRESH_MS = 60 * 1000;
  let refreshTimer = null;
  let lastKey = "";

  const badge = (item) => {
    const raw = String(item?.status || "UPDATED").toUpperCase();
    const label = item?.statusLabel || (typeof liveStatus === "function" ? liveStatus(item) : raw);
    return `<span class="live-badge live-${esc(raw.toLowerCase())}">${esc(label)}</span>`;
  };

  function paragraph(label, item, field, className) {
    const value = item?.[field];
    if (!value) return "";
    const key = field === "watchNext" ? "watch" : field;
    return `<p class="${className}"><strong>${label}</strong>${syncSpan(item, key, ruby(item, field, value))}</p>`;
  }

  function sourceMarkup(item) {
    const sources = Array.isArray(item.sources) && item.sources.length
      ? item.sources
      : (item.sourceUrl ? [{ name: item.sourceName || "原文", url: item.sourceUrl }] : []);
    if (!sources.length) return "";
    return `<div class="article-sources"><strong>確認済み情報源：</strong> ${sources.map((sourceItem) => `<a class="source-link" href="${esc(sourceItem.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(sourceItem.name || "原文")} ↗</a>`).join(" ・ ")}</div>`;
  }

  function bodyMarkup(item) {
    const parts = rubyBodyParagraphs(item);
    if (!parts.length) return "";
    return `<div class="live-body-main">${parts.map((part, index) => `<p>${syncSpan(item, `body-${index}`, part)}</p>`).join("")}</div>`;
  }

  function renderStory(item) {
    return `<article class="live-story live-story-rich">
      <div class="live-story-meta">${badge(item)} <span>${ruby(item, "section", item.section || "速報")}</span> <span>${esc(item.timeLabel || "")}</span></div>
      <h2>${syncSpan(item, "title", ruby(item, "title", item.title || ""))}</h2>
      ${item.dek ? `<p class="live-article-dek">${syncSpan(item, "dek", ruby(item, "dek", item.dek))}</p>` : ""}
      ${audio(item)}
      <div class="live-article-body">
        ${item.summary ? paragraph("要約：", item, "summary", "live-article-summary") : ""}
        ${bodyMarkup(item)}
        ${paragraph("背景：", item, "context", "live-article-context")}
        ${paragraph("重要な理由：", item, "why", "live-article-why")}
        ${paragraph("今後の注目：", item, "watchNext", "live-article-next")}
      </div>
      ${sourceMarkup(item)}
    </article>`;
  }

  function keyFor(data) {
    return [data?.lastUpdated || "", data?.windowLabel || "", (data?.items || []).map((item) => `${item.id}:${item.status}`).join("|")].join("::");
  }

  function render(data) {
    const host = document.querySelector("#live-items");
    if (!host) return;
    const items = Array.isArray(data.items) ? data.items : [];
    const actual = items.reduce((counts, item) => {
      const key = String(item.status || "").toUpperCase();
      if (key in counts) counts[key] += 1;
      return counts;
    }, { NEW: 0, UPDATED: 0, DEVELOPING: 0 });

    document.querySelectorAll("#live-header-time, #live-updated").forEach((el) => {
      el.textContent = data.lastUpdatedLabel || data.windowLabel || "速報";
    });

    const stats = document.querySelector("#live-page-stats");
    if (stats) {
      stats.innerHTML = `<div><strong>${actual.NEW}</strong><span>NEW</span></div><div><strong>${actual.UPDATED}</strong><span>UPDATED</span></div><div><strong>${actual.DEVELOPING}</strong><span>DEVELOPING</span></div><p>${esc(data.nextUpdateLabel || "")}</p>`;
    }

    const coverage = data.coverage || {};
    const audit = document.querySelector("#live-audit");
    if (audit) {
      const sourceCount = Number(coverage.sourceOrganizationCount || 0);
      const searchCount = Number(coverage.freshSearchCount || 0);
      const rawCount = Number(coverage.rawFreshCandidateCount || 0);
      const verifiedCount = Number(coverage.verifiedCandidateCount || 0);
      const incrementalCount = Number(coverage.incrementalCandidateCount || 0);
      audit.innerHTML = sourceCount || searchCount || rawCount || verifiedCount || incrementalCount
        ? `<strong>最新収集：</strong>${sourceCount}ニュース機関 ・ fresh searches ${searchCount} ・ raw ${rawCount} ・ verified ${verifiedCount} ・ incremental ${incrementalCount}`
        : `<strong>最新発行：</strong>${esc(data.lastUpdatedLabel || data.windowLabel || "更新済み")}`;
    }

    host.innerHTML = items.length
      ? items.map(renderStory).join("")
      : `<p class="notice">この時間帯の速報をまだ読み込めません。システムは最新のLive publicationを自動的に再取得します。</p>`;
    initAudioSync();
  }

  async function refresh({ force = false } = {}) {
    try {
      const url = new URL(LIVE_JSON, document.baseURI);
      url.searchParams.set("v", String(Date.now()));
      const response = await fetch(url.href, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const nextKey = keyFor(data);
      if (force || nextKey !== lastKey) {
        lastKey = nextKey;
        render(data);
      }
    } catch (error) {
      console.error("Japanese Live refresh failed", error);
      const audit = document.querySelector("#live-audit");
      if (audit) audit.textContent = "Liveデータを一時的に読み込めません。自動的に再試行します。";
    }
  }

  function start() {
    if (refreshTimer) window.clearInterval(refreshTimer);
    refresh({ force: true });
    refreshTimer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") refresh({ force: true });
    });
    window.addEventListener("pageshow", () => refresh({ force: true }));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
