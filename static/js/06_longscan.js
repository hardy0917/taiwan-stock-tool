  // ---------- 今日做多訊號掃描（觀察清單） ----------
  function buildLongScanContainer() {
    const wrap = document.createElement("div");
    wrap.className = "backtest-modal";
    wrap.innerHTML = `
      <div class="bt-form">
        <div class="bt-field">
          <label for="lsStrategy">策略</label>
          <select id="lsStrategy">
            <option value="ma_cross">均線黃金/死亡交叉</option>
            <option value="bollinger">布林通道回歸（John Bollinger）</option>
            <option value="breakout">唐奇安通道突破（海龜交易法則）</option>
            <option value="macd">MACD 指標交叉（Gerald Appel）</option>
            <option value="kd">KD 隨機指標（George Lane）</option>
            <option value="rsi">RSI 相對強弱指標（J. Welles Wilder）</option>
          </select>
        </div>
        <div class="bt-field">
          <label for="lsTimeframe">K線週期</label>
          <select id="lsTimeframe">
            <option value="daily" selected>日K</option>
            <option value="60m">60分K</option>
            <option value="5m">5分K</option>
          </select>
        </div>
        <div class="bt-field">
          <label for="lsMinVolume">最低平均量（張）</label>
          <input type="number" id="lsMinVolume" value="1000" min="0" step="100">
        </div>
        <button id="lsRunBtn" class="primary" type="button">開始掃描</button>
      </div>
      <div id="lsResults"><p class="empty">掃描你目前追蹤（觀察清單）的股票，用預設參數即時判斷每檔股票今天是否觸發買進訊號</p></div>
    `;
    return wrap;
  }

  function buildLongScanTable(results) {
    const wrap = document.createElement("div");
    const note = document.createElement("p");
    note.className = "note";
    note.innerHTML = `共掃描 ${results.length} 檔。「可進場」代表：策略觸發買進訊號、目前空手（不是加碼）、且近5日平均量通過流動性門檻。` +
      `這是規則式的即時試算，盤中價格還會變動，正式訊號要等這根K棒收盤才算數，<strong>不構成投資建議</strong>。`;
    wrap.appendChild(note);

    const table = document.createElement("table");
    table.innerHTML = `
      <thead><tr><th>代碼</th><th>名稱</th><th>訊號</th><th>近5日均量(張)</th><th>建議</th></tr></thead>
      <tbody>
        ${results.map((r) => {
          const name = escapeHtml((state.quotes[r.code] && state.quotes[r.code].name) || "");
          const code = escapeHtml(r.code);
          if (r.error) {
            return `<tr><td>${code}</td><td>${name}</td><td colspan="3" class="empty">${escapeHtml(r.error)}</td></tr>`;
          }
          const sigLabel = r.pending_signal === "buy" ? "買進" : r.pending_signal === "sell" ? "賣出" : "無訊號";
          const sigClass = r.pending_signal === "buy" ? "up" : r.pending_signal === "sell" ? "down" : "";
          let action, actionClass;
          if (r.actionable_buy) { action = "✅ 可進場（做多）"; actionClass = "up"; }
          else if (r.pending_signal === "buy" && r.will_execute && !r.liquidity_ok) { action = "⚠️ 有訊號但量太小"; actionClass = ""; }
          else if (r.pending_signal === "buy" && !r.will_execute) { action = "已持有中，不加碼"; actionClass = ""; }
          else { action = "-"; actionClass = ""; }
          return `
            <tr class="${r.actionable_buy ? "up" : ""}">
              <td>${code}</td>
              <td>${name}</td>
              <td class="${sigClass}">${sigLabel}</td>
              <td class="${r.liquidity_ok ? "" : "down"}">${fmtNum(r.avg_volume_lots, 0)}</td>
              <td class="${actionClass}">${action}</td>
            </tr>
          `;
        }).join("")}
      </tbody>
    `;
    wrap.appendChild(table);
    return wrap;
  }

  $("#longScanBtn").addEventListener("click", () => {
    if (!state.watchlist.length) {
      const container = document.createElement("div");
      container.innerHTML = `<p class="empty">觀察清單是空的，先加入幾檔股票再來掃描</p>`;
      openModal("今日做多訊號掃描", container);
      return;
    }
    const container = buildLongScanContainer();
    openModal("今日做多訊號掃描（觀察清單）", container);

    container.querySelector("#lsRunBtn").addEventListener("click", async () => {
      const resultsEl = container.querySelector("#lsResults");
      const params = new URLSearchParams({
        codes: state.watchlist.join(","),
        strategy: container.querySelector("#lsStrategy").value,
        timeframe: container.querySelector("#lsTimeframe").value,
        min_volume_lots: container.querySelector("#lsMinVolume").value,
      });
      resultsEl.innerHTML = `<p class="empty"><span class="spinner"></span>掃描中…（逐檔即時判斷，稍等一下）</p>`;
      try {
        const res = await fetch(`/api/backtest_scan?${params.toString()}`);
        const data = await res.json();
        if (modalBody.firstElementChild !== container) return;
        resultsEl.innerHTML = "";
        resultsEl.appendChild(buildLongScanTable(data.results || []));
      } catch (err) {
        console.error(err);
        if (modalBody.firstElementChild === container) {
          resultsEl.innerHTML = `<p class="empty">掃描失敗，請稍後再試</p>`;
        }
      }
    });
  });

