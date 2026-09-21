  // ---------- screener: 高點反轉黑K（放空早期觸發訊號）----------
  const reversalScreenerBody = $("#reversalScreenerBody");
  const reversalScreenerStatus = $("#reversalScreenerStatus");
  const reversalIndustryFilter = $("#reversalIndustryFilter");
  let reversalScreenerResults = [];
  let reversalScreenerPage = 1;

  function populateReversalIndustryFilter(results) {
    const industries = [...new Set(results.map((r) => r.industry))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
    const current = reversalIndustryFilter.value;
    reversalIndustryFilter.innerHTML = '<option value="">全部</option>';
    for (const ind of industries) {
      const opt = document.createElement("option");
      opt.value = ind;
      opt.textContent = ind;
      reversalIndustryFilter.appendChild(opt);
    }
    if (industries.includes(current)) reversalIndustryFilter.value = current;
  }

  function renderReversalScreenerTable() {
    const industry = reversalIndustryFilter.value;
    const rows = industry ? reversalScreenerResults.filter((r) => r.industry === industry) : reversalScreenerResults;

    const pagination = $("#reversalScreenerPagination");
    reversalScreenerBody.innerHTML = "";
    if (!rows.length) {
      reversalScreenerBody.innerHTML = `<tr><td colspan="21" class="empty">沒有符合條件的股票</td></tr>`;
      pagination.style.display = "none";
      return;
    }

    const totalPages = Math.max(1, Math.ceil(rows.length / SCREENER_PAGE_SIZE));
    reversalScreenerPage = Math.min(Math.max(1, reversalScreenerPage), totalPages);
    const pageRows = rows.slice((reversalScreenerPage - 1) * SCREENER_PAGE_SIZE, reversalScreenerPage * SCREENER_PAGE_SIZE);

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
      tr.appendChild(textCell(fmtNum(r.open)));
      tr.appendChild(textCell(fmtNum(r.high)));
      tr.appendChild(textCell(fmtNum(r.low)));
      tr.appendChild(textCell(fmtNum(r.close)));
      const shadowTd = textCell(r.shadow_ratio != null ? `${r.shadow_ratio}x` : "-");
      shadowTd.style.fontWeight = "700";
      tr.appendChild(shadowTd);
      tr.appendChild(textCell(fmtNum(r.prior_high)));
      tr.appendChild(pctCell(r.pct_from_high));
      tr.appendChild(textCell(r.avg_trade_value_wan != null ? r.avg_trade_value_wan.toLocaleString("zh-TW") : "-"));
      tr.appendChild(textCell(r.volume_confirmed ? "✓" : "-"));
      tr.appendChild(pctCell(r.chip_bias_5));
      tr.appendChild(pctCell(r.revenue_yoy_pct));
      tr.appendChild(textCell(
        r.eps !== null && r.eps !== undefined ? `${fmtNum(r.eps)}（${r.eps_period}）` : "-"
      ));
      const peTd = textCell(r.pe_ratio != null ? fmtNum(r.pe_ratio) : "-");
      if (r.pe_high || r.pe_missing) peTd.className = "pos";
      tr.appendChild(peTd);
      tr.appendChild(textCell(r.margin_short_balance != null ? r.margin_short_balance.toLocaleString("zh-TW") : "-"));
      tr.appendChild(textCell(r.margin_short_limit != null ? r.margin_short_limit.toLocaleString("zh-TW") : "-"));
      const usageTd = textCell(r.margin_short_usage_pct != null ? `${r.margin_short_usage_pct}%` : "-");
      if (r.margin_crowded) {
        usageTd.className = "neg";
        usageTd.title = "融券額度用超過80%，能加碼放空的空間有限";
      }
      tr.appendChild(usageTd);

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
      if (r.margin_crowded) {
        const b = document.createElement("span");
        b.className = "badge attention";
        b.textContent = "融券空間有限";
        b.title = "融券額度已使用超過80%";
        badgeCell.appendChild(b);
      }
      if (!r.is_disposition && !r.is_attention && !r.margin_crowded) badgeCell.textContent = "-";
      tr.appendChild(badgeCell);

      tr.addEventListener("click", () => selectStock(r.code, r.name));
      reversalScreenerBody.appendChild(tr);
    }

    pagination.style.display = totalPages > 1 ? "flex" : "none";
    $("#reversalScreenerPageInfo").textContent = `共 ${rows.length} 筆・第 ${reversalScreenerPage} / ${totalPages} 頁`;
    $("#reversalScreenerPrevBtn").disabled = reversalScreenerPage <= 1;
    $("#reversalScreenerNextBtn").disabled = reversalScreenerPage >= totalPages;
  }

  $("#reversalScreenerPrevBtn").addEventListener("click", () => {
    if (reversalScreenerPage > 1) { reversalScreenerPage -= 1; renderReversalScreenerTable(); }
  });
  $("#reversalScreenerNextBtn").addEventListener("click", () => {
    reversalScreenerPage += 1;
    renderReversalScreenerTable();
  });

  async function runReversalScreener() {
    const nearHighPct = parseFloat($("#reversalNearHighPct").value) || 3;
    const minShadowRatio = parseFloat($("#reversalMinShadowRatio").value) || 1;
    const minTradeValueWan = parseFloat($("#reversalMinTradeValue").value) || 0;
    const btn = $("#runReversalScreenerBtn");
    btn.disabled = true;
    reversalScreenerStatus.innerHTML = `<span class="spinner"></span>掃描全市場中，首次掃描可能需要 30-90 秒…`;
    reversalScreenerBody.innerHTML = `<tr><td colspan="21" class="empty">掃描中…</td></tr>`;
    try {
      const res = await fetch(`/api/reversal_short_screener?near_high_pct=${nearHighPct}&min_shadow_ratio=${minShadowRatio}&min_trade_value_wan=${minTradeValueWan}`);
      const data = await res.json();
      reversalScreenerResults = data.results || [];
      reversalScreenerPage = 1;
      populateReversalIndustryFilter(reversalScreenerResults);
      renderReversalScreenerTable();
      reversalScreenerStatus.textContent =
        `掃描 ${data.candidates_scanned} 檔候選股（今日收黑K且上影線夠長），符合條件（且可融券）${reversalScreenerResults.length} 檔・更新於 ${data.generated_at}`;
    } catch (err) {
      reversalScreenerStatus.textContent = "掃描失敗，請稍後再試";
      reversalScreenerBody.innerHTML = `<tr><td colspan="21" class="empty">掃描失敗</td></tr>`;
      console.error(err);
    } finally {
      btn.disabled = false;
    }
  }

  $("#runReversalScreenerBtn").addEventListener("click", runReversalScreener);
  reversalIndustryFilter.addEventListener("change", () => { reversalScreenerPage = 1; renderReversalScreenerTable(); });

  function openReversalScreenerModal() {
    openModal("選股：高點反轉黑K（放空早期觸發訊號）", $("#reversalScreenerCard"));
  }
  $("#navReversalScreenerBtn").addEventListener("click", openReversalScreenerModal);
