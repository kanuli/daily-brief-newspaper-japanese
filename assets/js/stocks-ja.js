(() => {
  "use strict";

  const SAFE_LOWER = new Set(["vs","km","kg","cm","mm","ms","gb","tb","mb","kb","fps","bps","kbps","mbps","gbps","app","apps","web","live","online","email","alpha","beta","http","https","www","com","org","net"]);
  const assetLabel = (value) => ({ EQUITY: "株式", ETF: "ETF" }[String(value || "").toUpperCase()] || value || "証券");
  const impactClass = (value) => value === "↑" ? "stock-impact-up" : value === "↓" ? "stock-impact-down" : "stock-impact-neutral";

  function corruptText(value = "") {
    const text = String(value || "");
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
    return lower.some(word => !SAFE_LOWER.has(word.toLowerCase()));
  }

  function corruptStory(story = {}) {
    return ["title","dek","summary","body","context","why","watchNext","timeLabel","impactLabel"]
      .some(field => corruptText(story?.[field]));
  }

  async function optionalJson(path) {
    try { return await getJson(path); } catch (error) { console.warn("optional stock layer unavailable", path, error); return null; }
  }

  function sourceMarkup(story) {
    const sources = Array.isArray(story.sources) && story.sources.length ? story.sources : (story.sourceUrl ? [{ name: story.sourceName || "原文", url: story.sourceUrl }] : []);
    if (!sources.length) return "";
    return `<div class="stock-sources"><strong>確認済み情報源：</strong> ${sources.map((item) => `<a href="${esc(item.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(item.name || "原文")} ↗</a>`).join(" ・ ")}</div>`;
  }

  function bodyMarkup(story) {
    const parts = rubyBodyParagraphs(story);
    return parts.length ? `<div class="stock-story-body">${parts.map((part, index) => `<p>${syncSpan(story, `body-${index}`, part)}</p>`).join("")}</div>` : "";
  }

  function infoCard(label, story, field) {
    const value = story?.[field];
    if (!value) return "";
    const key = field === "watchNext" ? "watch" : field;
    return `<div class="stock-info-card"><strong>${label}</strong><p>${syncSpan(story, key, ruby(story, field, value))}</p></div>`;
  }

  function storyMarkup(story, featured) {
    return `<article class="stock-story ${featured ? "featured" : ""}">
      <div><span class="stock-impact ${impactClass(story.impact)}">${esc(story.impact || "↔")} ${esc(story.impactLabel || "")}</span><span class="story-meta">${esc(story.storyType || "")}</span></div>
      <h2>${syncSpan(story, "title", ruby(story, "title", story.title || ""))}</h2>
      ${story.dek ? `<p class="stock-story-dek">${syncSpan(story, "dek", ruby(story, "dek", story.dek))}</p>` : ""}
      ${story.summary ? `<p class="stock-summary">${ruby(story, "summary", story.summary)}</p>` : ""}
      ${audio(story)}
      ${bodyMarkup(story)}
      <div class="stock-info-grid stock-info-grid-three">${infoCard("背景", story, "context")}${infoCard("重要な理由", story, "why")}${infoCard("今後の注目", story, "watchNext")}</div>
      <div class="stock-story-meta">${esc(story.timeLabel || "")} ${story.sourceName ? `・ ${esc(story.sourceName)}` : ""}</div>
      ${sourceMarkup(story)}
    </article>`;
  }

  function normalizeFallback(daily) {
    const stories = (daily.articles || []).filter((article) => deskOf(article) === "stocks" && !corruptStory(article));
    return {
      lastUpdatedLabel: daily.dateLabel || daily.date || "",
      tracked: ["MARKET"],
      tickers: { MARKET: { name: "Daily Edition 株式ニュース", assetType: "EQUITY", stories } }
    };
  }

  function render(data) {
    const tracked = Array.isArray(data.tracked) && data.tracked.length ? data.tracked : Object.keys(data.tickers || {});
    const nav = document.querySelector("#stock-ticker-nav");
    const updated = document.querySelector("#stock-updated");
    const sections = document.querySelector("#stock-sections");
    document.title = "株式ニュース｜日刊速報 Daily Brief";
    if (updated) updated.textContent = data.lastUpdatedLabel || data.generatedAt || "—";
    if (nav) nav.innerHTML = tracked.map((ticker) => `<a href="#stock-${esc(ticker.toLowerCase())}">${esc(ticker)}</a>`).join("");
    if (!sections) return;
    sections.innerHTML = tracked.map((ticker) => {
      const info = data.tickers?.[ticker] || {};
      const stories = (Array.isArray(info.stories) ? info.stories : []).filter((story) => {
        if (!corruptStory(story)) return true;
        console.error("QUARANTINED_GARBLED_STOCK_STORY", ticker, story?.id || "");
        return false;
      });
      return `<section class="stock-section" id="stock-${esc(ticker.toLowerCase())}"><div class="stock-section-head"><div><div class="stock-symbol">${esc(ticker)}</div><div class="stock-name">${esc(info.name || "")}</div></div><div class="stock-asset-type">${esc(assetLabel(info.assetType))}</div></div>${stories.length ? stories.map((story, index) => storyMarkup(story, index === 0)).join("") : `<p class="stock-empty">現在、この銘柄について掲載できる確認済みニュースはありません。</p>`}</section>`;
    }).join("");
    initAudioSync();
  }

  async function init() {
    let data = await optionalJson("data/stocks-latest.json");
    if (!data) data = normalizeFallback(await getJson("data/latest.json"));
    render(data);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init().catch(console.error), { once: true });
  else init().catch(console.error);
})();
