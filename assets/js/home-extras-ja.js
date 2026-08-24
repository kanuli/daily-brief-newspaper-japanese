(() => {
  "use strict";

  let topAudio = null, topButton = null;

  async function json(url, cache = "no-store") {
    const response = await fetch(url, { cache });
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json();
  }

  function statusLabel(item) {
    const raw = String(item?.status || "UPDATED").toUpperCase();
    return item?.statusLabel || ({ NEW: "新着", UPDATED: "更新", DEVELOPING: "続報", BREAKING: "速報", WATCHING: "注視" }[raw] || "更新");
  }

  function liveBadge(item) {
    const raw = String(item?.status || "UPDATED").toUpperCase();
    return `<span class="live-badge live-${esc(raw.toLowerCase())}">${esc(statusLabel(item))}</span>`;
  }

  function renderLiveSummary(data) {
    const host = document.querySelector("#live-summary");
    if (!host) return;
    const items = (data.items || []).slice(0, 4);
    const counts = (data.items || []).reduce((out, item) => {
      const key = String(item.status || "").toUpperCase();
      if (key in out) out[key] += 1;
      return out;
    }, { NEW: 0, UPDATED: 0, DEVELOPING: 0 });
    host.innerHTML = `<div class="live-summary-head"><div><div class="live-kicker"><span class="live-dot"></span> LIVE UPDATE</div><h2>最新ニュース更新</h2><p>最終更新 ${esc(data.lastUpdatedLabel || "—")} ・ ${esc(data.nextUpdateLabel || "")}</p></div><div class="live-counts"><span><strong>${counts.NEW}</strong>NEW</span><span><strong>${counts.UPDATED}</strong>UPDATED</span><span><strong>${counts.DEVELOPING}</strong>DEVELOPING</span></div></div><div class="live-summary-grid">${items.length ? items.map((item) => `<article class="live-mini-card"><div>${liveBadge(item)} <span class="live-time">${esc(item.timeLabel || "")}</span></div><h3>${ruby(item, "title", item.title || "")}</h3><p>${ruby(item, "summary", item.summary || "")}</p></article>`).join("") : `<p class="notice">現在表示できる速報はありません。次回の確認は予定どおり続行します。</p>`}</div><div class="live-more"><a href="live.html">完全なLive Updateを見る →</a></div>`;
  }

  function stopTopAudio() {
    if (topAudio) {
      try { topAudio.pause(); topAudio.currentTime = 0; } catch (_) {}
      topAudio = null;
    }
    if (topButton) {
      topButton.classList.remove("is-playing");
      topButton.textContent = "🔊 日本語朗読";
      topButton = null;
    }
  }

  function waitForDailyRender(callback, tries = 80) {
    const lead = document.querySelector("#lead-story h2");
    const top = document.querySelector("#top-five .top-card");
    if (lead && top) { callback(); return; }
    if (tries > 0) window.setTimeout(() => waitForDailyRender(callback, tries - 1), 100);
  }

  function addLeadMedia(data) {
    const articles = Array.isArray(data.articles) ? data.articles : [];
    const story = articles.find((item) => item.id === data.leadId) || articles[0];
    const host = document.querySelector("#lead-story");
    if (!story || !host || host.querySelector(".media-frame")) return;
    const figure = document.createElement("figure");
    figure.className = "media-frame";
    figure.dataset.label = story.section || "DAILY BRIEF";
    const image = story.image ? `<img src="${esc(story.image)}" alt="${esc(story.imageAlt || story.title || "")}" loading="eager">` : "";
    const caption = story.imageCaption ? esc(story.imageCaption) : "ニュース画像枠：公式配布または合法的に再利用できる画像のみ表示します。";
    figure.innerHTML = `${image}<figcaption>${caption}</figcaption>`;
    const anchor = host.querySelector(".story-meta") || host.querySelector(".audio-block") || null;
    host.insertBefore(figure, anchor);
  }

  function playTopStory(button) {
    const src = button.dataset.audio || "";
    if (!src) return;
    if (topButton === button && topAudio && !topAudio.paused) { stopTopAudio(); return; }
    stopTopAudio();
    topButton = button;
    topAudio = new Audio(src);
    button.classList.add("is-playing");
    button.textContent = "■ 停止";
    topAudio.onended = stopTopAudio;
    topAudio.onerror = stopTopAudio;
    topAudio.play().catch((error) => { console.warn("Top Five F3 audio unavailable", error); stopTopAudio(); });
  }

  function addTopFiveAudio(data) {
    const articles = Array.isArray(data.articles) ? data.articles : [];
    const ids = Array.isArray(data.topFive) && data.topFive.length ? data.topFive : articles.slice(0, 5).map((item) => item.id);
    const cards = [...document.querySelectorAll("#top-five .top-card")];
    cards.forEach((card, index) => {
      if (card.querySelector(".top-audio-btn")) return;
      const story = articles.find((item) => item.id === ids[index]);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "top-audio-btn";
      if (story?.audio) {
        button.dataset.audio = story.audio;
        button.textContent = "🔊 日本語朗読";
        button.title = "Supertonic 3 F3 日本語ニュース朗読";
        button.addEventListener("click", () => playTopStory(button));
      } else {
        button.textContent = "音声準備中";
        button.disabled = true;
      }
      card.appendChild(button);
    });
  }

  function decorateDaily(data) {
    waitForDailyRender(() => { addLeadMedia(data); addTopFiveAudio(data); });
  }

  async function init() {
    const tasks = [];
    if (document.querySelector("#lead-story")) tasks.push(json("data/latest.json").then(decorateDaily).catch((error) => console.warn("Daily parity extras unavailable", error)));
    if (document.querySelector("#live-summary")) tasks.push(json("data/live.json").then(renderLiveSummary).catch((error) => console.warn("Home Live summary unavailable", error)));
    await Promise.all(tasks);
  }

  window.addEventListener("pagehide", stopTopAudio, { once: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
