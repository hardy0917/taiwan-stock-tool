  // ---------- 個股日內模式分析（近20日，統計參考，不是預測）----------
  function buildPatternSvgChart(avgPath) {
    const ns = "http://www.w3.org/2000/svg";
    const W = 700, H = 200, padL = 40, padR = 10, padT = 10, padB = 22;
    const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("style", "width:100%; height:200px; display:block; overflow:visible");

    const allVals = avgPath.flatMap((p) => [p.min_pct, p.max_pct, p.avg_pct]);
    let min = Math.min(...allVals, 0), max = Math.max(...allVals, 0);
    if (min === max) { min -= 1; max += 1; }
    const pad = (max - min) * 0.1;
    min -= pad; max += pad;
    const xAt = (i) => x0 + (i / (avgPath.length - 1)) * (x1 - x0);
    const yAt = (v) => y1 - ((v - min) / (max - min)) * (y1 - y0);

    const g = document.createElementNS(ns, "g");

    // y 軸格線與標籤
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = min + ((max - min) * i) / steps;
      const y = yAt(v);
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", x0); line.setAttribute("x2", x1);
      line.setAttribute("y1", y); line.setAttribute("y2", y);
      line.setAttribute("class", Math.abs(v) < 1e-6 ? "baseline" : "gridline");
      g.appendChild(line);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", x0 - 6); label.setAttribute("y", y + 3);
      label.setAttribute("text-anchor", "end"); label.setAttribute("class", "axis-label");
      label.textContent = `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
      g.appendChild(label);
    }
    // x 軸時間標籤（每3個時段標一次）
    avgPath.forEach((p, i) => {
      if (i % 3 !== 0 && i !== avgPath.length - 1) return;
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", xAt(i)); label.setAttribute("y", y1 + 15);
      label.setAttribute("text-anchor", "middle"); label.setAttribute("class", "axis-label");
      label.textContent = p.time;
      g.appendChild(label);
    });

    // 每日高低變異帶
    const bandPoints = avgPath.map((p, i) => `${xAt(i)},${yAt(p.max_pct)}`)
      .concat(avgPath.slice().reverse().map((p, i) => `${xAt(avgPath.length - 1 - i)},${yAt(p.min_pct)}`));
    const band = document.createElementNS(ns, "polygon");
    band.setAttribute("points", bandPoints.join(" "));
    band.setAttribute("class", "boll-fill");
    g.appendChild(band);

    // 平均走勢線
    const linePoints = avgPath.map((p, i) => `${xAt(i)},${yAt(p.avg_pct)}`).join(" ");
    const line = document.createElementNS(ns, "polyline");
    line.setAttribute("points", linePoints);
    line.setAttribute("class", "ma20-line");
    g.appendChild(line);

    svg.appendChild(g);
    return svg;
  }

  function buildHistRows(histogram, maxCount, isLow) {
    const wrap = document.createElement("div");
    for (const item of histogram) {
      const row = document.createElement("div");
      row.className = "hist-row";
      const label = document.createElement("div");
      label.className = "hist-label";
      label.textContent = item.period;
      const track = document.createElement("div");
      track.className = "hist-track";
      const fill = document.createElement("div");
      fill.className = "hist-fill" + (isLow ? " low" : "");
      fill.style.width = maxCount > 0 ? `${(item.count / maxCount) * 100}%` : "0%";
      track.appendChild(fill);
      const count = document.createElement("div");
      count.className = "hist-count";
      count.textContent = item.count;
      row.append(label, track, count);
      wrap.appendChild(row);
    }
    return wrap;
  }

  function buildIntradayPatternContent(data, code, name) {
    const wrap = document.createElement("div");
    wrap.className = "pattern-modal";

    const note = document.createElement("p");
    note.className = "note";
    note.innerHTML =
      `以下是 <strong>${escapeHtml(name)}（${escapeHtml(code)}）近 ${data.days_analyzed} 個交易日</strong>的日內走勢統計整理——` +
      `全部是「過去已經發生過的事」的客觀彙整，<strong>不是對明天的預測，也不保證未來會重複同樣模式</strong>。` +
      `樣本數只有 ${data.days_analyzed} 天，個股走勢隨時可能改變，當沖風險本來就高，請自行判斷風險，不要當成勝率保證。`;
    wrap.appendChild(note);

    if (!data.avg_path || !data.avg_path.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "資料不足，無法統計（可能是新上市或近期交易日太少）";
      wrap.appendChild(empty);
      return wrap;
    }

    const h1 = document.createElement("h4");
    h1.textContent = "平均日內走勢（灰色區間＝每日高低變異範圍）";
    wrap.appendChild(h1);
    const chartWrap = document.createElement("div");
    chartWrap.className = "pattern-svg-wrap";
    chartWrap.appendChild(buildPatternSvgChart(data.avg_path));
    wrap.appendChild(chartWrap);

    const h2 = document.createElement("h4");
    h2.textContent = "當日最高點常出現的時段";
    wrap.appendChild(h2);
    const maxHighCount = Math.max(...data.high_time_histogram.map((h) => h.count), 1);
    wrap.appendChild(buildHistRows(data.high_time_histogram, maxHighCount, false));

    const h3 = document.createElement("h4");
    h3.textContent = "當日最低點常出現的時段";
    wrap.appendChild(h3);
    const maxLowCount = Math.max(...data.low_time_histogram.map((h) => h.count), 1);
    wrap.appendChild(buildHistRows(data.low_time_histogram, maxLowCount, true));

    const h4 = document.createElement("h4");
    h4.textContent = "開盤跳空與回補";
    wrap.appendChild(h4);
    const g = data.gap_stats;
    const grid = document.createElement("div");
    grid.className = "ref-grid";
    const items = [
      ["跳空上漲天數", `${g.gap_up_days} 天`],
      ["跳空上漲當日回補比例", g.gap_up_filled_pct != null ? `${g.gap_up_filled_pct}%` : "-"],
      ["跳空下跌天數", `${g.gap_down_days} 天`],
      ["跳空下跌當日回補比例", g.gap_down_filled_pct != null ? `${g.gap_down_filled_pct}%` : "-"],
      ["平均跳空幅度", g.avg_abs_gap_pct != null ? `${g.avg_abs_gap_pct}%` : "-"],
    ];
    for (const [label, value] of items) {
      const item = document.createElement("div");
      item.className = "ref-item";
      item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
      grid.appendChild(item);
    }
    wrap.appendChild(grid);

    return wrap;
  }

  $("#intradayPatternBtn").addEventListener("click", async () => {
    const container = document.createElement("div");
    if (state.selectedIsIndex || !state.selectedCode) {
      container.innerHTML = `<p class="empty">請先從觀察清單或選股結果點選一檔個股（指數目前不支援此分析）</p>`;
      openModal("日內模式分析", container);
      return;
    }
    const code = state.selectedCode;
    const name = state.selectedName || code;
    container.innerHTML = `<p class="empty"><span class="spinner"></span>統計近20個交易日資料中…</p>`;
    openModal(`日內模式分析：${name}（${code}）`, container);
    try {
      const res = await fetch(`/api/intraday_pattern?code=${encodeURIComponent(code)}`);
      const data = await res.json();
      if (modalBody.firstElementChild !== container) return; // 使用者已關閉或切換
      container.innerHTML = "";
      if (data.error) {
        container.innerHTML = `<p class="empty">查無足夠的日內資料，無法統計</p>`;
        return;
      }
      container.appendChild(buildIntradayPatternContent(data, code, name));
    } catch (err) {
      console.error(err);
      if (modalBody.firstElementChild === container) {
        container.innerHTML = `<p class="empty">載入失敗，請稍後再試</p>`;
      }
    }
  });

