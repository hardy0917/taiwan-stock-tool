  // ---------- chart ----------
  const PAD = { top: 16, right: 12, bottom: 24, left: 48 };
  const VB_W = 900, VB_H = 260;

  function plotArea() {
    return {
      x0: PAD.left, x1: VB_W - PAD.right,
      y0: PAD.top, y1: VB_H - PAD.bottom,
    };
  }

  function parseHistoryRows(rows) {
    // TWSE STOCK_DAY row: [日期(民國), 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌價差, 成交筆數, 註記]
    return rows.map((r) => {
      const [rocDate, volume, , open, high, low, close] = r;
      const [y, m, d] = rocDate.split("/").map(Number);
      const date = new Date(y + 1911, m - 1, d);
      const num = (v) => parseFloat(String(v).replace(/,/g, ""));
      return {
        date,
        open: num(open),
        high: num(high),
        low: num(low),
        close: num(close),
        volume: num(volume),
      };
    }).filter((p) => !Number.isNaN(p.close) && !Number.isNaN(p.open));
  }

  function withMovingAverages(points) {
    const closes = points.map((p) => p.close);
    const maAt = (i, period) => {
      if (i < period - 1) return null;
      let sum = 0;
      for (let k = i - period + 1; k <= i; k++) sum += closes[k];
      return sum / period;
    };
    const BOLL_PERIOD = 20, BOLL_K = 2;
    const bollAt = (i) => {
      if (i < BOLL_PERIOD - 1) return { upper: null, lower: null };
      const slice = closes.slice(i - BOLL_PERIOD + 1, i + 1);
      const mean = slice.reduce((a, b) => a + b, 0) / BOLL_PERIOD;
      const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / BOLL_PERIOD;
      const sd = Math.sqrt(variance);
      return { upper: mean + BOLL_K * sd, lower: mean - BOLL_K * sd };
    };
    return points.map((p, i) => {
      const boll = bollAt(i);
      return {
        ...p,
        ma5: maAt(i, 5),
        ma20: maAt(i, 20),
        ma60: maAt(i, 60),
        bollUpper: boll.upper,
        bollLower: boll.lower,
      };
    });
  }

  const SERIES = [
    { key: "ma5", label: "週線（5日均線）", cssVar: "--ma5" },
    { key: "ma20", label: "月線（20日均線）", cssVar: "--ma20" },
    { key: "ma60", label: "季線（60日均線）", cssVar: "--ma60" },
  ];

  function renderChartLegend() {
    const legend = $("#chartLegend");
    legend.innerHTML = "";

    const candleUp = document.createElement("div");
    candleUp.className = "item";
    const swUp = document.createElement("span");
    swUp.className = "swatch block";
    swUp.style.background = "var(--up)";
    candleUp.append(swUp, document.createTextNode("上漲"));
    legend.appendChild(candleUp);

    const candleDown = document.createElement("div");
    candleDown.className = "item";
    const swDown = document.createElement("span");
    swDown.className = "swatch block";
    swDown.style.background = "var(--down)";
    candleDown.append(swDown, document.createTextNode("下跌"));
    legend.appendChild(candleDown);

    for (const s of SERIES) {
      const item = document.createElement("div");
      item.className = "item";
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = `var(${s.cssVar})`;
      const label = document.createElement("span");
      label.textContent = s.label;
      item.append(sw, label);
      legend.appendChild(item);
    }

    if (state.showBollinger) {
      const item = document.createElement("div");
      item.className = "item";
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = "var(--text-muted)";
      sw.style.opacity = "0.85";
      const label = document.createElement("span");
      label.textContent = "布林通道（20,2）";
      item.append(sw, label);
      legend.appendChild(item);
    }
  }

  let chartPoints = [];

  function buildPath(points, xAt, yAt, key) {
    let d = "";
    let drawing = false;
    points.forEach((p, i) => {
      const v = p[key];
      if (v === null || v === undefined || Number.isNaN(v)) { drawing = false; return; }
      d += (drawing ? "L " : "M ") + xAt(i) + " " + yAt(v) + " ";
      drawing = true;
    });
    return d;
  }

  function drawChart(points) {
    chartPoints = points;
    svg.innerHTML = "";
    if (!points.length) {
      chartMeta.textContent = "查無歷史資料";
      return;
    }
    // 上方畫K線+均線，下方留一段畫成交量柱狀圖，共用同一個 x 軸
    const x0 = PAD.left, x1 = VB_W - PAD.right;
    const y0 = PAD.top, y1 = 168;       // 價格區
    const volY0 = 178, volY1 = 214;     // 成交量區
    const labelY = 232;

    const allValues = [];
    points.forEach((p) => {
      allValues.push(p.high, p.low);
      for (const s of SERIES) if (p[s.key] != null) allValues.push(p[s.key]);
      if (state.showBollinger) {
        if (p.bollUpper != null) allValues.push(p.bollUpper);
        if (p.bollLower != null) allValues.push(p.bollLower);
      }
    });
    let min = Math.min(...allValues), max = Math.max(...allValues);
    if (min === max) { min -= 1; max += 1; }
    const pad = (max - min) * 0.08;
    min -= pad; max += pad;

    const maxVol = Math.max(...points.map((p) => p.volume || 0), 1);

    const xAt = (i) => x0 + (points.length === 1 ? 0 : (i / (points.length - 1)) * (x1 - x0));
    const yAt = (v) => y1 - ((v - min) / (max - min)) * (y1 - y0);
    const volYAt = (v) => volY1 - (v / maxVol) * (volY1 - volY0);

    const ns = "http://www.w3.org/2000/svg";
    const g = document.createElementNS(ns, "g");

    // gridlines + axis labels (4 bands)，只在價格區畫
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = min + ((max - min) * i) / steps;
      const y = yAt(v);
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", x0); line.setAttribute("x2", x1);
      line.setAttribute("y1", y); line.setAttribute("y2", y);
      line.setAttribute("class", i === 0 ? "baseline" : "gridline");
      g.appendChild(line);

      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", x0 - 8);
      label.setAttribute("y", y + 3);
      label.setAttribute("text-anchor", "end");
      label.setAttribute("class", "axis-label");
      label.textContent = fmtNum(v);
      g.appendChild(label);
    }

    // 成交量區的頂線 + 標籤
    const volTopLine = document.createElementNS(ns, "line");
    volTopLine.setAttribute("x1", x0); volTopLine.setAttribute("x2", x1);
    volTopLine.setAttribute("y1", volY1); volTopLine.setAttribute("y2", volY1);
    volTopLine.setAttribute("class", "baseline");
    g.appendChild(volTopLine);
    const volLabel = document.createElementNS(ns, "text");
    volLabel.setAttribute("x", x0 - 8); volLabel.setAttribute("y", volY0 + 8);
    volLabel.setAttribute("text-anchor", "end"); volLabel.setAttribute("class", "axis-label");
    volLabel.textContent = "成交量";
    g.appendChild(volLabel);

    // x-axis date labels (first, middle, last)
    [0, Math.floor((points.length - 1) / 2), points.length - 1].forEach((i) => {
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", xAt(i));
      label.setAttribute("y", labelY);
      label.setAttribute("text-anchor", i === 0 ? "start" : i === points.length - 1 ? "end" : "middle");
      label.setAttribute("class", "axis-label");
      const d = points[i].date;
      label.textContent = `${d.getMonth() + 1}/${d.getDate()}`;
      g.appendChild(label);
    });

    // 布林通道（選用）：畫在K線後面當背景帶狀
    if (state.showBollinger) {
      const upperD = buildPath(points, xAt, yAt, "bollUpper");
      const lowerD = buildPath(points, xAt, yAt, "bollLower");
      const firstIdx = points.findIndex((p) => p.bollUpper != null && p.bollLower != null);
      if (firstIdx >= 0) {
        let fillPath = `M ${xAt(firstIdx)} ${yAt(points[firstIdx].bollUpper)} `;
        for (let i = firstIdx; i < points.length; i++) {
          if (points[i].bollUpper == null) break;
          fillPath += `L ${xAt(i)} ${yAt(points[i].bollUpper)} `;
        }
        for (let i = points.length - 1; i >= firstIdx; i--) {
          if (points[i].bollLower == null) continue;
          fillPath += `L ${xAt(i)} ${yAt(points[i].bollLower)} `;
        }
        fillPath += "Z";
        const fill = document.createElementNS(ns, "path");
        fill.setAttribute("d", fillPath);
        fill.setAttribute("class", "boll-fill");
        g.appendChild(fill);
      }
      if (upperD) {
        const upperPath = document.createElementNS(ns, "path");
        upperPath.setAttribute("d", upperD);
        upperPath.setAttribute("class", "boll-line");
        g.appendChild(upperPath);
      }
      if (lowerD) {
        const lowerPath = document.createElementNS(ns, "path");
        lowerPath.setAttribute("d", lowerD);
        lowerPath.setAttribute("class", "boll-line");
        g.appendChild(lowerPath);
      }
    }

    // K 線（紅漲綠跌）+ 成交量柱
    const slotW = (x1 - x0) / points.length;
    const candleW = Math.max(1.5, Math.min(slotW * 0.6, 14));
    points.forEach((p, i) => {
      const cx = xAt(i);
      const dir = p.close > p.open ? "up" : p.close < p.open ? "down" : "flat";
      const wick = document.createElementNS(ns, "line");
      wick.setAttribute("x1", cx); wick.setAttribute("x2", cx);
      wick.setAttribute("y1", yAt(p.high)); wick.setAttribute("y2", yAt(p.low));
      wick.setAttribute("class", "candle-wick " + dir);
      wick.setAttribute("stroke-width", "1");
      g.appendChild(wick);

      const bodyTop = yAt(Math.max(p.open, p.close));
      const bodyBottom = yAt(Math.min(p.open, p.close));
      const body = document.createElementNS(ns, "rect");
      body.setAttribute("x", cx - candleW / 2);
      body.setAttribute("y", bodyTop);
      body.setAttribute("width", candleW);
      body.setAttribute("height", Math.max(1, bodyBottom - bodyTop));
      body.setAttribute("class", "candle-body " + dir);
      g.appendChild(body);

      if (p.volume) {
        const volBar = document.createElementNS(ns, "rect");
        volBar.setAttribute("x", cx - candleW / 2);
        volBar.setAttribute("y", volYAt(p.volume));
        volBar.setAttribute("width", candleW);
        volBar.setAttribute("height", Math.max(1, volY1 - volYAt(p.volume)));
        volBar.setAttribute("class", "candle-body " + dir);
        volBar.setAttribute("opacity", "0.55");
        g.appendChild(volBar);
      }
    });

    // 3 條均線
    const lineClasses = { ma5: "ma5-line", ma20: "ma20-line", ma60: "ma60-line" };
    for (const s of SERIES) {
      const d = buildPath(points, xAt, yAt, s.key);
      if (!d) continue;
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      path.setAttribute("class", lineClasses[s.key]);
      path.setAttribute("stroke-linecap", "round");
      g.appendChild(path);
    }

    // crosshair (hidden until hover)，貫穿價格區與成交量區
    const crosshair = document.createElementNS(ns, "line");
    crosshair.setAttribute("y1", y0); crosshair.setAttribute("y2", volY1);
    crosshair.setAttribute("class", "crosshair");
    crosshair.style.display = "none";
    crosshair.id = "crosshairLine";
    g.appendChild(crosshair);

    // hit rect
    const hitRect = document.createElementNS(ns, "rect");
    hitRect.setAttribute("x", x0); hitRect.setAttribute("y", y0);
    hitRect.setAttribute("width", x1 - x0); hitRect.setAttribute("height", volY1 - y0);
    hitRect.setAttribute("fill", "transparent");
    hitRect.id = "hitRect";
    g.appendChild(hitRect);

    svg.appendChild(g);

    hitRect.addEventListener("pointermove", (e) => onHover(e, xAt, yAt));
    hitRect.addEventListener("pointerleave", hideHover);
  }

  function onHover(evt, xAt, yAt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    const { x0, x1 } = plotArea();
    const ratio = Math.min(1, Math.max(0, (svgP.x - x0) / (x1 - x0)));
    const idx = Math.round(ratio * (chartPoints.length - 1));
    const p = chartPoints[idx];
    if (!p) return;

    const cx = xAt(idx);
    const crosshair = $("#crosshairLine");
    crosshair.setAttribute("x1", cx); crosshair.setAttribute("x2", cx);
    crosshair.style.display = "block";

    tooltip.style.display = "block";

    const dateStr = p.date.toLocaleDateString("zh-TW", { year: "numeric", month: "2-digit", day: "2-digit" });
    tooltip.innerHTML = "";
    const dEl = document.createElement("div");
    dEl.className = "t-date";
    dEl.textContent = dateStr;
    tooltip.appendChild(dEl);

    const ohlcRow = document.createElement("div");
    ohlcRow.className = "t-row";
    ohlcRow.style.gap = "10px";
    const dir = p.close > p.open ? "up" : p.close < p.open ? "down" : "flat";
    const ohlcEl = document.createElement("span");
    ohlcEl.className = directionClass(dir === "up" ? 1 : dir === "down" ? -1 : 0);
    ohlcEl.textContent = `開${fmtNum(p.open)} 高${fmtNum(p.high)} 低${fmtNum(p.low)} 收${fmtNum(p.close)}`;
    ohlcRow.appendChild(ohlcEl);
    tooltip.appendChild(ohlcRow);

    if (p.volume) {
      const volRow = document.createElement("div");
      volRow.className = "t-row";
      const volEl = document.createElement("span");
      volEl.className = "key";
      volEl.textContent = `量 ${fmtVolume(p.volume)}`;
      volRow.appendChild(volEl);
      tooltip.appendChild(volRow);
    }

    for (const s of SERIES) {
      const v = p[s.key];
      if (v == null) continue;
      const row = document.createElement("div");
      row.className = "t-row";
      const keyEl = document.createElement("span");
      keyEl.className = "key";
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = `var(${s.cssVar})`;
      const label = document.createElement("span");
      label.textContent = s.label;
      keyEl.append(sw, label);
      const valEl = document.createElement("span");
      valEl.className = "val";
      valEl.textContent = fmtNum(v);
      row.append(keyEl, valEl);
      tooltip.appendChild(row);
    }

    if (state.showBollinger && p.bollUpper != null) {
      const bollRow = document.createElement("div");
      bollRow.className = "t-row";
      const bollKey = document.createElement("span");
      bollKey.className = "key";
      bollKey.textContent = "布林上/下軌";
      const bollVal = document.createElement("span");
      bollVal.className = "val";
      bollVal.textContent = `${fmtNum(p.bollUpper)} / ${fmtNum(p.bollLower)}`;
      bollRow.append(bollKey, bollVal);
      tooltip.appendChild(bollRow);
    }

    // 內容塞好、量出實際寬度後，依游標在圖表左半或右半決定貼在哪一側，
    // 避免提示框剛好蓋住滑鼠正在指的那根K棒
    const wrapRect = $("#chartWrap").getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const screenX = svgRect.left + (cx / VB_W) * svgRect.width - wrapRect.left;
    const tw = tooltip.offsetWidth;
    const onRightHalf = ratio > 0.5;
    let left = onRightHalf ? screenX - tw - 14 : screenX + 14;
    left = Math.max(4, Math.min(left, wrapRect.width - tw - 4));
    tooltip.style.left = left + "px";
    tooltip.style.top = "8px";
  }

  function hideHover() {
    const crosshair = $("#crosshairLine");
    const hoverDot = $("#hoverDot");
    if (crosshair) crosshair.style.display = "none";
    if (hoverDot) hoverDot.style.display = "none";
    tooltip.style.display = "none";
  }

  const TRADING_DAYS_PER_MONTH = 21;
  const MA_BUFFER_MONTHS = 3; // 多抓 3 個月，確保季線（60日均線）在顯示區間一開始就有值

  async function loadChart(code) {
    chartTitle.textContent = `${state.selectedName || code} (${code}) 技術分析圖`;
    chartMeta.textContent = "載入中…";
    $("#analysisPanel").style.display = "none";
    try {
      const fetchMonths = state.months + MA_BUFFER_MONTHS;
      const res = await fetch(`/api/history?code=${encodeURIComponent(code)}&months=${fetchMonths}`);
      const data = await res.json();
      const allPoints = withMovingAverages(parseHistoryRows(data.rows || []));
      const displayCount = state.months * TRADING_DAYS_PER_MONTH;
      const points = allPoints.slice(-displayCount);

      renderChartLegend();
      drawChart(points);
      renderAnalysisPanel(points, code);

      if (points.length) {
        const first = points[0].close, last = points[points.length - 1].close;
        const pct = ((last - first) / first) * 100;
        chartMeta.innerHTML = "";
        const span = document.createElement("span");
        span.className = directionClass(pct);
        span.textContent = `區間 ${directionArrow(pct)} ${fmtNum(Math.abs(pct))}%`;
        chartMeta.appendChild(span);
      } else {
        chartMeta.textContent = "查無歷史資料";
      }
    } catch (err) {
      chartMeta.textContent = "載入失敗";
      console.error(err);
    }
  }

  async function loadIndexChart(key, name) {
    state.selectedIsIndex = true;
    state.selectedIndexKey = key;
    state.selectedCode = null;
    state.selectedName = name;
    state.viewMode = "daily";
    document.querySelectorAll(".ranges button").forEach((b) => b.classList.remove("active"));
    document.querySelector(`.ranges button[data-months="${state.months}"]`)?.classList.add("active");
    renderTiles();

    chartTitle.textContent = `${name} 走勢圖`;
    chartMeta.textContent = "載入中…";
    $("#analysisPanel").style.display = "none";
    try {
      const fetchMonths = state.months + MA_BUFFER_MONTHS;
      const res = await fetch(`/api/index_history?key=${encodeURIComponent(key)}&months=${fetchMonths}`);
      const data = await res.json();
      const allPoints = withMovingAverages(parseHistoryRows(data.rows || []));
      const displayCount = state.months * TRADING_DAYS_PER_MONTH;
      const points = allPoints.slice(-displayCount);

      renderChartLegend();
      drawChart(points);

      if (points.length) {
        const last = points[points.length - 1];
        const first = points[0].close;
        const pct = ((last.close - first) / first) * 100;
        const dateStr = last.date.toLocaleDateString("zh-TW", { year: "numeric", month: "2-digit", day: "2-digit" });
        chartMeta.innerHTML = "";
        chartMeta.appendChild(document.createTextNode(`最後收盤日 ${dateStr}：${fmtNum(last.close)}　`));
        const span = document.createElement("span");
        span.className = directionClass(pct);
        span.textContent = `區間 ${directionArrow(pct)} ${fmtNum(Math.abs(pct))}%`;
        chartMeta.appendChild(span);
      } else {
        chartMeta.textContent = "查無歷史資料";
      }
    } catch (err) {
      chartMeta.textContent = "載入失敗";
      console.error(err);
    }
  }

  function computeVolumeBias(points, days) {
    if (points.length < days + 1) return null;
    let upVol = 0, downVol = 0;
    for (let i = points.length - days; i < points.length; i++) {
      const c = points[i].close, prevC = points[i - 1].close, v = points[i].volume;
      if (c == null || prevC == null || !v) continue;
      if (c > prevC) upVol += v;
      else if (c < prevC) downVol += v;
    }
    const total = upVol + downVol;
    if (total <= 0) return null;
    return ((upVol - downVol) / total) * 100;
  }

  function chipBiasLabel(v) {
    if (v == null) return "資料不足";
    if (v > 15) return "偏多（量能集中在上漲日）";
    if (v < -15) return "偏空（量能集中在下跌日）";
    return "中性";
  }

  async function renderAnalysisPanel(points, code) {
    const panel = $("#analysisPanel");
    const last = points[points.length - 1];
    if (!last || last.ma60 == null) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "block";
    panel.innerHTML = "";

    const close = last.close, ma5 = last.ma5, ma20 = last.ma20, ma60 = last.ma60;

    // 排列狀態
    let alignClass = "align-mixed", alignText = "均線糾結，方向不明確";
    if (ma5 > ma20 && ma20 > ma60) { alignClass = "align-bull"; alignText = "均線多頭排列（週線 > 月線 > 季線）"; }
    else if (ma5 < ma20 && ma20 < ma60) { alignClass = "align-bear"; alignText = "均線空頭排列（週線 < 月線 < 季線）"; }

    const badge = document.createElement("span");
    badge.className = `align-badge ${alignClass}`;
    badge.textContent = alignText;
    panel.appendChild(badge);

    // 近期低點（近 20 個交易日），作為出場停損參考
    const lookback = points.slice(-20);
    const recentLow = Math.min(...lookback.map((p) => p.low ?? p.close));

    const chipBias5 = computeVolumeBias(points, 5);
    const chipBias20 = computeVolumeBias(points, 20);

    // 參考價位卡片
    const refGrid = document.createElement("div");
    refGrid.className = "ref-grid";
    const refs = [
      { label: "目前收盤", value: fmtNum(close) },
      { label: "週線（5日均線）", value: fmtNum(ma5) },
      { label: "月線（20日均線）", value: fmtNum(ma20) },
      { label: "季線（60日均線）", value: fmtNum(ma60) },
      { label: "近5日籌碼傾向", value: chipBiasLabel(chipBias5) },
      { label: "近20日籌碼傾向", value: chipBiasLabel(chipBias20) },
    ];
    for (const r of refs) {
      const item = document.createElement("div");
      item.className = "ref-item";
      const l = document.createElement("div");
      l.className = "label";
      l.textContent = r.label;
      const v = document.createElement("div");
      v.className = "value";
      v.textContent = r.value;
      item.append(l, v);
      refGrid.appendChild(item);
    }
    panel.appendChild(refGrid);

    // 大戶（1,000張以上）持股人數 —— 集保股權分散表，每週更新，非同步補上
    const holderNote = document.createElement("p");
    holderNote.className = "note";
    holderNote.style.margin = "10px 0 0";
    holderNote.textContent = "大戶（1,000張以上）持股人數：載入中…";
    panel.appendChild(holderNote);
    fetch(`/api/holders?code=${encodeURIComponent(code)}`)
      .then((res) => res.json())
      .then((h) => {
        if (h.error || h.holders_1000 == null) {
          holderNote.textContent = "大戶（1,000張以上）持股人數：查無資料";
          return;
        }
        const chg = h.holders_1000_change;
        holderNote.textContent = "";
        holderNote.appendChild(document.createTextNode("大戶（1,000張以上）持股人數："));
        const strong = document.createElement("strong");
        strong.textContent = `${h.holders_1000} 人`;
        holderNote.appendChild(strong);
        holderNote.appendChild(document.createTextNode(`（${h.report_date} 集保週報）`));
        if (chg != null) {
          holderNote.appendChild(document.createTextNode(` （較上次 ${h.prev_report_date} `));
          const chgSpan = document.createElement("span");
          chgSpan.className = chg > 0 ? "pos" : chg < 0 ? "neg" : "flat";
          chgSpan.textContent = `${chg > 0 ? "+" : ""}${chg} 人`;
          holderNote.appendChild(chgSpan);
          holderNote.appendChild(document.createTextNode("）"));
        } else {
          holderNote.appendChild(document.createTextNode("（集保每週五更新，這是本工具目前看到的最新一期，還沒跨過下一次更新，暫時沒有比較基準，不是資料錯誤）"));
        }

        if (chipBias20 != null && chipBias20 < -10 && chg != null && chg < 0) {
          const warn = document.createElement("div");
          warn.className = "align-badge align-bear";
          warn.style.marginTop = "8px";
          warn.textContent = "⚠ 出貨風險提示：近20日量能偏空 + 大戶人數減少，留意乖離過大時追高風險";
          panel.insertBefore(warn, panel.children[1]);
        }
      })
      .catch(() => { holderNote.textContent = "大戶（1,000張以上）持股人數：載入失敗"; });

    // 進場／出場技術參考文字（條件式描述，非投資建議）
    const note = document.createElement("div");
    note.className = "note";
    const supportRef = close > ma20 ? ma20 : ma60;
    const supportLabel = close > ma20 ? "月線" : "季線";
    const entryText = ma5 > ma20 && ma20 > ma60
      ? `目前均線多頭排列，股價站上月線。技術面常見的參考做法是：拉回不破${supportLabel}（約 ${fmtNum(supportRef)} 元）視為偏多訊號延續，可作為進場觀察的參考位置；追價則需留意乖離過大拉回的風險。`
      : `目前均線排列不是標準多頭（週線／月線／季線未呈現由上到下排列），若要參考進場，通常會等站上月線且均線轉為多頭排列後再觀察，而非現在追高。`;
    const exitText = `技術面常見的出場／停損參考：① 收盤價跌破月線（約 ${fmtNum(ma20)} 元）；② 月線由上揚轉為走平或下彎；③ 跌破近 20 個交易日低點（約 ${fmtNum(recentLow)} 元）。三者任一出現，通常視為轉弱訊號，可作為停損或減碼的參考依據。`;
    note.appendChild(document.createTextNode("進場參考："));
    const p1 = document.createElement("p");
    p1.style.margin = "4px 0 10px";
    p1.textContent = entryText;
    note.appendChild(p1);
    note.appendChild(document.createTextNode("出場／停損參考："));
    const p2 = document.createElement("p");
    p2.style.margin = "4px 0 0";
    p2.textContent = exitText;
    note.appendChild(p2);
    panel.appendChild(note);

    const disclaimer = document.createElement("div");
    disclaimer.className = "disclaimer";
    disclaimer.textContent = "以上為根據歷史股價客觀計算之技術指標參考，非投資建議、亦非對未來走勢的預測，請自行評估風險。";
    panel.appendChild(disclaimer);
  }

  function minutesSinceOpen(timeStr) {
    const parts = timeStr.split(":").map(Number);
    const h = parts[0], m = parts[1] || 0;
    return (h * 60 + m) - (9 * 60);
  }

  async function renderIntradayChart() {
    const code = state.selectedCode;
    chartTitle.textContent = `${state.selectedName || code} (${code}) 分時走勢`;
    $("#analysisPanel").style.display = "none";
    $("#chartLegend").innerHTML = "";
    svg.innerHTML = "";
    chartMeta.textContent = "載入中…";

    let data;
    try {
      const res = await fetch(`/api/intraday?code=${encodeURIComponent(code)}`);
      data = await res.json();
    } catch (err) {
      chartMeta.textContent = "載入失敗";
      console.error(err);
      return;
    }
    if (state.viewMode !== "intraday" || state.selectedCode !== code) return; // 使用者已切換，結果過期

    const points = data.points || [];
    if (points.length < 2) {
      chartMeta.textContent = "查無最近交易日的分時資料（可能代碼查無資料，或已收盤超過快取時間）";
      return;
    }

    if (data.trade_date) {
      const todayStr = new Date().toLocaleDateString("sv-SE"); // yyyy-mm-dd
      const label = data.trade_date === todayStr
        ? "今日"
        : `最近交易日 ${data.trade_date.slice(5).replace("-", "/")} `;
      chartTitle.textContent = `${state.selectedName || code} (${code}) ${label}分時走勢`;
    }

    const { x0, x1, y0, y1 } = plotArea();
    const TRADING_MINUTES = 270; // 9:00-13:30
    const xAt = (p) => x0 + Math.min(1, Math.max(0, minutesSinceOpen(p.time) / TRADING_MINUTES)) * (x1 - x0);
    const prices = points.map((p) => p.price);
    if (data.prev_close) prices.push(data.prev_close);
    let min = Math.min(...prices), max = Math.max(...prices);
    if (min === max) { min -= 1; max += 1; }
    const pad = (max - min) * 0.1;
    min -= pad; max += pad;
    const yAt = (v) => y1 - ((v - min) / (max - min)) * (y1 - y0);

    const ns = "http://www.w3.org/2000/svg";
    const g = document.createElementNS(ns, "g");

    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = min + ((max - min) * i) / steps;
      const y = yAt(v);
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", x0); line.setAttribute("x2", x1);
      line.setAttribute("y1", y); line.setAttribute("y2", y);
      line.setAttribute("class", i === 0 ? "baseline" : "gridline");
      g.appendChild(line);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", x0 - 8); label.setAttribute("y", y + 3);
      label.setAttribute("text-anchor", "end"); label.setAttribute("class", "axis-label");
      label.textContent = fmtNum(v);
      g.appendChild(label);
    }
    ["09:00", "10:30", "12:00", "13:30"].forEach((t, i) => {
      const x = x0 + (i / 3) * (x1 - x0);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", x); label.setAttribute("y", y1 + 16);
      label.setAttribute("text-anchor", i === 0 ? "start" : i === 3 ? "end" : "middle");
      label.setAttribute("class", "axis-label");
      label.textContent = t;
      g.appendChild(label);
    });

    if (data.prev_close) {
      const py = yAt(data.prev_close);
      const refLine = document.createElementNS(ns, "line");
      refLine.setAttribute("x1", x0); refLine.setAttribute("x2", x1);
      refLine.setAttribute("y1", py); refLine.setAttribute("y2", py);
      refLine.setAttribute("class", "crosshair");
      g.appendChild(refLine);
      const refLabel = document.createElementNS(ns, "text");
      refLabel.setAttribute("x", x1); refLabel.setAttribute("y", py - 4);
      refLabel.setAttribute("text-anchor", "end"); refLabel.setAttribute("class", "axis-label");
      refLabel.textContent = `昨收 ${fmtNum(data.prev_close)}`;
      g.appendChild(refLabel);
    }

    let areaPath = `M ${xAt(points[0])} ${y1} `;
    points.forEach((p) => { areaPath += `L ${xAt(p)} ${yAt(p.price)} `; });
    areaPath += `L ${xAt(points[points.length - 1])} ${y1} Z`;
    const area = document.createElementNS(ns, "path");
    area.setAttribute("d", areaPath); area.setAttribute("class", "price-area");
    g.appendChild(area);

    let linePath = "";
    points.forEach((p, i) => { linePath += (i === 0 ? "M " : "L ") + xAt(p) + " " + yAt(p.price) + " "; });
    const line = document.createElementNS(ns, "path");
    line.setAttribute("d", linePath);
    line.setAttribute("stroke", "var(--series-1)");
    line.setAttribute("stroke-width", "2");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke-linecap", "round");
    g.appendChild(line);

    const last = points[points.length - 1];
    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", xAt(last)); dot.setAttribute("cy", yAt(last.price));
    dot.setAttribute("r", 4); dot.setAttribute("class", "end-dot");
    g.appendChild(dot);

    const hitRect = document.createElementNS(ns, "rect");
    hitRect.setAttribute("x", x0); hitRect.setAttribute("y", y0);
    hitRect.setAttribute("width", x1 - x0); hitRect.setAttribute("height", y1 - y0);
    hitRect.setAttribute("fill", "transparent");
    g.appendChild(hitRect);
    hitRect.addEventListener("pointermove", (evt) => {
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
      const ratio = Math.min(1, Math.max(0, (svgP.x - x0) / (x1 - x0)));
      const targetMin = ratio * TRADING_MINUTES;
      let nearest = points[0];
      for (const p of points) {
        if (Math.abs(minutesSinceOpen(p.time) - targetMin) < Math.abs(minutesSinceOpen(nearest.time) - targetMin)) nearest = p;
      }
      tooltip.style.display = "block";
      tooltip.innerHTML = "";
      const dEl = document.createElement("div");
      dEl.className = "t-date";
      dEl.textContent = nearest.time.slice(0, 5);
      const vEl = document.createElement("div");
      vEl.className = "t-row";
      const valSpan = document.createElement("span");
      valSpan.className = "val";
      valSpan.textContent = fmtNum(nearest.price);
      vEl.appendChild(valSpan);
      tooltip.append(dEl, vEl);

      const wrapRect = $("#chartWrap").getBoundingClientRect();
      const svgRect = svg.getBoundingClientRect();
      const screenX = svgRect.left + (xAt(nearest) / VB_W) * svgRect.width - wrapRect.left;
      const tw = tooltip.offsetWidth;
      const onRightHalf = ratio > 0.5;
      let left = onRightHalf ? screenX - tw - 14 : screenX + 14;
      left = Math.max(4, Math.min(left, wrapRect.width - tw - 4));
      tooltip.style.left = left + "px";
      tooltip.style.top = "8px";
    });
    hitRect.addEventListener("pointerleave", () => { tooltip.style.display = "none"; });

    svg.appendChild(g);

    const base = data.prev_close || points[0].price;
    const pct = ((last.price - base) / base) * 100;
    chartMeta.innerHTML = "";
    const span = document.createElement("span");
    span.className = directionClass(pct);
    span.textContent = `${directionArrow(pct)} ${fmtNum(Math.abs(pct))}%（較昨收，資料來源 Yahoo Finance，每 30 秒更新一次快取）`;
    chartMeta.appendChild(span);
  }

  function selectStock(code, name) {
    closeModal();
    state.selectedCode = code;
    state.selectedName = name;
    state.selectedIsIndex = false;
    state.selectedIndexKey = null;
    renderTiles();
    openChartModal();
    if (state.viewMode === "intraday") renderIntradayChart();
    else loadChart(code);
  }

  // 區間按鈕的月數階梯，滑鼠滾輪縮放時也沿用同一組數值（1個月～20年）
  const RANGE_LADDER = [1, 2, 3, 6, 12, 24, 36, 60, 120, 240];

  function monthsLabel(m) {
    if (m < 12) return `${m}個月`;
    const y = m / 12;
    return `${Number.isInteger(y) ? y : y.toFixed(1)}年`;
  }

  function applyRangeButtons() {
    document.querySelectorAll(".ranges button[data-months]").forEach((b) => {
      b.classList.toggle("active", parseInt(b.dataset.months, 10) === state.months);
    });
    $("#intradayBtn").classList.remove("active");
  }

  function switchToMonths(months) {
    state.viewMode = "daily";
    state.months = months;
    applyRangeButtons();
    if (state.selectedIsIndex) loadIndexChart(state.selectedIndexKey, state.selectedName);
    else if (state.selectedCode) loadChart(state.selectedCode);
  }

  document.querySelectorAll(".ranges button[data-months]").forEach((btn) => {
    btn.addEventListener("click", () => switchToMonths(parseInt(btn.dataset.months, 10)));
  });

  // 在走勢圖上滾滑鼠滾輪可以連續縮放時間區間，不用一直找按鈕點
  const rangeHint = $("#rangeHint");
  let wheelAccum = 0;
  let wheelHideTimer = null;
  let wheelFetchTimer = null;

  $("#chartWrap").addEventListener("wheel", (e) => {
    if (state.viewMode === "intraday" || (!state.selectedCode && !state.selectedIsIndex)) return;
    e.preventDefault();
    wheelAccum += e.deltaY;
    const STEP = 60;
    if (Math.abs(wheelAccum) < STEP) return;
    const dir = wheelAccum > 0 ? 1 : -1; // 往下滾＝拉長區間，往上滾＝縮短
    wheelAccum = 0;

    let idx = RANGE_LADDER.reduce((closest, v, i) =>
      Math.abs(v - state.months) < Math.abs(RANGE_LADDER[closest] - state.months) ? i : closest, 0);
    idx = Math.min(RANGE_LADDER.length - 1, Math.max(0, idx + dir));
    const months = RANGE_LADDER[idx];
    if (months === state.months) return;

    state.months = months;
    state.viewMode = "daily";
    applyRangeButtons();
    rangeHint.textContent = monthsLabel(months);
    rangeHint.style.display = "block";
    clearTimeout(wheelHideTimer);
    clearTimeout(wheelFetchTimer);
    wheelFetchTimer = setTimeout(() => {
      if (state.selectedIsIndex) loadIndexChart(state.selectedIndexKey, state.selectedName);
      else if (state.selectedCode) loadChart(state.selectedCode);
      wheelHideTimer = setTimeout(() => { rangeHint.style.display = "none"; }, 1200);
    }, 250);
  }, { passive: false });

  $("#intradayBtn").addEventListener("click", () => {
    if (state.selectedIsIndex) return; // 指數目前不支援分時走勢
    document.querySelectorAll(".ranges button").forEach((b) => b.classList.remove("active"));
    $("#intradayBtn").classList.add("active");
    state.viewMode = "intraday";
    if (state.selectedCode) renderIntradayChart();
  });

  $("#bollingerToggle").addEventListener("change", (e) => {
    state.showBollinger = e.target.checked;
    if (state.selectedIsIndex) loadIndexChart(state.selectedIndexKey, state.selectedName);
    else if (state.selectedCode && state.viewMode === "daily") loadChart(state.selectedCode);
  });

