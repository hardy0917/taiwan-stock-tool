  // ---------- 個股基本面分析（營收/EPS + 本益比河流圖 + 重大訊息） ----------
  function buildPeBandSvg(series, fairLow, fairMid, fairHigh) {
    const w = 900, h = 240, padTop = 14, padBottom = 22, padX = 6;
    if (!series.length) return "";
    const closes = series.map((s) => s.close);
    let min = Math.min(...closes, fairLow);
    let max = Math.max(...closes, fairHigh);
    if (min === max) { min -= 1; max += 1; }
    const padV = (max - min) * 0.08;
    min -= padV; max += padV;
    const n = series.length;
    const x = (i) => padX + (i / (n - 1 || 1)) * (w - padX * 2);
    const y = (v) => padTop + (1 - (v - min) / (max - min)) * (h - padTop - padBottom);

    const points = series.map((s, i) => `${x(i).toFixed(1)},${y(s.close).toFixed(1)}`).join(" ");
    const refLine = (v, color) =>
      `<line x1="${padX}" y1="${y(v).toFixed(1)}" x2="${w - padX}" y2="${y(v).toFixed(1)}" stroke="${color}" stroke-width="1" stroke-dasharray="5,4"/>`;

    const parts = [
      refLine(fairHigh, "#a855f7"),
      refLine(fairMid, "var(--series-1)"),
      refLine(fairLow, "#e08a1e"),
      `<polyline points="${points}" fill="none" stroke="var(--up)" stroke-width="1.6"/>`,
    ];
    [0, Math.floor((n - 1) / 2), n - 1].forEach((i) => {
      const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
      parts.push(`<text x="${x(i).toFixed(1)}" y="${h - 6}" text-anchor="${anchor}" class="axis-label">${escapeHtml(series[i].date)}</text>`);
    });
    return `<svg class="pe-band-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${parts.join("")}</svg>`;
  }

  function buildFundamentalsContent(data, name) {
    const wrap = document.createElement("div");
    wrap.className = "fundamentals-modal";

    const rev = data.revenue;
    const eps = data.eps;
    const peBand = data.pe_band;

    if (rev) {
      const h1 = document.createElement("h4");
      h1.textContent = "最新月營收";
      wrap.appendChild(h1);
      const grid = document.createElement("div");
      grid.className = "ref-grid";
      const pctSpan = (v) => v == null ? "-" : `<span class="${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "+" : ""}${fmtNum(v)}%</span>`;
      const items = [
        ["產業別", escapeHtml(rev.industry || "-")],
        ["當月營收(億)", rev.revenue_month == null ? "-" : fmtNum(rev.revenue_month / 100000, 1)],
        ["月增率(MoM)", pctSpan(rev.revenue_mom_pct)],
        ["年增率(YoY)", pctSpan(rev.revenue_yoy_pct)],
        ["累計營收年增率", pctSpan(rev.revenue_cum_yoy_pct)],
      ];
      for (const [label, value] of items) {
        const item = document.createElement("div");
        item.className = "ref-item";
        item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
        grid.appendChild(item);
      }
      wrap.appendChild(grid);
    } else {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "查無月營收資料（可能是金融/證券/保險業，或近期剛掛牌）";
      wrap.appendChild(p);
    }

    if (eps) {
      const h2 = document.createElement("h4");
      h2.textContent = "最新單季EPS";
      wrap.appendChild(h2);
      const grid = document.createElement("div");
      grid.className = "ref-grid";
      const items = [
        ["期別", `${eps.eps_year}年 Q${eps.eps_quarter}`],
        ["基本每股盈餘(元)", `<span class="${eps.eps > 0 ? "up" : eps.eps < 0 ? "down" : ""}">${fmtNum(eps.eps, 2)}</span>`],
      ];
      for (const [label, value] of items) {
        const item = document.createElement("div");
        item.className = "ref-item";
        item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
        grid.appendChild(item);
      }
      wrap.appendChild(grid);
    } else {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "查無單季EPS資料（金融/證券/保險業不在此份彙總表內）";
      wrap.appendChild(p);
    }

    const h3 = document.createElement("h4");
    h3.textContent = "本益比河流圖（合理價格帶）";
    wrap.appendChild(h3);

    if (peBand.error) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = peBand.error;
      wrap.appendChild(p);
    } else {
      const note = document.createElement("p");
      note.className = "note";
      note.innerHTML = `用<strong>${escapeHtml(name)}</strong>自己過去的本益比區間（25% / 50% / 75% 分位數）× 目前隱含EPS（近四季，用「目前股價 ÷ 目前本益比」反推，` +
        `因為證交所本來就是用近四季EPS算本益比）算出的歷史相對價格帶。<strong>這是用這檔股票自己的估值歷史區間當參考，不是絕對合理值，更不是預測未來股價</strong>，` +
        `公司體質、產業展望改變時這個區間本身也會跟著改變，請自行判斷風險。`;
      wrap.appendChild(note);

      const grid = document.createElement("div");
      grid.className = "ref-grid";
      const posClass = peBand.current_price > peBand.fair_price_high ? "up"
        : peBand.current_price < peBand.fair_price_low ? "down" : "";
      const items = [
        ["目前股價", `<span class="${posClass}">${fmtNum(peBand.current_price, 1)}</span>`],
        ["目前本益比", fmtNum(peBand.current_pe, 2)],
        ["隱含EPS(近四季)", fmtNum(peBand.current_eps_ttm, 2)],
        ["歷史本益比 25%/50%/75%", `${fmtNum(peBand.pe_low, 1)} / ${fmtNum(peBand.pe_mid, 1)} / ${fmtNum(peBand.pe_high, 1)}`],
        ["合理價格帶(低)", fmtNum(peBand.fair_price_low, 1)],
        ["合理價格帶(中)", fmtNum(peBand.fair_price_mid, 1)],
        ["合理價格帶(高)", fmtNum(peBand.fair_price_high, 1)],
      ];
      for (const [label, value] of items) {
        const item = document.createElement("div");
        item.className = "ref-item";
        item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
        grid.appendChild(item);
      }
      wrap.appendChild(grid);

      const legend = document.createElement("div");
      legend.className = "pe-band-legend";
      legend.innerHTML = `
        <div class="item"><span class="swatch" style="background:var(--up)"></span>實際股價</div>
        <div class="item"><span class="swatch" style="background:#a855f7"></span>合理價格帶(高，75%分位)</div>
        <div class="item"><span class="swatch" style="background:var(--series-1)"></span>合理價格帶(中，50%分位)</div>
        <div class="item"><span class="swatch" style="background:#e08a1e"></span>合理價格帶(低，25%分位)</div>
      `;
      wrap.appendChild(legend);
      const chartWrap = document.createElement("div");
      chartWrap.innerHTML = buildPeBandSvg(peBand.series, peBand.fair_price_low, peBand.fair_price_mid, peBand.fair_price_high);
      wrap.appendChild(chartWrap);
    }

    const h4 = document.createElement("h4");
    h4.textContent = "近期重大訊息公告";
    wrap.appendChild(h4);
    const miNote = document.createElement("p");
    miNote.className = "note";
    miNote.textContent = "資料來源是公開資訊觀測站經證交所整理的開放資料，只涵蓋最近一個交易日的公告批次，不是完整新聞來源，也不含上櫃公司——大部分股票大部分時候會是空的，這是正常現象。";
    wrap.appendChild(miNote);
    if (!data.material_info.length) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "最近一個交易日沒有這檔股票的重大訊息公告";
      wrap.appendChild(p);
    } else {
      const table = document.createElement("table");
      table.innerHTML = `
        <tbody>
          ${data.material_info.map((m) => `
            <tr>
              <td class="mi-date">${escapeHtml(m.date)}<br>${escapeHtml(m.time)}</td>
              <td>${escapeHtml(m.subject)}</td>
            </tr>
          `).join("")}
        </tbody>
      `;
      wrap.appendChild(table);
    }

    const disclaimer = document.createElement("p");
    disclaimer.className = "disclaimer";
    disclaimer.textContent = "以上全部是用已知公開資料計算的客觀統計，不構成投資建議，請自行判斷風險。";
    wrap.appendChild(disclaimer);

    return wrap;
  }

  $("#fundamentalsBtn").addEventListener("click", async () => {
    const container = document.createElement("div");
    if (state.selectedIsIndex || !state.selectedCode) {
      container.innerHTML = `<p class="empty">請先從觀察清單、選股結果或市場總覽點選一檔個股（不支援大盤指數）</p>`;
      openModal("基本面分析", container);
      return;
    }
    const name = state.selectedName || state.selectedCode;
    container.innerHTML = `<p class="empty"><span class="spinner"></span>分析基本面中…（本益比河流圖要抓兩年的歷史資料，可能需要 10-20 秒）</p>`;
    openModal(`基本面分析：${name}`, container);
    try {
      const res = await fetch(`/api/fundamentals?code=${encodeURIComponent(state.selectedCode)}&months=24`);
      const data = await res.json();
      if (modalBody.firstElementChild !== container) return;
      container.innerHTML = "";
      container.appendChild(buildFundamentalsContent(data, name));
    } catch (err) {
      console.error(err);
      if (modalBody.firstElementChild === container) {
        container.innerHTML = `<p class="empty">載入失敗，請稍後再試</p>`;
      }
    }
  });

