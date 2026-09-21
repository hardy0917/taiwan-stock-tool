  // ---------- K棒型態分析（多空型態辨識＋量價分析，個股／指數都支援）----------
  function buildPatternAnalysisContent(data, name) {
    const wrap = document.createElement("div");
    wrap.className = "pattern-modal";

    const note = document.createElement("p");
    note.className = "note";
    note.innerHTML =
      `以下是對<strong>${escapeHtml(name)}</strong>最近K線的技術型態辨識與量價分析——全部是對「已經發生的K棒」做客觀分類，` +
      `型態本身在傳統技術分析裡代表什麼意思會如實說明，但<strong>不是對明天走勢的預測</strong>，請自行判斷風險。`;
    wrap.appendChild(note);

    if (data.volume) {
      const h1 = document.createElement("h4");
      h1.textContent = "近期量價關係";
      wrap.appendChild(h1);
      const grid = document.createElement("div");
      grid.className = "ref-grid";
      const v = data.volume;
      const items = [
        ["量價分類", escapeHtml(v.label)],
        ["近5日漲跌", `${v.price_chg_5_pct > 0 ? "+" : ""}${v.price_chg_5_pct}%`],
        ["近5日均量 vs 近20日均量", `${v.vol_ratio_pct > 0 ? "+" : ""}${v.vol_ratio_pct}%（${escapeHtml(v.vol_trend)}）`],
      ];
      for (const [label, value] of items) {
        const item = document.createElement("div");
        item.className = "ref-item";
        item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
        grid.appendChild(item);
      }
      wrap.appendChild(grid);
      const desc = document.createElement("p");
      desc.className = "note";
      desc.textContent = v.desc;
      wrap.appendChild(desc);
    }

    const h2 = document.createElement("h4");
    h2.textContent = "偵測到的K棒型態（近5個交易日）";
    wrap.appendChild(h2);
    if (!data.patterns || !data.patterns.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "近5個交易日沒有偵測到明確定義的型態";
      wrap.appendChild(empty);
    } else {
      for (const p of data.patterns) {
        const row = document.createElement("div");
        row.className = "candle-pattern-row";
        const dateEl = document.createElement("div");
        dateEl.className = "cp-date";
        dateEl.textContent = p.date;
        const nameEl = document.createElement("div");
        nameEl.className = `cp-name ${p.bias}`;
        nameEl.textContent = p.name;
        const descEl = document.createElement("div");
        descEl.className = "cp-desc";
        descEl.textContent = p.desc;
        row.append(dateEl, nameEl, descEl);
        wrap.appendChild(row);
      }
    }

    return wrap;
  }

  $("#patternAnalysisBtn").addEventListener("click", async () => {
    const container = document.createElement("div");
    if (!state.selectedIsIndex && !state.selectedCode) {
      container.innerHTML = `<p class="empty">請先從觀察清單、選股結果或大盤指數點選一個標的</p>`;
      openModal("K棒型態分析", container);
      return;
    }
    const isIndex = state.selectedIsIndex;
    const name = state.selectedName || (isIndex ? state.selectedIndexKey : state.selectedCode);
    const qs = isIndex
      ? `key=${encodeURIComponent(state.selectedIndexKey)}`
      : `code=${encodeURIComponent(state.selectedCode)}`;
    container.innerHTML = `<p class="empty"><span class="spinner"></span>分析K棒型態中…</p>`;
    openModal(`K棒型態分析：${name}`, container);
    try {
      const res = await fetch(`/api/pattern_analysis?${qs}`);
      const data = await res.json();
      if (modalBody.firstElementChild !== container) return; // 使用者已關閉或切換
      container.innerHTML = "";
      container.appendChild(buildPatternAnalysisContent(data, name));
    } catch (err) {
      console.error(err);
      if (modalBody.firstElementChild === container) {
        container.innerHTML = `<p class="empty">載入失敗，請稍後再試</p>`;
      }
    }
  });

