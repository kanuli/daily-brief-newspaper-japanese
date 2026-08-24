(() => {
  "use strict";

  const ST3_CATALOG = "https://raw.githubusercontent.com/kanuli/japanese-vocab-game/main/word-supertonic3-catalog.json";
  const ST3_F1_INDEX = "https://raw.githubusercontent.com/kanuli/japanese-vocab-game/main/word-supertonic3-F1-index.json";
  let catalogPromise = null, f1IndexPromise = null, activeAudio = null, activeBlobUrl = "", activeButton = null;
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

  function loadCatalog() { if (!catalogPromise) catalogPromise = json(ST3_CATALOG, "force-cache"); return catalogPromise; }
  function loadF1Index() { if (!f1IndexPromise) f1IndexPromise = json(ST3_F1_INDEX, "force-cache"); return f1IndexPromise; }

  function stopVocabAudio() {
    if (activeAudio) { try { activeAudio.pause(); activeAudio.currentTime = 0; } catch (_) {} activeAudio = null; }
    if (activeBlobUrl) { try { URL.revokeObjectURL(activeBlobUrl); } catch (_) {} activeBlobUrl = ""; }
    if (activeButton) { activeButton.disabled = false; activeButton.textContent = "🔊"; activeButton.classList.remove("is-playing", "is-loading"); activeButton = null; }
  }

  function stopTopAudio() {
    if (topAudio) { try { topAudio.pause(); topAudio.currentTime = 0; } catch (_) {} topAudio = null; }
    if (topButton) { topButton.classList.remove("is-playing"); topButton.textContent = "🔊 日本語朗読"; topButton = null; }
  }

  async function rangeBytes(bundle, offset, size) {
    const end = offset + size - 1;
    const urls = [bundle.githubUrl, bundle.hfUrl, bundle.url].filter(Boolean);
    let lastError = null;
    for (const url of urls) {
      try {
        const response = await fetch(url, { headers: { Range: `bytes=${offset}-${end}` }, cache: "force-cache" });
        const bytes = await response.arrayBuffer();
        if (response.status !== 206 && !(response.status === 200 && bytes.byteLength === size)) throw new Error(`Range HTTP ${response.status}`);
        if (bytes.byteLength !== size) throw new Error(`Range size ${bytes.byteLength}/${size}`);
        return bytes;
      } catch (error) { lastError = error; }
    }
    throw lastError || new Error("音声の読み込みに失敗しました");
  }

  async function playF1(button) {
    if (!button || button.disabled) return;
    const reading = button.dataset.reading || "";
    const kanji = button.dataset.kanji || "";
    if (!reading) return;
    stopVocabAudio(); activeButton = button; button.disabled = true; button.classList.add("is-loading"); button.textContent = "…";
    try {
      const [catalog, index] = await Promise.all([loadCatalog(), loadF1Index()]);
      const key = `${reading}|${kanji || reading}`;
      const lookup = catalog?.words?.[key];
      if (!lookup) throw new Error("この単語のF1録音はまだありません");
      const [memberId, shard] = lookup;
      const bundle = index?.bundles?.[String(shard)];
      const member = bundle?.members?.[memberId];
      if (!bundle || !member) throw new Error("F1音声インデックスが見つかりません");
      const bytes = await rangeBytes(bundle, Number(member[0]), Number(member[1]));
      activeBlobUrl = URL.createObjectURL(new Blob([bytes], { type: "audio/mpeg" }));
      const player = activeAudio = new Audio(activeBlobUrl);
      button.classList.remove("is-loading"); button.classList.add("is-playing"); button.textContent = "■";
      player.onended = stopVocabAudio; player.onerror = stopVocabAudio; await player.play();
    } catch (error) {
      console.warn("F1 vocabulary audio unavailable", error);
      if (activeButton === button) { button.classList.remove("is-loading", "is-playing"); button.textContent = "⚠"; button.title = error?.message || "音声を利用できません"; button.disabled = false; activeButton = null; }
    }
  }

  function renderVocab(data) {
    const host = document.querySelector("#study-desk");
    if (!host) return;
    const levels = ["N1", "N2", "N3", "N4", "N5"];
    const groups = levels.map((level) => ({ level, words: (data.words || []).filter((word) => word.level === level).slice(0, 2) }));
    host.className = "daily-vocab";
    host.innerHTML = `<div class="section-heading daily-vocab-heading"><h2>きょうの日本語10語</h2><span>N1–N5 ・ 各レベル2語</span></div><p class="daily-vocab-intro">広東語版と同じ毎日の語彙セットを日本語表示へ同期しています。🔊でSupertonic 3 F1の録音発音を再生できます。</p><div class="vocab-level-grid">${groups.map((group) => `<section class="vocab-level-block"><div class="vocab-level-title">${group.level}</div>${group.words.length ? group.words.map((word) => `<article class="vocab-card"><div class="vocab-card-head"><div><div class="vocab-reading">${esc(word.reading || "")}</div><div class="vocab-kanji">${esc(word.kanji || word.reading || "")}</div></div><button class="vocab-play" type="button" data-reading="${esc(word.reading || "")}" data-kanji="${esc(word.kanji || "")}" title="Supertonic 3 F1 発音">🔊</button></div><div class="vocab-meaning">${esc(word.meaning || "")}</div><div class="vocab-pos">${esc(word.partOfSpeech || "")}</div></article>`).join("") : `<p class="vocab-missing">このレベルの有効な語彙をまだ取得できません。</p>`}</section>`).join("")}</div><div class="vocab-source-note"><span>${esc(data.levelNote || "一部のJLPTレベルは推定です。")} ・ Voice: Supertonic 3 F1</span><a href="${esc(data.sourceUrl || "https://github.com/kanuli/daily-brief-newspaper")}" target="_blank" rel="noopener noreferrer">語彙ソースを見る ↗</a></div>`;
    host.addEventListener("click", (event) => { const button = event.target.closest(".vocab-play"); if (button) playF1(button); });
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
    stopVocabAudio();
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
    if (document.querySelector("#study-desk")) tasks.push(json("data/vocab/latest.json").then(renderVocab).catch((error) => {
      console.warn("Japanese daily vocab unavailable", error);
      const host = document.querySelector("#study-desk");
      if (host) { host.className = "daily-vocab"; host.innerHTML = `<div class="section-heading"><h2>きょうの日本語10語</h2><span>同期準備中</span></div><p class="notice">次回のニュース同期で広東語版と同じ10語を日本語化して表示します。</p>`; }
    }));
    await Promise.all(tasks);
  }

  window.addEventListener("pagehide", () => { stopVocabAudio(); stopTopAudio(); }, { once: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
