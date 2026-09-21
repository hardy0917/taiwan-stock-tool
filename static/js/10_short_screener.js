  // ---------- screener: 放空篩選（脫離布林上軌 + 隔天進處置） ----------
  const shortScreenerBody = $("#shortScreenerBody");
  const shortScreenerStatus = $("#shortScreenerStatus");

  function renderShortScreenerTable(results) {
    shortScreenerBody.innerHTML = "";
    if (!results.length) {
      shortScreenerBody.innerHTML = `<tr><td colspan="8" class="empty">目前沒有「隔天要進處置＋已脫離布林上軌」的股票</td></tr>`;
      return;
    }
    for (const r of results) {
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
      const breakoutTd = document.createElement("td");
      breakoutTd.className = "up";
      breakoutTd.textContent = `+${fmtNum(r.breakout_pct)}%`;
      tr.appendChild(breakoutTd);
      tr.appendChild(textCell(r.avg_trade_value_wan != null ? r.avg_trade_value_wan.toLocaleString("zh-TW") : "-"));
      tr.appendChild(textCell(r.disposition_start_date, true));
      const reasonTd = textCell(r.disposition_reason, true);
      reasonTd.title = r.disposition_period || "";
      tr.appendChild(reasonTd);
      tr.addEventListener("click", () => selectStock(r.code, r.name));
      shortScreenerBody.appendChild(tr);
    }
  }

  async function runShortScreener() {
    const minTradeValueWan = parseFloat($("#shortScreenerMinTradeValue").value) || 0;
    const btn = $("#runShortScreenerBtn");
    btn.disabled = true;
    shortScreenerStatus.innerHTML = `<span class="spinner"></span>掃描處置公告與布林通道中…</span>`;
    shortScreenerBody.innerHTML = `<tr><td colspan="8" class="empty">掃描中…</td></tr>`;
    try {
      const res = await fetch(`/api/short_screener?min_trade_value_wan=${minTradeValueWan}`);
      const data = await res.json();
      const results = data.results || [];
      renderShortScreenerTable(results);
      shortScreenerStatus.textContent =
        `下一個交易日（${data.next_trading_day}）即將進處置的股票共 ${data.disposition_candidates_scanned} 檔，其中已脫離布林上軌 ${results.length} 檔・更新於 ${data.generated_at}`;
    } catch (err) {
      shortScreenerStatus.textContent = "掃描失敗，請稍後再試";
      shortScreenerBody.innerHTML = `<tr><td colspan="8" class="empty">掃描失敗</td></tr>`;
      console.error(err);
    } finally {
      btn.disabled = false;
    }
  }

  $("#runShortScreenerBtn").addEventListener("click", runShortScreener);

