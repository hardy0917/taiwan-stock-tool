  // ---------- 連線狀態監控（本機伺服器連不到證交所時顯示維護畫面） ----------
  const maintenanceOverlay = $("#maintenanceOverlay");
  const maintenanceRetryNote = $("#maintenanceRetryNote");
  let isDown = false;

  async function checkHealth() {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      const data = await res.json();
      return !!data.ok;
    } catch {
      return false;
    }
  }

  function reloadAllData() {
    if (marketLoaded) loadDayAll();
    if (sectorLoaded) loadSectorFlow();
    refreshQuotes();
    if (state.selectedCode) {
      if (state.viewMode === "intraday") renderIntradayChart();
      else loadChart(state.selectedCode);
    }
  }

  async function monitorHealth() {
    const ok = await checkHealth();
    const now = new Date().toLocaleTimeString("zh-TW", { hour12: false });
    if (!ok) {
      isDown = true;
      maintenanceOverlay.style.display = "flex";
      maintenanceRetryNote.textContent = `上次檢查 ${now}・連線中斷`;
    } else if (isDown) {
      isDown = false;
      maintenanceOverlay.style.display = "none";
      reloadAllData();
    }
  }

  // ---------- 展開查看：置中彈出視窗，取代原本要往下滑才看得到的內嵌展開 ----------
  // 支援「彈窗疊彈窗」：現在很多區塊本身就是彈窗內容（例如觀察清單／走勢圖），
  // 裡面又有按鈕會開另一個彈窗（例如策略回測、今日做多訊號掃描）。用一個堆疊
  // 記住上一層，關閉時先退回上一層，疊到底才真的關掉、把內容放回原本頁面位置。
  const modalOverlay = $("#modalOverlay");
  const modalTitle = $("#modalTitle");
  const modalBody = $("#modalBody");
  const modalHomes = new Map(); // contentEl -> 原本所在位置，回到頁面上時要放回去
  const modalStack = []; // 疊在下面、還沒關閉的上幾層 {title, contentEl}

  function openModal(title, contentEl, onFirstOpen) {
    if (!modalHomes.has(contentEl)) {
      modalHomes.set(contentEl, { parent: contentEl.parentNode, next: contentEl.nextSibling });
    }
    if (modalOverlay.classList.contains("open") && modalBody.firstElementChild
        && modalBody.firstElementChild !== contentEl) {
      modalStack.push({ title: modalTitle.textContent, contentEl: modalBody.firstElementChild });
    }
    modalTitle.textContent = title;
    modalBody.innerHTML = "";
    modalBody.appendChild(contentEl);
    contentEl.style.display = "block";
    modalOverlay.classList.add("open");
    document.body.style.overflow = "hidden"; // 彈窗開著時鎖住背景捲動，避免背景跟著滑動
    if (onFirstOpen) onFirstOpen();
  }

  function closeModal() {
    if (!modalOverlay.classList.contains("open")) return;
    const contentEl = modalBody.firstElementChild;
    if (contentEl) contentEl.style.display = "none";
    modalBody.innerHTML = "";

    if (modalStack.length) {
      // 底下還疊著上一層彈窗，退回去顯示上一層，不整個關掉
      const prev = modalStack.pop();
      modalTitle.textContent = prev.title;
      modalBody.appendChild(prev.contentEl);
      prev.contentEl.style.display = "block";
      return;
    }

    modalOverlay.classList.remove("open");
    document.body.style.overflow = "";
    if (contentEl && modalHomes.has(contentEl)) {
      const home = modalHomes.get(contentEl);
      if (home.parent) {
        if (home.next) home.parent.insertBefore(contentEl, home.next);
        else home.parent.appendChild(contentEl);
      }
      modalHomes.delete(contentEl);
    }
  }

  $("#modalCloseBtn").addEventListener("click", closeModal);
  modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  // ---------- 頂部導覽列：每個按鈕都是彈窗叫出對應區塊，不用滑滾輪找 ----------
  function openDailyWatchlistModal() {
    openModal("📋 明日觀察清單", $("#dailyWatchlistCard"));
  }
  function openWatchlistModal() {
    openModal("觀察清單", $("#watchlistCard"));
  }
  function openChartModal() {
    openModal("走勢圖", $("#chartCard"));
  }
  function openScreenerModal() {
    openModal("選股：拉回低接 + 財務體質", $("#screenerCard"));
  }
  function openShortScreenerModal() {
    openModal("放空篩選：脫離布林上軌＋隔天進處置", $("#shortScreenerCard"));
  }
  $("#navDailyWatchlistBtn").addEventListener("click", openDailyWatchlistModal);
  $("#navWatchlistBtn").addEventListener("click", openWatchlistModal);
  $("#navScreenerBtn").addEventListener("click", openScreenerModal);
  $("#navShortScreenerBtn").addEventListener("click", openShortScreenerModal);

  // ---------- 頂部導覽列：美元/日圓、美元/台幣快速叫出走勢圖並直接帶入匯率 ----------
  function jumpToFxChart(key, name) {
    openChartModal();
    loadIndexChart(key, name);
  }
  $("#navUsdJpyBtn").addEventListener("click", () => jumpToFxChart("usdjpy", "美元／日圓"));
  $("#navUsdTwdBtn").addEventListener("click", () => jumpToFxChart("usdtwd", "美元／新台幣"));

  // ---------- 產業資金流向／市場總覽：按按鈕才彈窗＋才載入資料 ----------
  let sectorLoaded = false, marketLoaded = false;

  function openSectorModal() {
    openModal("產業資金流向（今日）", $("#sectorFlowContent"), () => {
      if (!sectorLoaded) { sectorLoaded = true; loadSectorFlow(); }
    });
  }
  function openMarketModal() {
    openModal("市場總覽（前一交易日收盤資料）", $("#marketOverviewContent"), () => {
      if (!marketLoaded) { marketLoaded = true; loadDayAll(); }
    });
  }
  $("#toggleSectorBtn").addEventListener("click", openSectorModal);
  $("#toggleMarketBtn").addEventListener("click", openMarketModal);
  $("#navSectorBtn").addEventListener("click", openSectorModal);
  $("#navMarketBtn").addEventListener("click", openMarketModal);

  // ---------- 處置股回檔觀察 ----------
  let dispWatchResults = [];

  async function loadDispWatch() {
    const status = $("#dispWatchStatus");
    const table = $("#dispWatchTable");
    const body = $("#dispWatchBody");
    status.textContent = "載入中…";
    status.style.display = "block";
    table.style.display = "none";
    try {
      const res = await fetch("/api/disposition_watch");
      const data = await res.json();
      const rows = data.data || [];
      dispWatchResults = rows;
      renderDailyWatchlist();
      if (!rows.length) {
        status.textContent = "目前沒有處置股回檔到布林中線以下";
        return;
      }
      body.innerHTML = "";
      for (const r of rows) {
        const tr = document.createElement("tr");
        const textCell = (text, alignLeft) => {
          const td = document.createElement("td");
          if (alignLeft) td.style.textAlign = "left";
          td.textContent = text;
          return td;
        };
        tr.appendChild(textCell(r.code, true));
        tr.appendChild(textCell(r.name, true));
        tr.appendChild(textCell(fmtNum(r.close)));
        tr.appendChild(textCell(fmtNum(r.boll_upper)));
        tr.appendChild(textCell(fmtNum(r.boll_middle)));
        tr.appendChild(textCell(fmtNum(r.boll_lower)));
        const levelTd = document.createElement("td");
        levelTd.style.fontWeight = "700";
        levelTd.textContent = r.boll_level;
        tr.appendChild(levelTd);
        tr.appendChild(textCell(r.disposition_reason, true));
        tr.appendChild(textCell(r.disposition_period, true));
        tr.addEventListener("click", () => {
          state.showBollinger = true;
          $("#bollingerToggle").checked = true;
          selectStock(r.code, r.name);
        });
        body.appendChild(tr);
      }
      status.style.display = "none";
      table.style.display = "table";
    } catch (err) {
      status.textContent = "載入失敗";
      console.error(err);
    }
  }

  let dispWatchLoaded = false;
  function openDispWatchModal() {
    openModal("處置股回檔觀察", $("#dispWatchContent"), () => {
      if (!dispWatchLoaded) { dispWatchLoaded = true; loadDispWatch(); }
    });
  }
  $("#toggleDispWatchBtn").addEventListener("click", openDispWatchModal);
  $("#navDispWatchBtn").addEventListener("click", openDispWatchModal);

  // ---------- 重要新聞（工商時報，經 Google 新聞 RSS 彙整） ----------
  const newsStatus = $("#newsStatus");
  const newsList = $("#newsList");

  function fmtNewsTime(pubDate) {
    const d = new Date(pubDate);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  }

  async function loadNews() {
    newsStatus.textContent = "載入中…";
    newsStatus.style.display = "block";
    newsList.innerHTML = "";
    try {
      const res = await fetch("/api/news");
      const data = await res.json();
      const rows = data.data || [];
      if (!rows.length) {
        newsStatus.textContent = "查無新聞，或來源暫時抓不到";
        return;
      }
      newsStatus.style.display = "none";
      for (const n of rows) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = n.link;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const titleEl = document.createElement("span");
        titleEl.className = "news-title";
        titleEl.textContent = n.title;
        const timeEl = document.createElement("span");
        timeEl.className = "news-time";
        timeEl.textContent = fmtNewsTime(n.pub_date);
        a.append(titleEl, timeEl);
        li.appendChild(a);
        newsList.appendChild(li);
      }
    } catch (err) {
      newsStatus.textContent = "載入失敗";
      newsStatus.style.display = "block";
      console.error(err);
    }
  }

  let newsLoaded = false;
  function openNewsModal() {
    openModal("📰 重要新聞", $("#newsCard"), () => {
      if (!newsLoaded) { newsLoaded = true; loadNews(); }
    });
  }
  $("#navNewsBtn").addEventListener("click", openNewsModal);

  // ---------- 產業成分股（點熱力圖格子跳出該產業所有股票，可選擇性掃描做多／做空訊號） ----------
  const sectorStocksStatus = $("#sectorStocksStatus");
  const sectorStocksBody = $("#sectorStocksBody");
  const sectorSignalNote = $("#sectorSignalNote");
  const SECTOR_SIGNAL_SCAN_LIMIT = 30; // 成分股可能上百檔，逐檔即時判斷很慢，只掃成交值前30大

  let sectorStocksRows = [];

  function sectorSignalCell() {
    const td = document.createElement("td");
    td.dataset.signalCell = "1";
    td.textContent = "-";
    return td;
  }

  async function loadSectorStocks(industry) {
    sectorStocksStatus.textContent = "載入中…";
    sectorStocksStatus.style.display = "block";
    sectorStocksBody.innerHTML = "";
    sectorSignalNote.textContent = "";
    sectorStocksRows = [];
    try {
      const res = await fetch("/api/sector_stocks?industry=" + encodeURIComponent(industry));
      const data = await res.json();
      const rows = data.data || [];
      if (!rows.length) {
        sectorStocksStatus.textContent = "查無資料";
        return;
      }
      sectorStocksStatus.style.display = "none";
      sectorStocksRows = rows;
      for (const r of rows) {
        const tr = document.createElement("tr");
        tr.dataset.code = r.code;
        const codeTd = document.createElement("td");
        codeTd.style.textAlign = "left";
        codeTd.textContent = r.code;
        const nameTd = document.createElement("td");
        nameTd.style.textAlign = "left";
        nameTd.textContent = r.name;
        const closeTd = document.createElement("td");
        closeTd.textContent = fmtNum(r.close);
        const pctTd = document.createElement("td");
        pctTd.className = directionClass(r.change_pct);
        pctTd.textContent = `${directionArrow(r.change_pct)} ${fmtNum(Math.abs(r.change_pct))}%`;
        const valueTd = document.createElement("td");
        valueTd.textContent = fmtNum(r.value_billion, 2);
        tr.append(codeTd, nameTd, closeTd, pctTd, valueTd, sectorSignalCell());
        tr.addEventListener("click", () => selectStock(r.code, r.name));
        sectorStocksBody.appendChild(tr);
      }
    } catch (err) {
      sectorStocksStatus.textContent = "載入失敗";
      sectorStocksStatus.style.display = "block";
      console.error(err);
    }
  }

  async function scanSectorSignals() {
    if (!sectorStocksRows.length) return;
    const strategy = $("#sectorSignalStrategy").value;
    const timeframe = $("#sectorSignalTimeframe").value;
    const targets = sectorStocksRows.slice(0, SECTOR_SIGNAL_SCAN_LIMIT);
    const codes = targets.map((r) => r.code);

    sectorSignalNote.textContent = `掃描中…（即時判斷前 ${codes.length} 檔，依成交值排序，稍等一下）`;
    for (const r of targets) {
      const cell = sectorStocksBody.querySelector(`tr[data-code="${r.code}"] td[data-signal-cell]`);
      if (cell) cell.textContent = "…";
    }
    try {
      const params = new URLSearchParams({ codes: codes.join(","), strategy, timeframe, min_volume_lots: "1000" });
      const res = await fetch(`/api/backtest_scan?${params.toString()}`);
      const data = await res.json();
      const results = data.results || [];
      for (const r of results) {
        const cell = sectorStocksBody.querySelector(`tr[data-code="${r.code}"] td[data-signal-cell]`);
        if (!cell) continue;
        cell.className = "";
        if (r.error) { cell.textContent = "-"; continue; }
        if (r.actionable_buy) { cell.textContent = "🟢 做多"; cell.className = "up"; }
        else if (r.pending_signal === "sell" && r.will_execute) { cell.textContent = "🔴 做空"; cell.className = "down"; }
        else if (r.pending_signal === "buy") { cell.textContent = "偏多（已持有）"; }
        else { cell.textContent = "-"; }
      }
      const restCount = sectorStocksRows.length - targets.length;
      const strategyName = (results.find((r) => r.strategy_name) || {}).strategy_name || strategy;
      sectorSignalNote.textContent = `策略：${strategyName}・即時試算，正式訊號要等K棒收盤才算數，不構成投資建議` +
        (restCount > 0 ? `・僅掃描成交值前 ${targets.length} 大，其餘 ${restCount} 檔未掃描` : "");
    } catch (err) {
      sectorSignalNote.textContent = "掃描失敗，請稍後再試";
      console.error(err);
    }
  }

  $("#sectorSignalScanBtn").addEventListener("click", scanSectorSignals);

  function openSectorStocksModal(industry) {
    $("#sectorStocksTitle").textContent = `產業成分股：${industry}`;
    openModal(`產業成分股：${industry}`, $("#sectorStocksCard"), () => loadSectorStocks(industry));
  }

  // ---------- 明日觀察清單（彙整選股高分 + 處置股回檔） ----------
  const dailyWatchlistStatus = $("#dailyWatchlistStatus");
  const dailyWatchlistTable = $("#dailyWatchlistTable");
  const dailyWatchlistBody = $("#dailyWatchlistBody");
  let dailyWatchlistGenerated = false;

  function renderDailyWatchlist() {
    if (!dailyWatchlistGenerated) return;

    const trendRows = screenerResults
      .filter((r) => r.fit_score >= 3 && !r.is_disposition && !r.is_attention && !r.distribution_risk)
      .sort((a, b) => b.fit_score - a.fit_score)
      .slice(0, 15);
    const pullbackRows = dispWatchResults;

    if (!trendRows.length && !pullbackRows.length) {
      dailyWatchlistStatus.textContent = "目前沒有符合條件的觀察標的（選股高分股或處置股回檔）";
      dailyWatchlistStatus.style.display = "block";
      dailyWatchlistTable.style.display = "none";
      return;
    }

    dailyWatchlistBody.innerHTML = "";

    const textCell = (text, alignLeft) => {
      const td = document.createElement("td");
      if (alignLeft) td.style.textAlign = "left";
      td.textContent = text;
      return td;
    };

    for (const r of trendRows) {
      const tr = document.createElement("tr");
      const catTd = document.createElement("td");
      catTd.style.textAlign = "left";
      const catBadge = document.createElement("span");
      catBadge.className = "badge category-trend";
      catBadge.textContent = "多頭訊號";
      catTd.appendChild(catBadge);
      tr.appendChild(catTd);
      tr.appendChild(textCell(r.code, true));
      tr.appendChild(textCell(r.name, true));
      tr.appendChild(textCell(r.industry, true));
      const scoreTd = document.createElement("td");
      scoreTd.className = r.fit_score > 0 ? "pos" : r.fit_score < 0 ? "neg" : "flat";
      scoreTd.style.fontWeight = "700";
      scoreTd.textContent = (r.fit_score > 0 ? "+" : "") + r.fit_score;
      tr.appendChild(scoreTd);
      tr.appendChild(textCell(fmtNum(r.close)));
      tr.appendChild(textCell(fmtNum(r.entry_ref_price)));
      const badgeCell = document.createElement("td");
      badgeCell.style.textAlign = "left";
      if (r.chip_revenue_divergence) {
        const b = document.createElement("span");
        b.className = "badge attention";
        b.textContent = "⚠ 籌碼營收背離";
        badgeCell.appendChild(b);
      }
      if (r.pe_high) {
        const b = document.createElement("span");
        b.className = "badge attention";
        b.textContent = "本益比偏高";
        badgeCell.appendChild(b);
      }
      if (!r.chip_revenue_divergence && !r.pe_high) {
        badgeCell.textContent = "-";
      }
      tr.appendChild(badgeCell);
      tr.addEventListener("click", () => selectStock(r.code, r.name));
      dailyWatchlistBody.appendChild(tr);
    }

    for (const r of pullbackRows) {
      const tr = document.createElement("tr");
      const catTd = document.createElement("td");
      catTd.style.textAlign = "left";
      const catBadge = document.createElement("span");
      catBadge.className = "badge category-pullback";
      catBadge.textContent = "處置回檔";
      catTd.appendChild(catBadge);
      tr.appendChild(catTd);
      tr.appendChild(textCell(r.code, true));
      tr.appendChild(textCell(r.name, true));
      tr.appendChild(textCell("-", true));
      const levelTd = document.createElement("td");
      levelTd.style.fontWeight = "700";
      levelTd.textContent = `位階 ${r.boll_level}`;
      tr.appendChild(levelTd);
      tr.appendChild(textCell(fmtNum(r.close)));
      tr.appendChild(textCell(fmtNum(r.boll_middle)));
      const badgeCell = document.createElement("td");
      badgeCell.style.textAlign = "left";
      const b = document.createElement("span");
      b.className = "badge disposition";
      b.textContent = r.disposition_reason || "處置股";
      badgeCell.appendChild(b);
      tr.appendChild(badgeCell);
      tr.addEventListener("click", () => {
        state.showBollinger = true;
        $("#bollingerToggle").checked = true;
        selectStock(r.code, r.name);
      });
      dailyWatchlistBody.appendChild(tr);
    }

    dailyWatchlistStatus.style.display = "none";
    dailyWatchlistTable.style.display = "table";
  }

  $("#genDailyWatchlistBtn").addEventListener("click", async () => {
    const btn = $("#genDailyWatchlistBtn");
    dailyWatchlistGenerated = true;
    btn.disabled = true;
    dailyWatchlistStatus.textContent = "產生中，掃描全市場並檢查處置股回檔中，可能需要 30-60 秒…";
    dailyWatchlistStatus.style.display = "block";
    dailyWatchlistTable.style.display = "none";
    try {
      await Promise.all([runScreener(), loadDispWatch()]);
      renderDailyWatchlist();
    } finally {
      btn.disabled = false;
    }
  });

