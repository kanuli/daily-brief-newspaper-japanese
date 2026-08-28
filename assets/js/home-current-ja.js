(() => {
  "use strict";

  const DESK_ORDER = [
    "world", "asia", "hong-kong", "japan", "market-economy",
    "ai-tech", "manga-anime", "manchester-united", "football"
  ];

  const DESK_LABELS = {
    world: ["世界", "最新の世界ニュース"],
    asia: ["アジア", "最新のアジアニュース"],
    "hong-kong": ["香港", "最新の香港ニュース"],
    japan: ["日本", "最新の日本ニュース"],
    "market-economy": ["経済・世界市場", "最新の経済・市場ニュース"],
    "ai-tech": ["AI・テクノロジー", "最新のAI・テクノロジーニュース"],
    "manga-anime": ["漫画・アニメ", "最新の漫画・アニメニュース"],
    "manchester-united": ["マンチェスター・ユナイテッド", "最新のクラブニュース"],
    football: ["サッカー", "最新のサッカーニュース"]
  };

  function stamp(payload) {
    const values = [payload?.generatedAt, payload?.lastUpdated, payload?.sourceGeneratedAt, payload?.checkedAt];
    for (const value of values) {
      const ms = Date.parse(String(value || ""));
      if (Number.isFinite(ms)) return ms;
    }
    const day = String(payload?.date || "").slice(0, 10);
    const ms = Date.parse(`${day}T08:00:00+08:00`);
    return Number.isFinite(ms) ? ms : 0;
  }

  async function getJson(path) {
    const response = await fetch(`${path}?home_current=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  }

  function uniqueStories(items) {
    const out = [];
    const seen = new Set();
    for (const item of items) {
      if (!item || !item.id || seen.has(item.id)) continue;
      seen.add(item.id);
      out.push(item);
    }
    return out;
  }

  function deskStories(payload) {
    if (!payload?.desks || typeof payload.desks !== "object") return [];
    return uniqueStories(Object.values(payload.desks).flatMap((value) => Array.isArray(value) ? value : []));
  }

  function liveStories(payload) {
    return Array.isArray(payload?.items) ? payload.items : [];
  }

  function dailyStories(payload) {
    return Array.isArray(payload?.articles) ? payload.articles : [];
  }

  function setCurrentMeta(daily, live, freshestStamp) {
    const dateNodes = document.querySelectorAll("[data-edition-date]");
    const liveLabel = live?.lastUpdatedLabel || live?.lastUpdated || "";
    const dailyLabel = daily?.dateLabel || daily?.date || "";
    const label = liveLabel && stamp(live) === freshestStamp
      ? `最新更新 ${liveLabel}｜Daily ${dailyLabel}`
      : dailyLabel;
    dateNodes.forEach((node) => { node.textContent = label; });
  }

  function currentLead(daily, live, desk, freshestStamp) {
    const candidates = [];
    if (stamp(live) >= freshestStamp - 60 * 60 * 1000) candidates.push(...liveStories(live));
    if (stamp(desk) >= freshestStamp - 60 * 60 * 1000) candidates.push(...deskStories(desk));
    if (candidates.length) return uniqueStories(candidates)[0];
    const dailyList = dailyStories(daily);
    return dailyList.find((item) => item.id === daily?.leadId) || dailyList[0] || null;
  }

  function renderLead(story, live, freshestStamp) {
    const host = document.querySelector("#lead-story");
    if (!host || !story || typeof fullArticle !== "function") return;
    host.innerHTML = fullArticle(story, true);
    const eyebrow = host.querySelector(".eyebrow");
    if (eyebrow && stamp(live) >= freshestStamp - 60 * 60 * 1000 && liveStories(live).some((item) => item.id === story.id)) {
      eyebrow.insertAdjacentHTML("afterbegin", '<span class="live-badge live-new">最新</span> ');
    }
  }

  function renderTopFive(daily, live, desk, freshestStamp) {
    const host = document.querySelector("#top-five");
    if (!host) return;
    const dailyList = dailyStories(daily);
    const dailyIds = Array.isArray(daily?.topFive) ? daily.topFive : [];
    const dailyTop = dailyIds.map((id) => dailyList.find((item) => item.id === id)).filter(Boolean);
    const fresh = [];
    if (stamp(live) >= freshestStamp - 60 * 60 * 1000) fresh.push(...liveStories(live));
    if (stamp(desk) >= freshestStamp - 60 * 60 * 1000) fresh.push(...deskStories(desk));
    const top = uniqueStories([...fresh, ...dailyTop, ...dailyList]).slice(0, 5);
    host.innerHTML = top.map((story) => `<article class="top-card"><h3>${ruby(story, "title", story.title || "")}</h3><p>${ruby(story, story.dek ? "dek" : "summary", story.dek || story.summary || "")}</p></article>`).join("");
  }

  function renderSections(daily, live, desk, freshestStamp) {
    const host = document.querySelector("#dynamic-sections");
    if (!host || typeof card !== "function" || typeof deskOf !== "function") return;

    const fresh = [];
    if (stamp(live) >= freshestStamp - 60 * 60 * 1000) fresh.push(...liveStories(live));
    if (stamp(desk) >= freshestStamp - 60 * 60 * 1000) fresh.push(...deskStories(desk));
    const merged = uniqueStories([...fresh, ...dailyStories(daily)]);

    const groups = new Map();
    for (const story of merged) {
      let key = deskOf(story);
      if (["technology", "science-new-tech", "cybersecurity", "software-apps"].includes(key)) key = "ai-tech";
      if (!DESK_LABELS[key]) continue;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(story);
    }

    host.innerHTML = DESK_ORDER.map((key) => {
      const stories = groups.get(key) || [];
      if (!stories.length) return "";
      const [title, subtitle] = DESK_LABELS[key];
      return `<section class="section-block" id="home-${key}"><div class="section-heading"><h2>${uiRuby(title)}</h2><span>${subtitle}</span></div><div class="story-grid">${stories.slice(0, 4).map(card).join("")}</div></section>`;
    }).join("");
  }

  async function refreshHomepage() {
    try {
      const [daily, live, desk] = await Promise.all([
        getJson("data/latest.json"),
        getJson("data/live.json").catch(() => null),
        getJson("data/desk-latest.json").catch(() => null)
      ]);

      const freshestStamp = Math.max(stamp(daily), stamp(live), stamp(desk));
      const lead = currentLead(daily, live, desk, freshestStamp);
      setCurrentMeta(daily, live, freshestStamp);
      renderLead(lead, live, freshestStamp);
      renderTopFive(daily, live, desk, freshestStamp);
      renderSections(daily, live, desk, freshestStamp);
      if (typeof initAudioSync === "function") initAudioSync();

      document.documentElement.dataset.homeFreshness = "current";
      document.documentElement.dataset.homePublicationStamp = String(freshestStamp);
    } catch (error) {
      console.error("Homepage current-news promotion failed", error);
      document.documentElement.dataset.homeFreshness = "degraded";
    }
  }

  function start() {
    // newspaper-ja.js and home-extras-ja.js render first; this layer is the final
    // editorial authority for what the reader sees on the front page.
    window.setTimeout(refreshHomepage, 250);
    window.setInterval(refreshHomepage, 5 * 60 * 1000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
