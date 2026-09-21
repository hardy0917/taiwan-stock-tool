  // ---------- market overview table ----------
  function parseDayAll(raw) {
    return raw.map((r) => {
      const close = parseFloat(r.ClosingPrice);
      const change = parseFloat(r.Change);
      const base = close - change;
      const changePct = base ? (change / base) * 100 : 0;
      return {
        Code: r.Code,
        Name: r.Name,
        ClosingPrice: close,
        Change: change,
        ChangePct: changePct,
        OpeningPrice: parseFloat(r.OpeningPrice),
        HighestPrice: parseFloat(r.HighestPrice),
        LowestPrice: parseFloat(r.LowestPrice),
        TradeVolume: parseFloat(r.TradeVolume),
      };
    }).filter((r) => !Number.isNaN(r.ClosingPrice) && r.ClosingPrice > 0);
  }

  async function loadDayAll() {
    tableBody.innerHTML = `<tr><td colspan="8" class="empty">載入中…</td></tr>`;
    try {
      const res = await fetch("/api/day_all");
      const data = await res.json();
      state.allRows = parseDayAll(data.data || []);
      renderTable();
    } catch (err) {
      tableBody.innerHTML = `<tr><td colspan="8" class="empty">載入失敗</td></tr>`;
      console.error(err);
    }
  }

  function renderTable() {
    let rows = state.allRows;
    const q = searchInput.value.trim().toLowerCase();
    if (q) {
      rows = rows.filter((r) => r.Code.toLowerCase().includes(q) || r.Name.toLowerCase().includes(q));
    }

    if (state.chip === "attention" || state.chip === "disposition") {
      const set = state.chip === "attention" ? state.attentionSet : state.dispositionSet;
      if (!set) {
        tableBody.innerHTML = `<tr><td colspan="8" class="empty">載入中…</td></tr>`;
        return;
      }
      rows = rows.filter((r) => set.has(r.Code));
      if (q) rows = rows.filter((r) => r.Code.toLowerCase().includes(q) || r.Name.toLowerCase().includes(q));
    } else if (state.sortKey) {
      rows = [...rows].sort((a, b) => (a[state.sortKey] - b[state.sortKey]) * state.sortDir);
      rows = rows.slice(0, 100);
    } else if (!q) {
      if (state.chip === "volume") {
        rows = [...rows].sort((a, b) => b.TradeVolume - a.TradeVolume).slice(0, 20);
      } else if (state.chip === "gainers") {
        rows = [...rows].sort((a, b) => b.ChangePct - a.ChangePct).slice(0, 20);
      } else if (state.chip === "losers") {
        rows = [...rows].sort((a, b) => a.ChangePct - b.ChangePct).slice(0, 20);
      }
    } else {
      rows = rows.slice(0, 100);
    }

    tableBody.innerHTML = "";
    if (!rows.length) {
      const msg = state.chip === "attention" ? "今日無注意股公告"
        : state.chip === "disposition" ? "目前無處置股公告"
        : "查無資料";
      tableBody.innerHTML = `<tr><td colspan="8" class="empty">${msg}</td></tr>`;
      return;
    }
    for (const r of rows) {
      const tr = document.createElement("tr");
      const cells = [
        r.Code,
        r.Name,
        fmtNum(r.ClosingPrice),
        null, // changePct, special
        fmtNum(r.OpeningPrice),
        fmtNum(r.HighestPrice),
        fmtNum(r.LowestPrice),
        fmtVolume(r.TradeVolume),
      ];
      cells.forEach((val, i) => {
        const td = document.createElement("td");
        if (i === 3) {
          td.className = directionClass(r.ChangePct);
          td.textContent = `${directionArrow(r.ChangePct)} ${fmtNum(Math.abs(r.ChangePct))}%`;
        } else {
          td.textContent = val;
        }
        tr.appendChild(td);
      });
      tr.addEventListener("click", () => selectStock(r.Code, r.Name));
      tableBody.appendChild(tr);
    }
  }

  async function ensureAttentionLoaded() {
    if (state.attentionSet) return;
    const res = await fetch("/api/attention");
    const data = await res.json();
    state.attentionSet = new Set(data.data || []);
    if (state.chip === "attention") renderTable();
  }

  async function ensureDispositionLoaded() {
    if (state.dispositionSet) return;
    const res = await fetch("/api/disposition");
    const data = await res.json();
    const map = new Set((data.data || []).map((d) => d.code));
    state.dispositionSet = map;
    if (state.chip === "disposition") renderTable();
  }

  document.querySelectorAll(".chips button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".chips button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.chip = btn.dataset.filter;
      state.sortKey = null;
      if (state.chip === "attention") ensureAttentionLoaded();
      if (state.chip === "disposition") ensureDispositionLoaded();
      renderTable();
    });
  });

  document.querySelectorAll("thead th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDir *= -1;
      } else {
        state.sortKey = key;
        state.sortDir = -1;
      }
      document.querySelectorAll("thead th").forEach((h) => h.classList.remove("sorted"));
      th.classList.add("sorted");
      renderTable();
    });
  });

  searchInput.addEventListener("input", renderTable);

  $("#refreshBtn").addEventListener("click", () => {
    refreshQuotes();
    loadIndices();
    loadHomeTreemap();
    if (marketLoaded) loadDayAll();
    if (sectorLoaded) loadSectorFlow();
    if (state.selectedCode) loadChart(state.selectedCode);
  });

