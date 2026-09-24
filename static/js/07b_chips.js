  // ---------- 個股籌碼分析（三大法人買賣超歷史 + 融資融券 + 價籌背離判斷） ----------
  const CHIPS_DAYS_OPTIONS = [
    { days: 5, label: "5日（極短線）" },
    { days: 10, label: "10日（短線）" },
    { days: 20, label: "20日（預設）" },
    { days: 40, label: "40日（中線）" },
    { days: 60, label: "60日（長線）" },
  ];
  let chipsDays = 20;
  let chipsCurrentCode = null;
  let chipsCurrentName = null;

  function fmtLots(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "-";
    return `${n > 0 ? "+" : ""}${n.toLocaleString("zh-TW")}`;
  }

  function buildChipsDaysSelector() {
    const row = document.createElement("div");
    row.className = "chips-days-selector";
    for (const { days, label } of CHIPS_DAYS_OPTIONS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.className = days === chipsDays ? "active" : "";
      btn.addEventListener("click", () => {
        if (chipsDays === days) return;
        chipsDays = days;
        loadChips(chipsCurrentCode, chipsCurrentName);
      });
      row.appendChild(btn);
    }
    return row;
  }

  function buildChipsContent(data, name) {
    const wrap = document.createElement("div");
    wrap.className = "fundamentals-modal chips-modal";
    wrap.appendChild(buildChipsDaysSelector());

    const div = data.divergence;
    if (div && !div.error) {
      const banner = document.createElement("div");
      banner.className = `verdict-banner ${div.verdict}`;
      banner.textContent = `${div.verdict_label}（${escapeHtml(div.period_from)} ~ ${escapeHtml(div.period_to)}，共 ${div.days} 個交易日）`;
      wrap.appendChild(banner);

      const thresholdNote = document.createElement("p");
      thresholdNote.className = "note";
      thresholdNote.style.margin = "4px 0 10px";
      thresholdNote.textContent = `本次判斷門檻（隨天數自動調整）：股價變動 ±${fmtNum(div.price_threshold_pct)}%・籌碼佔量比 ±${fmtNum(div.chip_threshold_pct)}%`;
      wrap.appendChild(thresholdNote);

      const grid = document.createElement("div");
      grid.className = "ref-grid";
      const items = [
        ["股價變動%", `${div.price_change_pct > 0 ? "+" : ""}${fmtNum(div.price_change_pct)}%`],
        ["三大法人合計買賣超(張)", fmtLots(div.total_net_lots)],
        ["外資買賣超(張)", fmtLots(div.foreign_net_lots)],
        ["投信買賣超(張)", fmtLots(div.trust_net_lots)],
        ["自營商買賣超(張)", fmtLots(div.dealer_net_lots)],
        ["籌碼佔期間成交量比", `${div.chip_bias_pct > 0 ? "+" : ""}${fmtNum(div.chip_bias_pct)}%`],
      ];
      for (const [label, value] of items) {
        const item = document.createElement("div");
        item.className = "ref-item";
        item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
        grid.appendChild(item);
      }
      wrap.appendChild(grid);
    } else if (div && div.error) {
      const p = document.createElement("p");
      p.className = "note";
      p.textContent = `背離判斷暫時無法計算：${div.error}`;
      wrap.appendChild(p);
    }

    const margin = data.margin;
    if (margin) {
      const h4 = document.createElement("h4");
      h4.textContent = "融資融券（最新交易日）";
      wrap.appendChild(h4);
      const grid = document.createElement("div");
      grid.className = "ref-grid";
      const usageValue = (pct) => pct == null ? "-" : `${pct}%`;
      const items = [
        ["融資今日餘額(張)", margin.margin_balance != null ? margin.margin_balance.toLocaleString("zh-TW") : "-"],
        ["融資限額(張)", margin.margin_limit != null ? margin.margin_limit.toLocaleString("zh-TW") : "-"],
        ["融資使用率", usageValue(margin.margin_usage_pct)],
        ["融券今日餘額(張)", margin.short_balance != null ? margin.short_balance.toLocaleString("zh-TW") : "-"],
        ["融券限額(張)", margin.short_limit != null ? margin.short_limit.toLocaleString("zh-TW") : "-"],
        ["融券使用率", usageValue(margin.short_usage_pct)],
      ];
      for (const [label, value] of items) {
        const item = document.createElement("div");
        item.className = "ref-item";
        item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
        grid.appendChild(item);
      }
      wrap.appendChild(grid);
    }

    const marginHistory = data.margin_history || [];
    if (marginHistory.length) {
      const mh4 = document.createElement("h4");
      mh4.textContent = "融資融券每日增減（單位：張，由舊到新）";
      wrap.appendChild(mh4);
      const mTable = document.createElement("table");
      const mThead = document.createElement("thead");
      mThead.innerHTML = `<tr><th style="text-align:left">日期</th><th>融資餘額</th><th>融資增減</th><th>融券餘額</th><th>融券增減</th></tr>`;
      mTable.appendChild(mThead);
      const mTbody = document.createElement("tbody");
      for (const h of [...marginHistory].reverse()) {
        const tr = document.createElement("tr");
        const dateTd = document.createElement("td");
        dateTd.style.textAlign = "left";
        dateTd.textContent = h.date;
        tr.appendChild(dateTd);

        const balCell = (v) => {
          const td = document.createElement("td");
          td.textContent = v != null ? v.toLocaleString("zh-TW") : "-";
          return td;
        };
        const changeCell = (v) => {
          const td = document.createElement("td");
          td.className = directionClass(v ?? 0);
          td.textContent = fmtLots(v);
          return td;
        };
        tr.appendChild(balCell(h.margin_balance));
        tr.appendChild(changeCell(h.margin_change));
        tr.appendChild(balCell(h.short_balance));
        tr.appendChild(changeCell(h.short_change));
        mTbody.appendChild(tr);
      }
      mTable.appendChild(mTbody);
      wrap.appendChild(mTable);
    }

    const history = data.history || [];
    const h4 = document.createElement("h4");
    h4.textContent = "三大法人買賣超歷史（單位：張，由舊到新）";
    wrap.appendChild(h4);
    if (!history.length) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "查無資料";
      wrap.appendChild(p);
    } else {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      thead.innerHTML = `<tr><th style="text-align:left">日期</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th></tr>`;
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const h of [...history].reverse()) {
        const tr = document.createElement("tr");
        const dateTd = document.createElement("td");
        dateTd.style.textAlign = "left";
        dateTd.textContent = h.date;
        tr.appendChild(dateTd);
        for (const key of ["foreign_net", "trust_net", "dealer_net", "total_net"]) {
          const td = document.createElement("td");
          const lots = h[key] != null ? Math.round(h[key] / 1000) : null;
          td.className = directionClass(lots ?? 0);
          td.textContent = fmtLots(lots);
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      wrap.appendChild(table);
    }

    const disclaimer = document.createElement("p");
    disclaimer.className = "disclaimer";
    disclaimer.textContent = "三大法人買賣超（外資／投信／自營商）是市場上最主流的籌碼指標，但不是「主力」的全部——證交所沒有提供公開的券商分點進出資料，這部分不在本工具涵蓋範圍內。背離判斷是對已發生資料的客觀統計比對，不是預測，也不構成投資建議。";
    wrap.appendChild(disclaimer);

    return wrap;
  }

  async function loadChips(code, name) {
    chipsCurrentCode = code;
    chipsCurrentName = name;
    const container = document.createElement("div");
    container.innerHTML = `<p class="empty"><span class="spinner"></span>分析籌碼中…（第一次查某檔股票、或切換到更長的天數，要逐日回溯查詢，可能需要10-30秒；查過的天數之後會秒開）</p>`;
    openModal(`籌碼分析：${name}`, container);
    try {
      const res = await fetch(`/api/chips?code=${encodeURIComponent(code)}&days=${chipsDays}`);
      const data = await res.json();
      if (modalBody.firstElementChild !== container) return;
      container.innerHTML = "";
      container.appendChild(buildChipsContent(data, name));
    } catch (err) {
      console.error(err);
      if (modalBody.firstElementChild === container) {
        container.innerHTML = `<p class="empty">載入失敗，請稍後再試</p>`;
      }
    }
  }

  $("#chipsBtn").addEventListener("click", () => {
    if (state.selectedIsIndex || !state.selectedCode) {
      const container = document.createElement("div");
      container.innerHTML = `<p class="empty">請先從觀察清單、選股結果或市場總覽點選一檔個股（不支援大盤指數）</p>`;
      openModal("籌碼分析", container);
      return;
    }
    loadChips(state.selectedCode, state.selectedName || state.selectedCode);
  });
