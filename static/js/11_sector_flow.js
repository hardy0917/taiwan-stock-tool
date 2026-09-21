  // ---------- 產業資金流向 ----------
  const sectorFlowBody = $("#sectorFlowBody");
  const sectorFlowStatus = $("#sectorFlowStatus");
  const sectorFlowTable = $("#sectorFlowTable");

  function renderSectorFlow(rows) {
    sectorFlowBody.innerHTML = "";
    const maxAbs = Math.max(...rows.map((r) => Math.abs(r.value_weighted_change_pct)), 1);
    for (const r of rows) {
      const tr = document.createElement("tr");

      const nameTd = document.createElement("td");
      nameTd.style.textAlign = "left";
      nameTd.textContent = r.industry;
      tr.appendChild(nameTd);

      const barTd = document.createElement("td");
      barTd.style.textAlign = "left";
      const track = document.createElement("div");
      track.className = "flow-bar-track";
      const mid = document.createElement("div");
      mid.className = "flow-bar-mid";
      const fill = document.createElement("div");
      const widthPct = (Math.abs(r.value_weighted_change_pct) / maxAbs) * 50;
      fill.className = "flow-bar-fill " + (r.value_weighted_change_pct >= 0 ? "pos" : "neg");
      fill.style.width = widthPct + "%";
      track.append(mid, fill);
      barTd.appendChild(track);
      tr.appendChild(barTd);

      const pctTd = document.createElement("td");
      pctTd.className = directionClass(r.value_weighted_change_pct);
      pctTd.textContent = `${directionArrow(r.value_weighted_change_pct)} ${fmtNum(Math.abs(r.value_weighted_change_pct))}%`;
      tr.appendChild(pctTd);

      tr.appendChild((() => { const td = document.createElement("td"); td.textContent = r.advance; return td; })());
      tr.appendChild((() => { const td = document.createElement("td"); td.textContent = r.decline; return td; })());
      tr.appendChild((() => { const td = document.createElement("td"); td.textContent = r.stock_count; return td; })());
      tr.appendChild((() => { const td = document.createElement("td"); td.textContent = fmtNum(r.total_value_billion); return td; })());

      tr.addEventListener("click", () => {
        closeModal();
        document.querySelectorAll("#industryFilter option").forEach((opt) => {
          if (opt.value === r.industry) industryFilter.value = r.industry;
        });
        if (industryFilter.value === r.industry) { screenerPage = 1; renderScreenerTable(); }
        openScreenerModal();
      });
      sectorFlowBody.appendChild(tr);
    }
  }

  let sectorFlowRows = [];
  let sectorFlowSortKey = "value_weighted_change_pct";
  let sectorFlowSortDir = -1;

  function renderSectorFlowSorted() {
    const sorted = [...sectorFlowRows].sort((a, b) => {
      const av = a[sectorFlowSortKey], bv = b[sectorFlowSortKey];
      if (typeof av === "string") return av.localeCompare(bv, "zh-Hant") * sectorFlowSortDir;
      return (av - bv) * sectorFlowSortDir;
    });
    renderSectorFlow(sorted);
  }

  async function loadSectorFlow() {
    sectorFlowStatus.textContent = "載入中…";
    sectorFlowStatus.style.display = "block";
    sectorFlowTable.style.display = "none";
    sectorTreemapStatus.textContent = "載入中…";
    sectorTreemapStatus.style.display = "block";
    try {
      const res = await fetch("/api/sector_flow");
      const data = await res.json();
      sectorFlowRows = data.data || [];
      if (!sectorFlowRows.length) {
        sectorFlowStatus.textContent = "查無資料";
        sectorTreemapStatus.textContent = "查無資料";
        return;
      }
      renderSectorFlowSorted();
      sectorFlowStatus.style.display = "none";
      sectorFlowTable.style.display = "table";
      renderSectorTreemap(sectorFlowRows);
    } catch (err) {
      sectorFlowStatus.textContent = "載入失敗";
      sectorTreemapStatus.textContent = "載入失敗";
      console.error(err);
    }
  }

  $("#refreshSectorBtn").addEventListener("click", () => {
    loadSectorFlow();
    if (sectorHeatmapLoaded) loadSectorHeatmap();
  });

  document.querySelectorAll("#sectorFlowTable thead th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (sectorFlowSortKey === key) {
        sectorFlowSortDir *= -1;
      } else {
        sectorFlowSortKey = key;
        sectorFlowSortDir = -1;
      }
      document.querySelectorAll("#sectorFlowTable thead th").forEach((h) => h.classList.remove("sorted"));
      th.classList.add("sorted");
      renderSectorFlowSorted();
    });
  });

  // ---------- 產業資金流向：20日熱力圖 ----------
  const sectorHeatmapStatus = $("#sectorHeatmapStatus");
  const sectorHeatmapScroll = $("#sectorHeatmapScroll");
  let sectorHeatmapLoaded = false;

  function heatCellStyle(pct, maxAbs) {
    if (pct === null || pct === undefined) return "";
    const alpha = maxAbs > 0 ? Math.min(1, Math.abs(pct) / maxAbs) * 0.8 + 0.08 : 0.08;
    const rgb = pct >= 0 ? "208,59,59" : "12,163,12";
    return `background: rgba(${rgb}, ${alpha.toFixed(2)});`;
  }

  function renderSectorHeatmap(data) {
    const { dates, rows } = data;
    if (!dates.length || !rows.length) {
      sectorHeatmapStatus.textContent = "目前還沒有累積到任何快照，稍後（或明天）再回來看看";
      sectorHeatmapStatus.style.display = "block";
      sectorHeatmapScroll.innerHTML = "";
      return;
    }
    sectorHeatmapStatus.style.display = "none";

    const allChanges = rows.flatMap((r) => r.changes).filter((v) => v !== null && v !== undefined);
    const maxAbs = Math.max(...allChanges.map(Math.abs), 1);

    const table = document.createElement("table");
    table.className = "heatmap-table";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.innerHTML = `<th class="heatmap-industry">產業別</th>` +
      dates.map((d) => `<th>${escapeHtml(d.split("/").slice(1).join("/"))}</th>`).join("");
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      nameTd.className = "heatmap-industry";
      nameTd.textContent = r.industry;
      nameTd.addEventListener("click", () => {
        closeModal();
        document.querySelectorAll("#industryFilter option").forEach((opt) => {
          if (opt.value === r.industry) industryFilter.value = r.industry;
        });
        if (industryFilter.value === r.industry) { screenerPage = 1; renderScreenerTable(); }
        openScreenerModal();
      });
      tr.appendChild(nameTd);
      r.changes.forEach((pct) => {
        const td = document.createElement("td");
        td.className = "heatmap-cell" + (pct === null || pct === undefined ? " empty-cell" : "");
        td.setAttribute("style", heatCellStyle(pct, maxAbs));
        td.textContent = pct === null || pct === undefined ? "-" : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    sectorHeatmapScroll.innerHTML = "";
    sectorHeatmapScroll.appendChild(table);
  }

  async function loadSectorHeatmap() {
    sectorHeatmapStatus.textContent = "載入中…";
    sectorHeatmapStatus.style.display = "block";
    try {
      const res = await fetch("/api/sector_flow_history");
      const data = await res.json();
      renderSectorHeatmap(data);
    } catch (err) {
      sectorHeatmapStatus.textContent = "載入失敗";
      console.error(err);
    }
  }

  // ---------- 產業資金流向：今日熱力圖（面積=成交值、顏色=漲跌幅，類似股市大盤熱力圖）----------
  const sectorTreemapStatus = $("#sectorTreemapStatus");
  const sectorTreemapLegend = $("#sectorTreemapLegend");
  const sectorTreemapWrap = $("#sectorTreemapWrap");

  // 簡化版樹狀圖（binary treemap）：每次把目前這組項目依累計值切成盡量對半的
  // 兩組，沿著長邊切一刀分配對應比例的寬/高，兩組各自遞迴——不是最嚴謹的
  // squarified treemap，但實作簡單、格子形狀也夠方正，足夠給人一眼看出大小對比。
  function computeTreemap(items, x, y, w, h) {
    if (!items.length) return [];
    if (items.length === 1) return [{ item: items[0], x, y, w, h }];
    const total = items.reduce((s, it) => s + it.value, 0);
    if (total <= 0) return [];
    let cum = 0, splitAt = 1, bestDiff = Infinity;
    for (let i = 0; i < items.length - 1; i++) {
      cum += items[i].value;
      const diff = Math.abs(cum - total / 2);
      if (diff < bestDiff) { bestDiff = diff; splitAt = i + 1; }
    }
    const groupA = items.slice(0, splitAt);
    const groupB = items.slice(splitAt);
    const sumA = groupA.reduce((s, it) => s + it.value, 0);
    const fracA = sumA / total;
    if (w >= h) {
      const wA = w * fracA;
      return [...computeTreemap(groupA, x, y, wA, h), ...computeTreemap(groupB, x + wA, y, w - wA, h)];
    }
    const hA = h * fracA;
    return [...computeTreemap(groupA, x, y, w, hA), ...computeTreemap(groupB, x, y + hA, w, h - hA)];
  }

  const TREEMAP_SCALE_PCT = 6; // 顏色深淺對應的漲跌幅上限，超過這個幅度一律用最深的顏色
  function treemapColor(pct) {
    const clamped = Math.max(-TREEMAP_SCALE_PCT, Math.min(TREEMAP_SCALE_PCT, pct));
    const alpha = 0.25 + (Math.abs(clamped) / TREEMAP_SCALE_PCT) * 0.65;
    const rgb = pct >= 0 ? "208,59,59" : "12,163,12";
    return `rgba(${rgb}, ${alpha.toFixed(2)})`;
  }

  function renderTreemapLegend(legendEl) {
    const steps = [-6, -3, -1, 1, 3, 6];
    legendEl.innerHTML = "圖例：" + steps.map((pct) =>
      `<span class="chip" style="background:${treemapColor(pct)}">${pct > 0 ? "+" : ""}${pct}%</span>`
    ).join("");
  }

  // wrapEl/legendEl/statusEl：同一套渲染邏輯要同時給彈窗裡的大版跟首頁的精簡版用，
  // 所以目標容器一律當參數傳進來，不寫死抓固定的 DOM 節點。
  function renderSectorTreemapInto(rows, wrapEl, legendEl, statusEl) {
    if (!rows.length) {
      if (statusEl) { statusEl.textContent = "查無資料"; statusEl.style.display = "block"; }
      wrapEl.innerHTML = "";
      return;
    }
    if (statusEl) statusEl.style.display = "none";
    renderTreemapLegend(legendEl);

    const items = [...rows]
      .filter((r) => r.total_value_billion > 0)
      .sort((a, b) => b.total_value_billion - a.total_value_billion)
      .map((r) => ({ value: r.total_value_billion, row: r }));

    const W = 1000, H = 460;
    const placed = computeTreemap(items, 0, 0, W, H);

    wrapEl.innerHTML = "";
    for (const { item, x, y, w, h } of placed) {
      const r = item.row;
      const cell = document.createElement("div");
      cell.className = "treemap-cell";
      cell.style.left = `${(x / W) * 100}%`;
      cell.style.top = `${(y / H) * 100}%`;
      cell.style.width = `${(w / W) * 100}%`;
      cell.style.height = `${(h / H) * 100}%`;
      cell.style.background = treemapColor(r.value_weighted_change_pct);
      cell.title = `${r.industry}：${r.value_weighted_change_pct > 0 ? "+" : ""}${fmtNum(r.value_weighted_change_pct)}%・成交值 ${fmtNum(r.total_value_billion, 1)} 億`;

      // 格子太小的時候文字會爆版，依格子面積決定要不要顯示文字、字要多大
      const areaPx = (w / W) * wrapEl.clientWidth * (h / H) * wrapEl.clientHeight;
      if (w > 28 && h > 22) {
        const nameSize = Math.max(10, Math.min(16, Math.sqrt(Math.max(areaPx, 0)) / 8));
        const name = document.createElement("div");
        name.className = "tc-name";
        name.style.fontSize = `${nameSize}px`;
        name.textContent = r.industry;
        cell.appendChild(name);
        if (h > 34) {
          const pctEl = document.createElement("div");
          pctEl.className = "tc-pct";
          pctEl.style.fontSize = `${Math.max(9, nameSize - 3)}px`;
          pctEl.textContent = `${r.value_weighted_change_pct > 0 ? "+" : ""}${fmtNum(r.value_weighted_change_pct)}%`;
          cell.appendChild(pctEl);
        }
      }

      cell.addEventListener("click", () => openSectorStocksModal(r.industry));
      wrapEl.appendChild(cell);
    }
  }

  function renderSectorTreemap(rows) {
    renderSectorTreemapInto(rows, sectorTreemapWrap, sectorTreemapLegend, sectorTreemapStatus);
  }

  // ---------- 首頁精簡版熱力圖（不用開彈窗就能看，跟指數列一樣是常駐資訊） ----------
  const homeTreemapStatus = $("#homeTreemapStatus");
  const homeTreemapLegend = $("#homeTreemapLegend");
  const homeTreemapWrap = $("#homeTreemapWrap");

  async function loadHomeTreemap() {
    if (!homeTreemapWrap) return;
    try {
      const res = await fetch("/api/sector_flow");
      const data = await res.json();
      renderSectorTreemapInto(data.data || [], homeTreemapWrap, homeTreemapLegend, homeTreemapStatus);
    } catch (err) {
      if (homeTreemapStatus) { homeTreemapStatus.textContent = "載入失敗"; homeTreemapStatus.style.display = "block"; }
      console.error("loadHomeTreemap failed", err);
    }
  }

  // 首頁熱力圖的高度不用固定比例（vh），改成量實際剩下多少空間就用多少——
  // 不管視窗大小、字型渲染差異，都保證整頁塞得進一個畫面，不用捲動。
  function fitHomeTreemapHeight() {
    if (!homeTreemapWrap) return;
    const footer = document.querySelector("footer");
    if (!footer) return;
    // 先把熱力圖收到 0，量出「扣掉熱力圖本身，其他東西（header/nav/card padding/
    // footer/body 下邊界）總共要佔多少高度」，剩下的空間才是熱力圖能用的高度。
    // 這樣量出來的一定是實際數字，不用去猜每一層 padding/margin 各多少、也不會有
    // 「改高度會影響量測結果」的循環依賴問題。這個 0px 狀態只存在於同一個同步的
    // JS 執行過程中，瀏覽器不會真的畫出來，使用者不會看到閃爍。
    homeTreemapWrap.style.height = "0px";
    const bodyPaddingBottom = parseFloat(getComputedStyle(document.body).paddingBottom) || 0;
    // getBoundingClientRect() 是相對「目前視窗」的位置，如果頁面當下剛好有捲動
    // （例如上一輪算錯導致跑出捲軸），量出來的值會不準，所以要加回目前的捲動距離，
    // 換算成「相對頁面最上面」的絕對位置，才不會因為捲動位置不同而算錯。
    const footerBottomAbs = footer.getBoundingClientRect().bottom + window.scrollY;
    const staticHeight = footerBottomAbs + bodyPaddingBottom;
    const available = window.innerHeight - staticHeight - 16; // 16px 留白
    homeTreemapWrap.style.height = `${Math.max(200, Math.min(620, available))}px`;
  }
  let fitTreemapTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(fitTreemapTimer);
    fitTreemapTimer = setTimeout(fitHomeTreemapHeight, 150);
  });

  function showSectorView(view) {
    const views = { treemap: "#sectorTreemapView", today: "#sectorTodayView", heatmap: "#sectorHeatmapView" };
    const btns = { treemap: "#sectorViewTreemapBtn", today: "#sectorViewTodayBtn", heatmap: "#sectorViewHeatmapBtn" };
    for (const key of Object.keys(views)) {
      $(views[key]).style.display = key === view ? "" : "none";
      $(btns[key]).classList.toggle("active", key === view);
    }
    if (view === "heatmap" && !sectorHeatmapLoaded) { sectorHeatmapLoaded = true; loadSectorHeatmap(); }
  }
  $("#sectorViewTreemapBtn").addEventListener("click", () => showSectorView("treemap"));
  $("#sectorViewTodayBtn").addEventListener("click", () => showSectorView("today"));
  $("#sectorViewHeatmapBtn").addEventListener("click", () => showSectorView("heatmap"));

