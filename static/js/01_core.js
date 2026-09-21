(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const tilesEl = $("#tiles");
  const tilesEmptyEl = $("#tilesEmpty");
  const lastUpdatedEl = $("#lastUpdated");
  const tableBody = $("#tableBody");
  const searchInput = $("#searchInput");
  const chartTitle = $("#chartTitle");
  const chartMeta = $("#chartMeta");
  const svg = $("#chart");
  const tooltip = $("#tooltip");

  const DEFAULT_WATCHLIST = ["2330", "2317", "2454"];
  const state = {
    watchlist: JSON.parse(localStorage.getItem("watchlist") || "null") || DEFAULT_WATCHLIST,
    quotes: {},          // code -> quote object
    allRows: [],          // parsed day_all rows
    chip: "volume",
    sortKey: null,
    sortDir: -1,
    selectedCode: null,
    selectedName: "",
    months: 3,
    dispositionSet: null,  // Set(code)，惰性載入
    attentionSet: null,    // Set(code)，惰性載入
    viewMode: "daily",     // "daily" | "intraday"
    showBollinger: false,
    selectedIsIndex: false,
    selectedIndexKey: null,
  };

  // ---------- helpers ----------
  function saveWatchlist() {
    localStorage.setItem("watchlist", JSON.stringify(state.watchlist));
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtNum(n, digits = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "-";
    return n.toLocaleString("zh-TW", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function fmtVolume(shares) {
    if (!shares && shares !== 0) return "-";
    return Math.round(shares / 1000).toLocaleString("zh-TW") + " 張";
  }

  function directionClass(v) {
    if (v > 0) return "up";
    if (v < 0) return "down";
    return "flat";
  }

  function directionArrow(v) {
    if (v > 0) return "▲";
    if (v < 0) return "▼";
    return "‒";
  }

  function setLastUpdated() {
    const now = new Date();
    lastUpdatedEl.textContent = "最後更新 " + now.toLocaleTimeString("zh-TW", { hour12: false });
  }

  // ---------- watchlist ----------
  function renderTiles() {
    tilesEl.innerHTML = "";
    tilesEmptyEl.style.display = state.watchlist.length ? "none" : "block";
    for (const code of state.watchlist) {
      const q = state.quotes[code];
      const tile = document.createElement("div");
      tile.className = "tile" + (state.selectedCode === code ? " selected" : "");
      tile.dataset.code = code;

      const codeEl = document.createElement("div");
      codeEl.className = "code";
      codeEl.textContent = code;

      const nameEl = document.createElement("div");
      nameEl.className = "name";
      nameEl.textContent = q ? q.name : "讀取中…";

      const priceEl = document.createElement("div");
      priceEl.className = "price";
      priceEl.textContent = q && q.price !== null ? fmtNum(q.price) : "-";

      const deltaEl = document.createElement("div");
      if (q && q.change !== null) {
        deltaEl.className = "delta " + directionClass(q.change);
        deltaEl.textContent = `${directionArrow(q.change)} ${fmtNum(Math.abs(q.change))} (${fmtNum(Math.abs(q.changePct))}%)`;
      } else {
        deltaEl.className = "delta flat";
        deltaEl.textContent = "-";
      }

      const rmBtn = document.createElement("button");
      rmBtn.className = "rm";
      rmBtn.textContent = "✕";
      rmBtn.title = "移除";
      rmBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.watchlist = state.watchlist.filter((c) => c !== code);
        saveWatchlist();
        renderTiles();
      });

      tile.append(codeEl, nameEl, priceEl, deltaEl, rmBtn);
      tile.addEventListener("click", () => selectStock(code, q ? q.name : code));
      tilesEl.appendChild(tile);
    }
  }

  async function refreshQuotes() {
    if (!state.watchlist.length) return;
    try {
      const res = await fetch("/api/quote?codes=" + encodeURIComponent(state.watchlist.join(",")));
      const data = await res.json();
      for (const q of data.quotes || []) {
        state.quotes[q.code] = q;
      }
      renderTiles();
      setLastUpdated();
    } catch (err) {
      console.error("refreshQuotes failed", err);
    }
  }

  const INDEX_ORDER = [
    { key: "taiex", short: "加權" },
    { key: "tpex", short: "櫃買" },
    { key: "sox", short: "費半" },
    { key: "txf", short: "台指期(夜盤)" },
    { key: "usdjpy", short: "美元/日圓" },
    { key: "usdtwd", short: "美元/台幣" },
  ];

  async function loadIndices() {
    try {
      const res = await fetch("/api/indices");
      const data = await res.json();
      const bar = $("#indicesBar");
      bar.innerHTML = "";
      for (const { key, short } of INDEX_ORDER) {
        const idx = data[key];
        if (!idx || idx.price == null) continue;
        const item = document.createElement("div");
        item.className = "idx-item";
        const nameEl = document.createElement("span");
        nameEl.className = "idx-name";
        nameEl.textContent = short;
        const priceEl = document.createElement("span");
        priceEl.className = "idx-price";
        priceEl.textContent = fmtNum(idx.price);
        const chgEl = document.createElement("span");
        chgEl.className = "idx-chg " + directionClass(idx.change_pct ?? 0);
        chgEl.textContent = idx.change_pct != null
          ? `${directionArrow(idx.change_pct)} ${fmtNum(Math.abs(idx.change_pct))}%`
          : "-";
        item.append(nameEl, priceEl, chgEl);
        item.style.cursor = "pointer";
        item.title = "點擊查看走勢圖";
        item.addEventListener("click", () => { openChartModal(); loadIndexChart(key, idx.name); });
        bar.appendChild(item);
      }
    } catch (err) {
      console.error("loadIndices failed", err);
    }
  }

  $("#watchlistForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#codeInput");
    const code = input.value.trim();
    if (!code) return;
    if (!state.watchlist.includes(code)) {
      state.watchlist.push(code);
      saveWatchlist();
      renderTiles();
      refreshQuotes();
    }
    input.value = "";
    hideCodeSuggestions();
  });

  // ---------- 代碼／名稱自動完成（輸入中文名稱或不完整代碼都能選）----------
  let stockDirectory = [];
  let stockDirectoryPromise = null;

  function ensureStockDirectory() {
    if (stockDirectory.length) return Promise.resolve(stockDirectory);
    if (!stockDirectoryPromise) {
      stockDirectoryPromise = fetch("/api/stock_directory")
        .then((res) => res.json())
        .then((data) => {
          stockDirectory = data.data || [];
          return stockDirectory;
        })
        .catch((err) => { console.error(err); return []; });
    }
    return stockDirectoryPromise;
  }

  const suggestionsEl = $("#codeInputSuggestions");
  let suggestionActiveIndex = -1;
  let currentSuggestions = [];

  function hideCodeSuggestions() {
    suggestionsEl.classList.remove("open");
    suggestionsEl.innerHTML = "";
    suggestionActiveIndex = -1;
    currentSuggestions = [];
  }

  function renderCodeSuggestions(matches) {
    currentSuggestions = matches;
    suggestionActiveIndex = -1;
    suggestionsEl.innerHTML = "";
    if (!matches.length) {
      suggestionsEl.innerHTML = `<div class="empty-item">查無符合的代碼或名稱</div>`;
      suggestionsEl.classList.add("open");
      return;
    }
    matches.forEach((m, i) => {
      const item = document.createElement("div");
      item.className = "item";
      item.dataset.index = i;
      item.innerHTML = `<span class="code">${escapeHtml(m.code)}</span><span class="name">${escapeHtml(m.name)}</span>`;
      item.addEventListener("mousedown", (e) => {
        e.preventDefault(); // 避免 input 先觸發 blur 把清單關掉
        $("#codeInput").value = m.code;
        hideCodeSuggestions();
      });
      suggestionsEl.appendChild(item);
    });
    suggestionsEl.classList.add("open");
  }

  function updateSuggestionActive() {
    suggestionsEl.querySelectorAll(".item").forEach((el, i) => {
      el.classList.toggle("active", i === suggestionActiveIndex);
    });
  }

  $("#codeInput").addEventListener("input", async (e) => {
    const q = e.target.value.trim();
    if (!q) { hideCodeSuggestions(); return; }
    const dir = await ensureStockDirectory();
    if ($("#codeInput").value.trim() !== q) return; // 輸入內容已變化，結果過期
    const ql = q.toLowerCase();
    const rank = (s) => {
      const code = s.code.toLowerCase();
      if (code === ql) return 0;
      if (code.startsWith(ql)) return 1;
      if (s.name.startsWith(q)) return 2;
      if (code.includes(ql)) return 3;
      if (s.name.includes(q)) return 4;
      return 9;
    };
    const matches = dir
      .map((s) => ({ s, r: rank(s) }))
      .filter((x) => x.r < 9)
      .sort((a, b) => a.r - b.r || a.s.code.localeCompare(b.s.code))
      .slice(0, 8)
      .map((x) => x.s);
    renderCodeSuggestions(matches);
  });

  $("#codeInput").addEventListener("keydown", (e) => {
    if (!suggestionsEl.classList.contains("open") || !currentSuggestions.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      suggestionActiveIndex = Math.min(suggestionActiveIndex + 1, currentSuggestions.length - 1);
      updateSuggestionActive();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      suggestionActiveIndex = Math.max(suggestionActiveIndex - 1, 0);
      updateSuggestionActive();
    } else if (e.key === "Enter" && suggestionActiveIndex >= 0) {
      e.preventDefault();
      $("#codeInput").value = currentSuggestions[suggestionActiveIndex].code;
      hideCodeSuggestions();
    } else if (e.key === "Escape") {
      hideCodeSuggestions();
    }
  });

  $("#codeInput").addEventListener("blur", () => {
    setTimeout(hideCodeSuggestions, 150); // 延遲一下，讓點擊清單項目的 mousedown 先觸發
  });

  // ---------- 深／淺色介面切換 ----------
  const themeToggleBtn = $("#themeToggleBtn");

  function isDarkActive() {
    return document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function updateThemeToggleIcon() {
    themeToggleBtn.textContent = isDarkActive() ? "☀️" : "🌙";
  }

  themeToggleBtn.addEventListener("click", () => {
    const next = isDarkActive() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch {}
    updateThemeToggleIcon();
  });

  updateThemeToggleIcon();

