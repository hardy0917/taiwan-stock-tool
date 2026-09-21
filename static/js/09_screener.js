  // ---------- screener: 月線多頭 + 財務體質 ----------
  const screenerBody = $("#screenerBody");
  const screenerStatus = $("#screenerStatus");
  const industryFilter = $("#industryFilter");
  let screenerResults = [];
  const SCREENER_PAGE_SIZE = 10;
  let screenerPage = 1;

  function populateIndustryFilter(results) {
    const industries = [...new Set(results.map((r) => r.industry))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
    const current = industryFilter.value;
    industryFilter.innerHTML = '<option value="">全部</option>';
    for (const ind of industries) {
      const opt = document.createElement("option");
      opt.value = ind;
      opt.textContent = ind;
      industryFilter.appendChild(opt);
    }
    if (industries.includes(current)) industryFilter.value = current;
  }

  function renderScreenerTable() {
    const industry = industryFilter.value;
    const rows = industry ? screenerResults.filter((r) => r.industry === industry) : screenerResults;

    const pagination = $("#screenerPagination");
    screenerBody.innerHTML = "";
    if (!rows.length) {
      screenerBody.innerHTML = `<tr><td colspan="22" class="empty">沒有符合條件的股票</td></tr>`;
      pagination.style.display = "none";
      return;
    }

    const totalPages = Math.max(1, Math.ceil(rows.length / SCREENER_PAGE_SIZE));
    screenerPage = Math.min(Math.max(1, screenerPage), totalPages);
    const pageRows = rows.slice((screenerPage - 1) * SCREENER_PAGE_SIZE, screenerPage * SCREENER_PAGE_SIZE);

    for (const r of pageRows) {
      const tr = document.createElement("tr");

      const textCell = (text, alignLeft) => {
        const td = document.createElement("td");
        if (alignLeft) td.style.textAlign = "left";
        td.textContent = text;
        return td;
      };
      const pctCell = (val) => {
        const td = document.createElement("td");
        if (val === null || val === undefined || Number.isNaN(val)) {
          td.textContent = "-";
        } else {
          td.className = val > 0 ? "pos" : val < 0 ? "neg" : "flat";
          td.textContent = `${val > 0 ? "+" : ""}${val.toFixed(1)}%`;
        }
        return td;
      };

      tr.appendChild(textCell(r.code, true));
      tr.appendChild(textCell(r.name, true));
      tr.appendChild(textCell(r.industry, true));
      const scoreTd = document.createElement("td");
      scoreTd.className = r.fit_score > 0 ? "pos" : r.fit_score < 0 ? "neg" : "flat";
      scoreTd.style.fontWeight = "700";
      scoreTd.textContent = (r.fit_score > 0 ? "+" : "") + r.fit_score;
      tr.appendChild(scoreTd);
      tr.appendChild(textCell(fmtNum(r.close)));
      tr.appendChild(textCell(fmtNum(r.monthly_avg)));
      tr.appendChild(textCell(fmtNum(r.entry_ref_price)));
      const levelTd = document.createElement("td");
      levelTd.style.fontWeight = "700";
      levelTd.textContent = r.boll_level != null ? r.boll_level : "-";
      tr.appendChild(levelTd);
      tr.appendChild(pctCell(r.ma20_slope_pct));
      tr.appendChild(pctCell(r.chip_bias_20));
      const holdersTd = textCell(r.holders_1000 != null ? `${r.holders_1000}` : "-");
      if (r.holders_1000 != null && !r.holders_reliable) {
        holdersTd.textContent += "（樣本少）";
        holdersTd.title = "大戶人數低於5人，變化%統計上不可靠，未列入評分";
        holdersTd.style.color = "var(--text-muted)";
      }
      tr.appendChild(holdersTd);
      const holderChgTd = document.createElement("td");
      if (!r.holders_reliable) {
        holderChgTd.textContent = "-";
        holderChgTd.className = "flat";
      } else if (r.holders_1000_change == null) {
        holderChgTd.textContent = "-";
      } else {
        holderChgTd.className = r.holders_1000_change > 0 ? "pos" : r.holders_1000_change < 0 ? "neg" : "flat";
        holderChgTd.textContent = `${r.holders_1000_change > 0 ? "+" : ""}${r.holders_1000_change}`;
      }
      tr.appendChild(holderChgTd);
      tr.appendChild(textCell(r.avg_trade_value_wan != null ? r.avg_trade_value_wan.toLocaleString("zh-TW") : "-"));
      tr.appendChild(textCell(r.long_term_bull_pct != null ? `${r.long_term_bull_pct.toFixed(1)}%` : "-"));
      tr.appendChild(pctCell(r.revenue_mom_pct));
      tr.appendChild(pctCell(r.revenue_yoy_pct));
      tr.appendChild(pctCell(r.revenue_cum_yoy_pct));
      tr.appendChild(textCell(
        r.eps !== null && r.eps !== undefined ? `${fmtNum(r.eps)}（${r.eps_period}）` : "-"
      ));
      const peTd = textCell(r.pe_ratio != null ? fmtNum(r.pe_ratio) : "-");
      if (r.pe_high) {
        peTd.className = "neg";
        peTd.title = "本益比超過 40 倍，評分已扣分提醒估值偏高";
      }
      tr.appendChild(peTd);
      tr.appendChild(textCell(r.dividend_yield != null ? `${fmtNum(r.dividend_yield)}%` : "-"));

      const entryTypeCell = document.createElement("td");
      entryTypeCell.style.textAlign = "left";
      const entryTypeLabels = { boll_pullback: "布林下軌拉回", disposition_pullback: "處置回檔" };
      (r.entry_type || []).forEach((t) => {
        const b = document.createElement("span");
        b.className = "badge category-trend";
        b.textContent = entryTypeLabels[t] || t;
        entryTypeCell.appendChild(b);
      });
      tr.appendChild(entryTypeCell);

      const badgeCell = document.createElement("td");
      badgeCell.style.textAlign = "left";
      if (r.is_disposition) {
        const b = document.createElement("span");
        b.className = "badge disposition";
        b.textContent = "處置股";
        if (r.disposition_reason) b.title = r.disposition_reason;
        badgeCell.appendChild(b);
      }
      if (r.is_attention) {
        const b = document.createElement("span");
        b.className = "badge attention";
        b.textContent = "注意股";
        badgeCell.appendChild(b);
      }
      if (r.distribution_risk) {
        const b = document.createElement("span");
        b.className = "badge disposition";
        b.textContent = "⚠ 疑似出貨";
        b.title = "近20日量能偏空 + 大戶人數減少";
        badgeCell.appendChild(b);
      }
      if (r.chip_revenue_divergence) {
        const b = document.createElement("span");
        b.className = "badge attention";
        b.textContent = "⚠ 籌碼營收背離";
        b.title = "近20日籌碼明顯偏多，但營收年增卻明顯衰退，買盤可能是題材面而非基本面";
        badgeCell.appendChild(b);
      }
      if (r.pe_high) {
        const b = document.createElement("span");
        b.className = "badge attention";
        b.textContent = "本益比偏高";
        b.title = "本益比超過 40 倍，估值相對偏貴，可能是題材／成長性溢價";
        badgeCell.appendChild(b);
      }
      if (!r.is_disposition && !r.is_attention && !r.distribution_risk && !r.chip_revenue_divergence && !r.pe_high) badgeCell.textContent = "-";
      tr.appendChild(badgeCell);

      tr.addEventListener("click", () => selectStock(r.code, r.name));
      screenerBody.appendChild(tr);
    }

    pagination.style.display = totalPages > 1 ? "flex" : "none";
    $("#screenerPageInfo").textContent = `共 ${rows.length} 筆・第 ${screenerPage} / ${totalPages} 頁`;
    $("#screenerPrevBtn").disabled = screenerPage <= 1;
    $("#screenerNextBtn").disabled = screenerPage >= totalPages;
  }

  $("#screenerPrevBtn").addEventListener("click", () => {
    if (screenerPage > 1) { screenerPage -= 1; renderScreenerTable(); }
  });
  $("#screenerNextBtn").addEventListener("click", () => {
    screenerPage += 1;
    renderScreenerTable();
  });

  async function runScreener() {
    const pct = parseFloat($("#screenerPct").value);
    const bollLevelThreshold = Number.isNaN(pct) ? 3 : pct;
    const trendDays = parseInt($("#screenerTrendDays").value, 10) || 10;
    const longTerm = $("#screenerLongTerm").checked;
    const minTradeValueWan = parseFloat($("#screenerMinTradeValue").value) || 0;
    const btn = $("#runScreenerBtn");
    btn.disabled = true;
    const waitHint = longTerm ? "首次掃描含長期分析可能需要 30-90 秒…" : "首次掃描可能需要 30-60 秒…";
    screenerStatus.innerHTML = `<span class="spinner"></span>掃描全市場中，${waitHint}`;
    screenerBody.innerHTML = `<tr><td colspan="22" class="empty">掃描中…</td></tr>`;
    try {
      const res = await fetch(`/api/screener?boll_level_threshold=${bollLevelThreshold}&trend_days=${trendDays}&long_term=${longTerm ? 1 : 0}&min_trade_value_wan=${minTradeValueWan}`);
      const data = await res.json();
      screenerResults = data.results || [];
      screenerPage = 1;
      populateIndustryFilter(screenerResults);
      renderScreenerTable();
      renderDailyWatchlist();
      screenerStatus.textContent =
        `掃描 ${data.candidates_scanned} 檔候選股，符合條件 ${screenerResults.length} 檔・更新於 ${data.generated_at}`;
    } catch (err) {
      screenerStatus.textContent = "掃描失敗，請稍後再試";
      screenerBody.innerHTML = `<tr><td colspan="22" class="empty">掃描失敗</td></tr>`;
      console.error(err);
    } finally {
      btn.disabled = false;
    }
  }

  $("#runScreenerBtn").addEventListener("click", runScreener);
  industryFilter.addEventListener("change", () => { screenerPage = 1; renderScreenerTable(); });

