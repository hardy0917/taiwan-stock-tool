  // ---------- 個股策略回測 ----------
  function backtestFieldsHtml(strategy) {
    if (strategy === "ma_cross") {
      return `
        <div class="bt-field"><label for="btShortPeriod">短均線(根)</label><input type="number" id="btShortPeriod" value="5" min="2" max="120" step="1"></div>
        <div class="bt-field"><label for="btLongPeriod">長均線(根)</label><input type="number" id="btLongPeriod" value="20" min="3" max="240" step="1"></div>
      `;
    }
    if (strategy === "bollinger") {
      return `
        <div class="bt-field"><label for="btBollPeriod">布林週期(根)</label><input type="number" id="btBollPeriod" value="20" min="5" max="120" step="1"></div>
        <div class="bt-field"><label for="btBollK">布林倍數(k)</label><input type="number" id="btBollK" value="2" min="0.5" max="4" step="0.1"></div>
      `;
    }
    if (strategy === "breakout") {
      return `<div class="bt-field"><label for="btBreakoutPeriod">突破週期(根)</label><input type="number" id="btBreakoutPeriod" value="20" min="5" max="120" step="1"></div>`;
    }
    if (strategy === "macd") {
      return `
        <div class="bt-field"><label for="btMacdFast">快線EMA</label><input type="number" id="btMacdFast" value="12" min="2" max="60" step="1"></div>
        <div class="bt-field"><label for="btMacdSlow">慢線EMA</label><input type="number" id="btMacdSlow" value="26" min="3" max="120" step="1"></div>
        <div class="bt-field"><label for="btMacdSignal">訊號線EMA</label><input type="number" id="btMacdSignal" value="9" min="2" max="60" step="1"></div>
      `;
    }
    if (strategy === "kd") {
      return `
        <div class="bt-field"><label for="btKdPeriod">KD週期(根)</label><input type="number" id="btKdPeriod" value="9" min="3" max="60" step="1"></div>
        <div class="bt-field"><label for="btKdOversold">超賣門檻(&lt;)</label><input type="number" id="btKdOversold" value="20" min="5" max="40" step="1"></div>
        <div class="bt-field"><label for="btKdOverbought">超買門檻(&gt;)</label><input type="number" id="btKdOverbought" value="80" min="60" max="95" step="1"></div>
      `;
    }
    return `
      <div class="bt-field"><label for="btRsiPeriod">RSI週期(根)</label><input type="number" id="btRsiPeriod" value="14" min="3" max="60" step="1"></div>
      <div class="bt-field"><label for="btRsiBuy">買進門檻(&lt;)</label><input type="number" id="btRsiBuy" value="30" min="5" max="45" step="1"></div>
      <div class="bt-field"><label for="btRsiSell">賣出門檻(&gt;)</label><input type="number" id="btRsiSell" value="70" min="55" max="95" step="1"></div>
    `;
  }

  function backtestRangeFieldHtml(timeframe) {
    if (timeframe === "60m") {
      return `
        <div class="bt-field">
          <label for="btDays">回測天數（60分K，Yahoo最長約2年）</label>
          <select id="btDays">
            <option value="90">90天</option>
            <option value="180" selected>180天</option>
            <option value="365">365天</option>
            <option value="729">2年（上限）</option>
          </select>
        </div>`;
    }
    if (timeframe === "5m") {
      return `
        <div class="bt-field">
          <label for="btDays">回測天數（5分K，Yahoo最長約60天）</label>
          <select id="btDays">
            <option value="10">10天</option>
            <option value="20" selected>20天</option>
            <option value="30">30天</option>
            <option value="59">60天（上限）</option>
          </select>
        </div>`;
    }
    return `
      <div class="bt-field">
        <label for="btMonths">回測期間</label>
        <select id="btMonths">
          <option value="6">6個月</option>
          <option value="12">1年</option>
          <option value="24" selected>2年</option>
          <option value="36">3年</option>
          <option value="60">5年</option>
          <option value="120">10年</option>
        </select>
      </div>`;
  }

  function buildBacktestContainer() {
    const wrap = document.createElement("div");
    wrap.className = "backtest-modal";
    wrap.innerHTML = `
      <div class="bt-form">
        <div class="bt-field">
          <label for="btStrategy">策略</label>
          <select id="btStrategy">
            <option value="ma_cross">均線黃金/死亡交叉</option>
            <option value="bollinger">布林通道回歸（John Bollinger）</option>
            <option value="breakout">唐奇安通道突破（海龜交易法則）</option>
            <option value="macd">MACD 指標交叉（Gerald Appel）</option>
            <option value="kd">KD 隨機指標（George Lane）</option>
            <option value="rsi">RSI 相對強弱指標（J. Welles Wilder）</option>
          </select>
        </div>
        <div id="btParamFields" style="display:flex; gap:10px 16px;"></div>
        <div class="bt-field">
          <label for="btTimeframe">K線週期</label>
          <select id="btTimeframe">
            <option value="daily" selected>日K</option>
            <option value="60m">60分K</option>
            <option value="5m">5分K</option>
          </select>
        </div>
        <div id="btRangeField"></div>
        <div class="bt-field">
          <label for="btCapital">初始資金</label>
          <input type="number" id="btCapital" value="100000" min="1000" step="10000">
        </div>
        <div class="bt-field checkbox">
          <input type="checkbox" id="btFee" checked>
          <label for="btFee" style="margin:0">計入手續費/證交稅</label>
        </div>
        <button id="btRunBtn" class="primary" type="button">執行回測</button>
        <button id="btCompareBtn" type="button">🏆 比較所有策略</button>
        <button id="btLiveBtn" type="button">⚡ 即時訊號判斷</button>
      </div>
      <div id="btLiveResult"></div>
      <div id="btResults"><p class="empty">設定策略參數後按「執行回測」</p></div>
    `;
    return wrap;
  }

  function buildLiveSignalContent(data) {
    const box = document.createElement("div");
    box.className = "bt-live-box";
    const timeLabel = data.timeframe === "daily" ? "日K" : data.timeframe === "60m" ? "60分K" : "5分K";
    const barNote = data.is_live_bar_synthetic
      ? `（最新一根是用目前報價試算出的「假設現在收盤」臨時K棒，盤中價格還會變動，正式訊號要等這根K棒真的收盤才算數）`
      : `（最新一根是已經收盤確定的K棒）`;

    let verdict, verdictClass;
    if (!data.pending_signal) {
      verdict = `目前沒有新訊號，維持${data.currently_holding ? "持有" : "空手"}`;
      verdictClass = "";
    } else if (data.pending_signal === "buy") {
      verdict = data.will_execute
        ? `觸發【買進】訊號 → 將於下一根${timeLabel}開盤進場（不是這根K棒的收盤價）`
        : `出現買進訊號，但目前已持有部位，策略不會加碼（訊號被忽略）`;
      verdictClass = data.will_execute ? "up" : "";
    } else {
      verdict = data.will_execute
        ? `觸發【賣出】訊號 → 將於下一根${timeLabel}開盤出場（不是這根K棒的收盤價）`
        : `出現賣出訊號，但目前空手，訊號被忽略`;
      verdictClass = data.will_execute ? "down" : "";
    }

    box.innerHTML = `
      <div class="bt-live-verdict ${verdictClass}">${verdict}</div>
      <div class="bt-live-meta">
        依據「${escapeHtml(data.strategy_name)}」・${timeLabel}・截至 ${escapeHtml(data.as_of_date)}（價格 ${fmtNum(data.as_of_price, 2)}）${barNote}
      </div>
    `;
    return box;
  }

  function buildCompareTable(data, onPickStrategy) {
    const wrap = document.createElement("div");
    const note = document.createElement("p");
    note.className = "note";
    note.innerHTML = `同一段歷史資料（<strong>${escapeHtml(data.period.from)} ~ ${escapeHtml(data.period.to)}</strong>），六種策略都用預設參數各跑一次，` +
      `依總報酬率排序，買進持有報酬率為 <strong>${data.buy_hold_return_pct > 0 ? "+" : ""}${data.buy_hold_return_pct}%</strong>。` +
      `這只是這檔股票、這段期間、這個K線週期下的歷史排名，不是「哪種策略比較好」的通用結論，點一列可以直接切換到該策略看完整K線圖。`;
    wrap.appendChild(note);

    const table = document.createElement("table");
    table.innerHTML = `
      <thead><tr><th>策略</th><th>總報酬率</th><th>最大回撤</th><th>交易次數</th><th>勝率</th><th>平均每筆</th></tr></thead>
      <tbody>
        ${data.results.map((r, i) => {
          if (r.error) {
            return `<tr data-strategy="${escapeHtml(r.strategy)}"><td>${escapeHtml(r.strategy_name)}</td><td colspan="5" class="empty">${escapeHtml(r.error)}</td></tr>`;
          }
          const retClass = r.total_return_pct > 0 ? "up" : r.total_return_pct < 0 ? "down" : "";
          return `
            <tr data-strategy="${escapeHtml(r.strategy)}" style="cursor:pointer">
              <td>${i === 0 ? "🏆 " : ""}${escapeHtml(r.strategy_name)}</td>
              <td class="${retClass}">${r.total_return_pct > 0 ? "+" : ""}${r.total_return_pct}%</td>
              <td class="down">${r.max_drawdown_pct}%</td>
              <td>${r.trade_count}</td>
              <td>${r.win_rate_pct === null ? "-" : r.win_rate_pct + "%"}</td>
              <td>${r.avg_return_pct === null ? "-" : (r.avg_return_pct > 0 ? "+" : "") + r.avg_return_pct + "%"}</td>
            </tr>
          `;
        }).join("")}
      </tbody>
    `;
    table.querySelectorAll("tbody tr[data-strategy]").forEach((tr) => {
      tr.addEventListener("click", () => onPickStrategy(tr.dataset.strategy));
    });
    wrap.appendChild(table);
    return wrap;
  }

  function buildEquitySvg(curve, initialCapital) {
    const w = 900, h = 160, pad = 4;
    if (!curve.length) return "";
    const values = curve.map((p) => p.equity);
    let min = Math.min(...values, initialCapital);
    let max = Math.max(...values, initialCapital);
    if (min === max) { min -= 1; max += 1; }
    const x = (i) => pad + (i / (curve.length - 1 || 1)) * (w - pad * 2);
    const y = (v) => h - pad - ((v - min) / (max - min)) * (h - pad * 2);
    const points = curve.map((p, i) => `${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(" ");
    const baseY = y(initialCapital).toFixed(1);
    return `
      <svg class="bt-equity-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <line x1="${pad}" y1="${baseY}" x2="${w - pad}" y2="${baseY}" stroke="var(--text-muted)" stroke-width="1" stroke-dasharray="4,4"/>
        <polyline points="${points}" fill="none" stroke="var(--series-1, var(--up))" stroke-width="1.6"/>
      </svg>
    `;
  }

  function buildBacktestCandleSvg(candles, trades, openPosition, showBollinger) {
    const w = 900, h = 240, padTop = 10, padBottom = 22, padX = 6;
    if (!candles.length) return "";
    const n = candles.length;
    const dateIndex = new Map();
    candles.forEach((c, i) => dateIndex.set(c.date, i));
    // 太多根K棒（例如長期間的分鐘K）逐根畫會很卡，退化成收盤價折線，買賣標記邏輯不變
    const useLine = n > 1500;
    const highs = candles.map((c) => c.high);
    const lows = candles.map((c) => c.low);
    const closes = candles.map((c) => c.close);
    const hasBoll = showBollinger && candles.some((c) => c.boll_upper != null);
    let min = Math.min(...(useLine ? closes : lows));
    let max = Math.max(...(useLine ? closes : highs));
    if (hasBoll) {
      const bollVals = candles.flatMap((c) => [c.boll_upper, c.boll_lower]).filter((v) => v != null);
      if (bollVals.length) { min = Math.min(min, ...bollVals); max = Math.max(max, ...bollVals); }
    }
    if (min === max) { min -= 1; max += 1; }
    const padV = (max - min) * 0.08;
    min -= padV; max += padV;
    const x = (i) => padX + (i / (n - 1 || 1)) * (w - padX * 2);
    const y = (v) => padTop + (1 - (v - min) / (max - min)) * (h - padTop - padBottom);

    const parts = [];
    if (hasBoll) {
      const firstIdx = candles.findIndex((c) => c.boll_upper != null && c.boll_lower != null);
      if (firstIdx >= 0) {
        let fillPath = `M ${x(firstIdx).toFixed(1)} ${y(candles[firstIdx].boll_upper).toFixed(1)} `;
        for (let i = firstIdx; i < n; i++) {
          if (candles[i].boll_upper == null) break;
          fillPath += `L ${x(i).toFixed(1)} ${y(candles[i].boll_upper).toFixed(1)} `;
        }
        for (let i = n - 1; i >= firstIdx; i--) {
          if (candles[i].boll_lower == null) continue;
          fillPath += `L ${x(i).toFixed(1)} ${y(candles[i].boll_lower).toFixed(1)} `;
        }
        parts.push(`<path d="${fillPath}Z" class="boll-fill"/>`);
        const upperPts = candles.map((c, i) => c.boll_upper == null ? null : `${x(i).toFixed(1)},${y(c.boll_upper).toFixed(1)}`).filter(Boolean).join(" ");
        const lowerPts = candles.map((c, i) => c.boll_lower == null ? null : `${x(i).toFixed(1)},${y(c.boll_lower).toFixed(1)}`).filter(Boolean).join(" ");
        parts.push(`<polyline points="${upperPts}" class="boll-line"/>`);
        parts.push(`<polyline points="${lowerPts}" class="boll-line"/>`);
      }
    }
    if (useLine) {
      const points = closes.map((c, i) => `${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(" ");
      parts.push(`<polyline points="${points}" fill="none" stroke="var(--series-1)" stroke-width="1.2"/>`);
    } else {
      const slotW = (w - padX * 2) / n;
      const candleW = Math.max(1, Math.min(slotW * 0.6, 10));
      candles.forEach((c, i) => {
        const cx = x(i);
        const dir = c.close > c.open ? "up" : c.close < c.open ? "down" : "flat";
        parts.push(`<line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${y(c.high).toFixed(1)}" y2="${y(c.low).toFixed(1)}" class="candle-wick ${dir}" stroke-width="1"/>`);
        const bodyTop = y(Math.max(c.open, c.close));
        const bodyBottom = y(Math.min(c.open, c.close));
        parts.push(`<rect x="${(cx - candleW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${candleW.toFixed(1)}" height="${Math.max(1, bodyBottom - bodyTop).toFixed(1)}" class="candle-body ${dir}"/>`);
      });
    }

    const markerOffset = 9;
    const addBuyMarker = (idx, label) => {
      if (idx === undefined) return;
      const cx = x(idx), cy = y(lows[idx]) + markerOffset;
      parts.push(`<path d="M ${(cx - 5).toFixed(1)} ${(cy + 7).toFixed(1)} L ${(cx + 5).toFixed(1)} ${(cy + 7).toFixed(1)} L ${cx.toFixed(1)} ${(cy - 3).toFixed(1)} Z" class="bt-marker buy"><title>${escapeHtml(label)}</title></path>`);
    };
    const addSellMarker = (idx, label) => {
      if (idx === undefined) return;
      const cx = x(idx), cy = y(highs[idx]) - markerOffset;
      parts.push(`<path d="M ${(cx - 5).toFixed(1)} ${(cy - 7).toFixed(1)} L ${(cx + 5).toFixed(1)} ${(cy - 7).toFixed(1)} L ${cx.toFixed(1)} ${(cy + 3).toFixed(1)} Z" class="bt-marker sell"><title>${escapeHtml(label)}</title></path>`);
    };
    for (const t of trades) {
      addBuyMarker(dateIndex.get(t.buy_date), `買進 ${t.buy_date} @ ${t.buy_price}`);
      addSellMarker(dateIndex.get(t.sell_date), `賣出 ${t.sell_date} @ ${t.sell_price}`);
    }
    if (openPosition) {
      addBuyMarker(dateIndex.get(openPosition.buy_date), `買進(持有中) ${openPosition.buy_date} @ ${openPosition.buy_price}`);
    }

    [0, Math.floor((n - 1) / 2), n - 1].forEach((i) => {
      const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
      parts.push(`<text x="${x(i).toFixed(1)}" y="${h - 6}" text-anchor="${anchor}" class="axis-label">${escapeHtml(candles[i].date)}</text>`);
    });

    return `<svg class="bt-candle-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${parts.join("")}</svg>`;
  }

  function buildBacktestResults(data) {
    const wrap = document.createElement("div");
    const unit = data.timeframe === "daily" ? "根日K" : data.timeframe === "60m" ? "根60分K" : "根5分K";

    const note = document.createElement("p");
    note.className = "note";
    note.innerHTML =
      `以下是「${escapeHtml(data.strategy_name)}」策略在 <strong>${escapeHtml(data.period.from)} ~ ${escapeHtml(data.period.to)}</strong>` +
      `（共 ${data.period.days} ${unit}）的歷史回溯模擬結果——訊號用當根收盤後算出、下一根開盤才進出場，` +
      `避免用到當下還沒發生的價格。<strong>這是歷史資料統計，不是未來報酬的保證</strong>，也沒有考慮滑價、跌停鎖死無法成交等實務限制，請自行判斷風險。`;
    wrap.appendChild(note);

    const candleH1 = document.createElement("h4");
    candleH1.textContent = "K線圖（買賣點位標記）";
    wrap.appendChild(candleH1);
    const legend = document.createElement("div");
    legend.className = "bt-candle-legend";
    legend.innerHTML = `
      <div class="item"><span class="swatch buy"></span>買進</div>
      <div class="item"><span class="swatch sell"></span>賣出</div>
      <label class="item" style="cursor:pointer">
        <input type="checkbox" id="btShowBoll" checked style="margin:0">布林通道（20,2）
      </label>
    `;
    wrap.appendChild(legend);
    const candleWrap = document.createElement("div");
    candleWrap.className = "bt-candle-wrap";
    const redrawCandles = () => {
      const showBoll = legend.querySelector("#btShowBoll").checked;
      candleWrap.innerHTML = buildBacktestCandleSvg(data.candles, data.trades, data.open_position, showBoll);
    };
    redrawCandles();
    legend.querySelector("#btShowBoll").addEventListener("change", redrawCandles);
    wrap.appendChild(candleWrap);

    const grid = document.createElement("div");
    grid.className = "ref-grid";
    const retClass = data.total_return_pct > 0 ? "up" : data.total_return_pct < 0 ? "down" : "";
    const bhClass = data.buy_hold_return_pct > 0 ? "up" : data.buy_hold_return_pct < 0 ? "down" : "";
    const items = [
      ["策略總報酬率", `<span class="${retClass}">${data.total_return_pct > 0 ? "+" : ""}${data.total_return_pct}%</span>`],
      ["買進持有報酬率", `<span class="${bhClass}">${data.buy_hold_return_pct > 0 ? "+" : ""}${data.buy_hold_return_pct}%</span>`],
      ["最大回撤", `<span class="down">${data.max_drawdown_pct}%</span>`],
      ["最終資產", fmtNum(data.final_equity, 0)],
      ["交易次數", data.trade_count],
      ["勝率", data.win_rate_pct === null ? "-" : `${data.win_rate_pct}%`],
      ["平均每筆報酬", data.avg_return_pct === null ? "-" : `${data.avg_return_pct > 0 ? "+" : ""}${data.avg_return_pct}%`],
    ];
    for (const [label, value] of items) {
      const item = document.createElement("div");
      item.className = "ref-item";
      item.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
      grid.appendChild(item);
    }
    wrap.appendChild(grid);

    if (data.open_position) {
      const op = document.createElement("p");
      op.className = "note";
      const opClass = data.open_position.unrealized_return_pct > 0 ? "up" : "down";
      op.innerHTML = `目前仍持有中（${escapeHtml(data.open_position.buy_date)} 進場 @ ${fmtNum(data.open_position.buy_price, 2)}），` +
        `未實現報酬 <span class="${opClass}">${data.open_position.unrealized_return_pct > 0 ? "+" : ""}${data.open_position.unrealized_return_pct}%</span>（已計入上方統計）。`;
      wrap.appendChild(op);
    }

    const h1 = document.createElement("h4");
    h1.textContent = "資產曲線";
    wrap.appendChild(h1);
    const equityWrap = document.createElement("div");
    equityWrap.className = "bt-equity-wrap";
    equityWrap.innerHTML = buildEquitySvg(data.equity_curve, data.initial_capital);
    wrap.appendChild(equityWrap);

    const h2 = document.createElement("h4");
    h2.textContent = `交易紀錄（共 ${data.trades.length} 筆）`;
    wrap.appendChild(h2);
    if (!data.trades.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "回測期間內沒有出現進出場訊號";
      wrap.appendChild(empty);
    } else {
      const table = document.createElement("table");
      table.innerHTML = `
        <thead><tr><th>買進日</th><th>買進價</th><th>賣出日</th><th>賣出價</th><th>報酬率</th></tr></thead>
        <tbody>
          ${[...data.trades].reverse().map((t) => `
            <tr>
              <td>${escapeHtml(t.buy_date)}</td>
              <td>${fmtNum(t.buy_price, 2)}</td>
              <td>${escapeHtml(t.sell_date)}</td>
              <td>${fmtNum(t.sell_price, 2)}</td>
              <td class="${t.return_pct > 0 ? "up" : t.return_pct < 0 ? "down" : ""}">${t.return_pct > 0 ? "+" : ""}${t.return_pct}%</td>
            </tr>
          `).join("")}
        </tbody>
      `;
      wrap.appendChild(table);
    }

    const disclaimer = document.createElement("p");
    disclaimer.className = "disclaimer";
    disclaimer.textContent = "回測未考慮實際成交量能否吃單、除權息調整、融資融券等因素，僅為策略邏輯的歷史參考，不構成投資建議。";
    wrap.appendChild(disclaimer);

    return wrap;
  }

  function wireBacktestContainer(container) {
    const updateParamFields = () => {
      const strategy = container.querySelector("#btStrategy").value;
      container.querySelector("#btParamFields").innerHTML = backtestFieldsHtml(strategy);
    };
    updateParamFields();
    container.querySelector("#btStrategy").addEventListener("change", updateParamFields);

    const updateRangeField = () => {
      const timeframe = container.querySelector("#btTimeframe").value;
      container.querySelector("#btRangeField").innerHTML = backtestRangeFieldHtml(timeframe);
    };
    updateRangeField();
    container.querySelector("#btTimeframe").addEventListener("change", updateRangeField);

    const collectStrategyParams = (strategy, target) => {
      if (strategy === "ma_cross") {
        target.set("short_period", container.querySelector("#btShortPeriod").value);
        target.set("long_period", container.querySelector("#btLongPeriod").value);
      } else if (strategy === "bollinger") {
        target.set("boll_period", container.querySelector("#btBollPeriod").value);
        target.set("boll_k", container.querySelector("#btBollK").value);
      } else if (strategy === "breakout") {
        target.set("breakout_period", container.querySelector("#btBreakoutPeriod").value);
      } else if (strategy === "macd") {
        target.set("macd_fast", container.querySelector("#btMacdFast").value);
        target.set("macd_slow", container.querySelector("#btMacdSlow").value);
        target.set("macd_signal", container.querySelector("#btMacdSignal").value);
      } else if (strategy === "kd") {
        target.set("kd_period", container.querySelector("#btKdPeriod").value);
        target.set("kd_oversold", container.querySelector("#btKdOversold").value);
        target.set("kd_overbought", container.querySelector("#btKdOverbought").value);
      } else {
        target.set("rsi_period", container.querySelector("#btRsiPeriod").value);
        target.set("rsi_buy", container.querySelector("#btRsiBuy").value);
        target.set("rsi_sell", container.querySelector("#btRsiSell").value);
      }
    };

    const collectRangeParams = (target) => {
      const timeframe = container.querySelector("#btTimeframe").value;
      if (timeframe === "daily") {
        target.set("months", container.querySelector("#btMonths").value);
      } else {
        target.set("days", container.querySelector("#btDays").value);
      }
    };

    const runFullBacktest = async () => {
      const resultsEl = container.querySelector("#btResults");
      const strategy = container.querySelector("#btStrategy").value;
      const timeframe = container.querySelector("#btTimeframe").value;
      const params = new URLSearchParams({
        code: state.selectedCode,
        strategy,
        timeframe,
        initial_capital: container.querySelector("#btCapital").value,
        include_fee: container.querySelector("#btFee").checked ? "1" : "0",
      });
      collectRangeParams(params);
      collectStrategyParams(strategy, params);
      resultsEl.innerHTML = `<p class="empty"><span class="spinner"></span>回測執行中…</p>`;
      try {
        const res = await fetch(`/api/backtest?${params.toString()}`);
        const data = await res.json();
        if (modalBody.firstElementChild !== container) return; // 使用者已關閉或切換
        if (data.error) {
          resultsEl.innerHTML = `<p class="empty">${escapeHtml(data.error)}</p>`;
          return;
        }
        resultsEl.innerHTML = "";
        resultsEl.appendChild(buildBacktestResults(data));
      } catch (err) {
        console.error(err);
        if (modalBody.firstElementChild === container) {
          resultsEl.innerHTML = `<p class="empty">回測失敗，請稍後再試</p>`;
        }
      }
    };
    container.querySelector("#btRunBtn").addEventListener("click", runFullBacktest);

    container.querySelector("#btCompareBtn").addEventListener("click", async () => {
      const resultsEl = container.querySelector("#btResults");
      const timeframe = container.querySelector("#btTimeframe").value;
      const params = new URLSearchParams({
        code: state.selectedCode,
        timeframe,
        initial_capital: container.querySelector("#btCapital").value,
        include_fee: container.querySelector("#btFee").checked ? "1" : "0",
      });
      collectRangeParams(params);
      resultsEl.innerHTML = `<p class="empty"><span class="spinner"></span>比較六種策略中…（要跑六次回測，稍等一下）</p>`;
      try {
        const res = await fetch(`/api/backtest_compare?${params.toString()}`);
        const data = await res.json();
        if (modalBody.firstElementChild !== container) return;
        if (data.error) {
          resultsEl.innerHTML = `<p class="empty">${escapeHtml(data.error)}</p>`;
          return;
        }
        resultsEl.innerHTML = "";
        resultsEl.appendChild(buildCompareTable(data, (strategy) => {
          container.querySelector("#btStrategy").value = strategy;
          updateParamFields();
          runFullBacktest();
        }));
      } catch (err) {
        console.error(err);
        if (modalBody.firstElementChild === container) {
          resultsEl.innerHTML = `<p class="empty">比較失敗，請稍後再試</p>`;
        }
      }
    });

    container.querySelector("#btLiveBtn").addEventListener("click", async () => {
      const liveEl = container.querySelector("#btLiveResult");
      const strategy = container.querySelector("#btStrategy").value;
      const timeframe = container.querySelector("#btTimeframe").value;
      const params = new URLSearchParams({ code: state.selectedCode, strategy, timeframe });
      collectRangeParams(params);
      collectStrategyParams(strategy, params);
      liveEl.innerHTML = `<p class="empty"><span class="spinner"></span>即時判斷中…</p>`;
      try {
        const res = await fetch(`/api/backtest_live?${params.toString()}`);
        const data = await res.json();
        if (modalBody.firstElementChild !== container) return;
        if (data.error) {
          liveEl.innerHTML = `<p class="empty">${escapeHtml(data.error)}</p>`;
          return;
        }
        liveEl.innerHTML = "";
        liveEl.appendChild(buildLiveSignalContent(data));
      } catch (err) {
        console.error(err);
        if (modalBody.firstElementChild === container) {
          liveEl.innerHTML = `<p class="empty">即時判斷失敗，請稍後再試</p>`;
        }
      }
    });
  }

  $("#backtestBtn").addEventListener("click", () => {
    if (state.selectedIsIndex || !state.selectedCode) {
      const container = document.createElement("div");
      container.innerHTML = `<p class="empty">請先從觀察清單、選股結果或市場總覽點選一檔個股（回測不支援大盤指數）</p>`;
      openModal("策略回測", container);
      return;
    }
    const name = state.selectedName || state.selectedCode;
    const container = buildBacktestContainer();
    openModal(`策略回測：${name}`, container);
    wireBacktestContainer(container);
  });

