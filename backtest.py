"""
個股策略回測引擎：六種常見技術面策略（均線交叉、布林回歸、唐奇安突破、MACD、KD、RSI）
的訊號產生、進出場模擬、即時訊號判斷、多策略比較、觀察清單掃描。

所有訊號都用「當根K棒收盤後算出的訊號，隔一根K棒開盤才進場/出場」的方式模擬，
避免用到當下還沒發生的價格（look-ahead bias）。這是歷史資料的回溯統計，不代表未來報酬，
也沒有考慮滑價、無法成交（跌停鎖死等）等實務限制。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from app_core import safe_float
from market_data import (
    fetch_stock_daily_rows_for_chart,
    fetch_stock_daily_rows,
    fetch_stock_intraday_rows_for_backtest,
    fetch_intraday,
)

BACKTEST_BUY_FEE_PCT = 0.1425     # 買進手續費（券商折扣前，僅供估算）
BACKTEST_SELL_FEE_PCT = 0.1425 + 0.3  # 賣出手續費 + 證交稅

BACKTEST_STRATEGIES = {
    "ma_cross": "均線黃金/死亡交叉",
    "bollinger": "布林通道回歸（John Bollinger）",
    "breakout": "唐奇安通道突破（海龜交易法則）",
    "macd": "MACD 指標交叉（Gerald Appel）",
    "kd": "KD 隨機指標（George Lane）",
    "rsi": "RSI 相對強弱指標（J. Welles Wilder）",
}


def _parse_ohlcv_rows(rows):
    dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for r in rows:
        o, h, l, c = safe_float(r[3]), safe_float(r[4]), safe_float(r[5]), safe_float(r[6])
        v = safe_float(r[1])
        if None in (o, h, l, c):
            continue
        dates.append(r[0])
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v or 0)
    return dates, opens, highs, lows, closes, volumes


def _ma_series(values, period):
    out = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    running = sum(values[:period])
    out[period - 1] = running / period
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        out[i] = running / period
    return out


def _backtest_signals_ma_cross(closes, params):
    short_p = max(1, int(params.get("short_period", 5)))
    long_p = max(short_p + 1, int(params.get("long_period", 20)))
    ma_short = _ma_series(closes, short_p)
    ma_long = _ma_series(closes, long_p)
    signals = [None] * len(closes)
    for i in range(1, len(closes)):
        if None in (ma_short[i - 1], ma_long[i - 1], ma_short[i], ma_long[i]):
            continue
        if ma_short[i - 1] <= ma_long[i - 1] and ma_short[i] > ma_long[i]:
            signals[i] = "buy"
        elif ma_short[i - 1] >= ma_long[i - 1] and ma_short[i] < ma_long[i]:
            signals[i] = "sell"
    return signals, {"short_period": short_p, "long_period": long_p}


def _backtest_signals_bollinger(closes, params):
    period = max(2, int(params.get("boll_period", 20)))
    k = float(params.get("boll_k", 2))
    signals = [None] * len(closes)
    if len(closes) < period:
        return signals, {"boll_period": period, "boll_k": k}
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / period
        sd = (sum((c - mean) ** 2 for c in window) / period) ** 0.5
        upper, lower = mean + k * sd, mean - k * sd
        if i == period - 1:
            continue
        prev_close = closes[i - 1]
        if closes[i] < lower and prev_close >= lower:
            signals[i] = "buy"
        elif closes[i] > mean and prev_close <= mean:
            signals[i] = "sell"
    return signals, {"boll_period": period, "boll_k": k}


def _backtest_signals_breakout(highs, lows, closes, params):
    period = max(2, int(params.get("breakout_period", 20)))
    signals = [None] * len(closes)
    for i in range(period, len(closes)):
        prior_high = max(highs[i - period:i])
        prior_low = min(lows[i - period:i])
        if closes[i] > prior_high:
            signals[i] = "buy"
        elif closes[i] < prior_low:
            signals[i] = "sell"
    return signals, {"breakout_period": period}


def _ema_series(values, period):
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _backtest_signals_macd(closes, params):
    fast = max(1, int(params.get("macd_fast", 12)))
    slow = max(fast + 1, int(params.get("macd_slow", 26)))
    sig = max(1, int(params.get("macd_signal", 9)))
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    macd_line = [a - b for a, b in zip(ema_fast, ema_slow)]
    signal_line = _ema_series(macd_line, sig)
    signals = [None] * len(closes)
    warmup = slow + sig
    for i in range(max(1, warmup), len(closes)):
        prev_diff = macd_line[i - 1] - signal_line[i - 1]
        diff = macd_line[i] - signal_line[i]
        if prev_diff <= 0 and diff > 0:
            signals[i] = "buy"
        elif prev_diff >= 0 and diff < 0:
            signals[i] = "sell"
    return signals, {"macd_fast": fast, "macd_slow": slow, "macd_signal": sig}


def _backtest_signals_kd(highs, lows, closes, params):
    period = max(2, int(params.get("kd_period", 9)))
    oversold = float(params.get("kd_oversold", 20))
    overbought = float(params.get("kd_overbought", 80))
    n = len(closes)
    signals = [None] * n
    k_series, d_series = [None] * n, [None] * n
    k_val, d_val = 50.0, 50.0
    for i in range(period - 1, n):
        window_h = highs[i - period + 1:i + 1]
        window_l = lows[i - period + 1:i + 1]
        hh, ll = max(window_h), min(window_l)
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k_val = k_val * (2 / 3) + rsv * (1 / 3)
        d_val = d_val * (2 / 3) + k_val * (1 / 3)
        k_series[i], d_series[i] = k_val, d_val
    for i in range(period, n):
        if None in (k_series[i - 1], d_series[i - 1], k_series[i], d_series[i]):
            continue
        # 低檔黃金交叉：K向上穿越D，且交叉當下K還在超賣區 -> 買進
        if k_series[i - 1] <= d_series[i - 1] and k_series[i] > d_series[i] and k_series[i] < oversold:
            signals[i] = "buy"
        # 高檔死亡交叉：K向下穿越D，且交叉當下K還在超買區 -> 賣出
        elif k_series[i - 1] >= d_series[i - 1] and k_series[i] < d_series[i] and k_series[i] > overbought:
            signals[i] = "sell"
    return signals, {"kd_period": period, "kd_oversold": oversold, "kd_overbought": overbought}


def _backtest_signals_rsi(closes, params):
    period = max(2, int(params.get("rsi_period", 14)))
    buy_th = float(params.get("rsi_buy", 30))
    sell_th = float(params.get("rsi_sell", 70))
    n = len(closes)
    signals = [None] * n
    if n < period + 2:
        return signals, {"rsi_period": period, "rsi_buy": buy_th, "rsi_sell": sell_th}

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        chg = closes[i] - closes[i - 1]
        gains[i] = max(chg, 0.0)
        losses[i] = max(-chg, 0.0)

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsi = [None] * n

    def calc_rsi(ag, al):
        if al == 0:
            return 100.0
        return 100 - 100 / (1 + ag / al)

    rsi[period] = calc_rsi(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i] = calc_rsi(avg_gain, avg_loss)

    for i in range(period + 1, n):
        if rsi[i - 1] is None or rsi[i] is None:
            continue
        # RSI從超賣區向上穿越 -> 止跌訊號，買進
        if rsi[i - 1] <= buy_th < rsi[i]:
            signals[i] = "buy"
        # RSI從超買區向下穿越 -> 過熱回落訊號，賣出
        elif rsi[i - 1] >= sell_th > rsi[i]:
            signals[i] = "sell"
    return signals, {"rsi_period": period, "rsi_buy": buy_th, "rsi_sell": sell_th}


def _fetch_backtest_series(code, timeframe, months, days):
    if timeframe == "daily":
        rows = fetch_stock_daily_rows_for_chart(code, months=months)
    else:
        rows = fetch_stock_intraday_rows_for_backtest(code, interval=timeframe, days=days)
    return _parse_ohlcv_rows(rows)


def _min_bars_required(strategy, params):
    min_bars_map = {
        "ma_cross": params.get("long_period", 20),
        "bollinger": params.get("boll_period", 20),
        "breakout": params.get("breakout_period", 20),
        "macd": params.get("macd_slow", 26) + params.get("macd_signal", 9),
        "kd": params.get("kd_period", 9),
        "rsi": params.get("rsi_period", 14),
    }
    return min_bars_map[strategy] + 10


def _compute_backtest_signals(strategy, params, highs, lows, closes):
    if strategy == "ma_cross":
        return _backtest_signals_ma_cross(closes, params)
    if strategy == "bollinger":
        return _backtest_signals_bollinger(closes, params)
    if strategy == "breakout":
        return _backtest_signals_breakout(highs, lows, closes, params)
    if strategy == "macd":
        return _backtest_signals_macd(closes, params)
    if strategy == "kd":
        return _backtest_signals_kd(highs, lows, closes, params)
    return _backtest_signals_rsi(closes, params)


def _simulate_backtest(dates, opens, closes, signals, initial_capital, include_fee):
    """把訊號序列模擬成實際進出場：訊號在當根K棒收盤後才算數，實際進出場動作
    放在下一根K棒的開盤價成交，避免用到還沒發生的價格。回傳的 pending_signal／
    holding 是「跑完整段序列後，還沒被下一根執行到」的最新訊號與目前部位狀態，
    給即時判斷功能用。"""
    buy_fee = BACKTEST_BUY_FEE_PCT / 100 if include_fee else 0.0
    sell_fee = BACKTEST_SELL_FEE_PCT / 100 if include_fee else 0.0

    cash = float(initial_capital)
    shares = 0.0
    entry = None  # {"date","price"}
    pending_signal = None
    trades = []
    equity_curve = []

    n = len(closes)
    for i in range(n):
        if pending_signal == "buy" and shares == 0:
            price = opens[i]
            cash_after_fee = cash * (1 - buy_fee)
            shares = cash_after_fee / price
            cash = 0.0
            entry = {"date": dates[i], "price": price}
        elif pending_signal == "sell" and shares > 0:
            price = opens[i]
            proceeds = shares * price * (1 - sell_fee)
            ret_pct = (proceeds / (shares * entry["price"]) - 1) * 100 if entry else 0.0
            trades.append({
                "buy_date": entry["date"], "buy_price": round(entry["price"], 2),
                "sell_date": dates[i], "sell_price": round(price, 2),
                "return_pct": round(ret_pct, 2),
            })
            cash = proceeds
            shares = 0.0
            entry = None

        equity = cash if shares == 0 else shares * closes[i]
        equity_curve.append({"date": dates[i], "equity": round(equity, 2)})
        pending_signal = signals[i]

    open_position = None
    if shares > 0 and entry:
        unrealized_pct = (closes[-1] / entry["price"] - 1) * 100
        open_position = {"buy_date": entry["date"], "buy_price": round(entry["price"], 2),
                          "unrealized_return_pct": round(unrealized_pct, 2)}

    return {
        "trades": trades, "equity_curve": equity_curve, "open_position": open_position,
        "pending_signal": pending_signal, "holding": shares > 0,
    }


def _backtest_params_from_qs(qs):
    return {
        "short_period": int(qs.get("short_period", ["5"])[0]),
        "long_period": int(qs.get("long_period", ["20"])[0]),
        "boll_period": int(qs.get("boll_period", ["20"])[0]),
        "boll_k": float(qs.get("boll_k", ["2"])[0]),
        "breakout_period": int(qs.get("breakout_period", ["20"])[0]),
        "macd_fast": int(qs.get("macd_fast", ["12"])[0]),
        "macd_slow": int(qs.get("macd_slow", ["26"])[0]),
        "macd_signal": int(qs.get("macd_signal", ["9"])[0]),
        "kd_period": int(qs.get("kd_period", ["9"])[0]),
        "kd_oversold": float(qs.get("kd_oversold", ["20"])[0]),
        "kd_overbought": float(qs.get("kd_overbought", ["80"])[0]),
        "rsi_period": int(qs.get("rsi_period", ["14"])[0]),
        "rsi_buy": float(qs.get("rsi_buy", ["30"])[0]),
        "rsi_sell": float(qs.get("rsi_sell", ["70"])[0]),
    }


def _bollinger_band_series(closes, period=20, k=2):
    """回傳每一根K棒對應的布林通道 (upper, mid, lower)，資料不足時該筆為 (None,None,None)。
    給K線圖疊加布林通道背景帶用。"""
    n = len(closes)
    out = [(None, None, None)] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / period
        sd = (sum((c - mean) ** 2 for c in window) / period) ** 0.5
        out[i] = (round(mean + k * sd, 2), round(mean, 2), round(mean - k * sd, 2))
    return out


def run_backtest(code, timeframe="daily", months=24, days=30, strategy="ma_cross", params=None,
                  initial_capital=100000.0, include_fee=True):
    params = params or {}
    if strategy not in BACKTEST_STRATEGIES:
        return {"error": f"unknown strategy: {strategy}"}
    if timeframe not in ("daily", "60m", "5m"):
        return {"error": f"unknown timeframe: {timeframe}"}

    dates, opens, highs, lows, closes, volumes = _fetch_backtest_series(code, timeframe, months, days)

    min_bars = _min_bars_required(strategy, params)
    if len(closes) < min_bars:
        return {"error": f"歷史資料不足（僅 {len(closes)} 根K棒），請拉長回測期間或放寬參數"}

    signals, used_params = _compute_backtest_signals(strategy, params, highs, lows, closes)
    sim = _simulate_backtest(dates, opens, closes, signals, initial_capital, include_fee)
    trades, equity_curve, open_position = sim["trades"], sim["equity_curve"], sim["open_position"]

    n = len(closes)
    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
    total_return_pct = (final_equity / initial_capital - 1) * 100
    buy_hold_return_pct = (closes[-1] / opens[0] - 1) * 100 if opens else 0.0

    peak = -float("inf")
    max_dd = 0.0
    for pt in equity_curve:
        peak = max(peak, pt["equity"])
        if peak > 0:
            dd = (pt["equity"] - peak) / peak * 100
            max_dd = min(max_dd, dd)

    win_trades = [t for t in trades if t["return_pct"] > 0]
    win_rate = (len(win_trades) / len(trades) * 100) if trades else None
    avg_return_pct = (sum(t["return_pct"] for t in trades) / len(trades)) if trades else None

    boll_bands = _bollinger_band_series(closes)
    candles = [{
        "date": dates[i], "open": round(opens[i], 2), "high": round(highs[i], 2),
        "low": round(lows[i], 2), "close": round(closes[i], 2),
        "boll_upper": boll_bands[i][0], "boll_mid": boll_bands[i][1], "boll_lower": boll_bands[i][2],
    } for i in range(n)]

    return {
        "code": code,
        "timeframe": timeframe,
        "strategy": strategy,
        "strategy_name": BACKTEST_STRATEGIES[strategy],
        "params": used_params,
        "include_fee": include_fee,
        "period": {"from": dates[0], "to": dates[-1], "days": n},
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return_pct, 2),
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "trade_count": len(trades),
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "avg_return_pct": round(avg_return_pct, 2) if avg_return_pct is not None else None,
        "open_position": open_position,
        "trades": trades,
        "equity_curve": equity_curve,
        "candles": candles,
    }


def compare_backtest_strategies(code, timeframe="daily", months=24, days=30,
                                 initial_capital=100000.0, include_fee=True):
    """用同一段歷史資料，把六種策略（全部用預設參數）都跑一次回測，依總報酬率排序，
    方便使用者比較「這檔股票在這段期間、這個K線週期下，哪種策略打敗買進持有／
    哪種最差」——單純是歷史資料的排名比較，不是「哪種策略比較好」的通用結論，
    換一檔股票或換一段期間排名可能完全不同。"""
    if timeframe not in ("daily", "60m", "5m"):
        return {"error": f"unknown timeframe: {timeframe}"}

    dates, opens, highs, lows, closes, volumes = _fetch_backtest_series(code, timeframe, months, days)
    if not closes:
        return {"error": "查無歷史資料"}

    results = []
    for strategy in BACKTEST_STRATEGIES:
        params = {}
        min_bars = _min_bars_required(strategy, params)
        if len(closes) < min_bars:
            results.append({"strategy": strategy, "strategy_name": BACKTEST_STRATEGIES[strategy],
                             "error": "歷史資料不足"})
            continue
        signals, used_params = _compute_backtest_signals(strategy, params, highs, lows, closes)
        sim = _simulate_backtest(dates, opens, closes, signals, initial_capital, include_fee)
        trades, equity_curve = sim["trades"], sim["equity_curve"]

        final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
        total_return_pct = (final_equity / initial_capital - 1) * 100
        peak = -float("inf")
        max_dd = 0.0
        for pt in equity_curve:
            peak = max(peak, pt["equity"])
            if peak > 0:
                max_dd = min(max_dd, (pt["equity"] - peak) / peak * 100)
        win_trades = [t for t in trades if t["return_pct"] > 0]
        win_rate = (len(win_trades) / len(trades) * 100) if trades else None
        avg_return_pct = (sum(t["return_pct"] for t in trades) / len(trades)) if trades else None

        results.append({
            "strategy": strategy, "strategy_name": BACKTEST_STRATEGIES[strategy], "params": used_params,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "trade_count": len(trades),
            "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
            "avg_return_pct": round(avg_return_pct, 2) if avg_return_pct is not None else None,
        })

    buy_hold_return_pct = (closes[-1] / opens[0] - 1) * 100 if opens else 0.0
    results.sort(key=lambda r: r.get("total_return_pct", -1e18), reverse=True)

    return {
        "code": code, "timeframe": timeframe,
        "period": {"from": dates[0], "to": dates[-1], "days": len(closes)},
        "initial_capital": round(initial_capital, 2),
        "include_fee": include_fee,
        "buy_hold_return_pct": round(buy_hold_return_pct, 2),
        "results": results,
    }


def run_live_signal(code, timeframe="daily", strategy="ma_cross", params=None, months=24, days=30):
    """即時判斷：用最新資料（日K會把「今天盤中還沒收盤」的即時報價併成一根臨時K棒）
    算出策略目前的訊號——這是「如果現在這根K棒就這樣收，策略會怎麼判斷」的即時試算，
    正式訊號仍要等這根K棒真的收盤才算數，盤中價格隨時可能再變動。"""
    params = params or {}
    if strategy not in BACKTEST_STRATEGIES:
        return {"error": f"unknown strategy: {strategy}"}
    if timeframe not in ("daily", "60m", "5m"):
        return {"error": f"unknown timeframe: {timeframe}"}

    dates, opens, highs, lows, closes, volumes = _fetch_backtest_series(code, timeframe, months, days)
    if not closes:
        return {"error": "查無歷史資料"}

    is_live_bar_synthetic = False
    if timeframe == "daily":
        live = fetch_intraday(code)
        if live and live.get("points"):
            y, m, d = live["trade_date"].split("-")
            roc_date = f"{int(y) - 1911}/{m}/{d}"
            # 用字串比大小而非只比不等於：避免即時報價解析到的交易日比歷史序列
            # 最後一筆還舊（時區/快取誤差）時，把舊資料接到新資料後面、弄亂日期順序
            if not dates or roc_date > dates[-1]:
                prices = [p["price"] for p in live["points"]]
                today_open = prices[0]
                today_close = prices[-1]
                today_high = live.get("day_high") or max(prices)
                today_low = live.get("day_low") or min(prices)
                dates.append(roc_date)
                opens.append(today_open)
                highs.append(today_high)
                lows.append(today_low)
                closes.append(today_close)
                volumes.append(0)
                is_live_bar_synthetic = True
    # 60分K／5分K：Yahoo 回傳的序列本身已經包含到目前為止還在走的最後一根K，不用額外處理

    min_bars = _min_bars_required(strategy, params)
    if len(closes) < min_bars:
        return {"error": f"歷史資料不足（僅 {len(closes)} 根K棒），請拉長回測期間或放寬參數"}

    signals, used_params = _compute_backtest_signals(strategy, params, highs, lows, closes)
    sim = _simulate_backtest(dates, opens, closes, signals, initial_capital=100000.0, include_fee=True)
    pending_signal = sim["pending_signal"]
    holding = sim["holding"]
    will_execute = (pending_signal == "buy" and not holding) or (pending_signal == "sell" and holding)

    return {
        "code": code, "timeframe": timeframe, "strategy": strategy,
        "strategy_name": BACKTEST_STRATEGIES[strategy], "params": used_params,
        "as_of_date": dates[-1], "as_of_price": round(closes[-1], 2),
        "is_live_bar_synthetic": is_live_bar_synthetic,
        "pending_signal": pending_signal,
        "currently_holding": holding,
        "will_execute": will_execute,
    }


def scan_backtest_buy_signals(codes, timeframe="daily", strategy="ma_cross", params=None,
                               months=24, days=30, min_volume_lots=1000):
    """量化做多掃描：對一組股票（通常是使用者的觀察清單）各自跑一次即時訊號判斷，
    並用近5個交易日平均成交量（張）做流動性門檻，避免挑到量小、進出場會打到自己
    價格的股票。回傳全部結果（含未通過的），由前端決定要不要只顯示『可進場』的。"""
    params = params or {}

    def check_one(code):
        sig = run_live_signal(code, timeframe=timeframe, strategy=strategy, params=params,
                               months=months, days=days)
        if "error" in sig:
            return {"code": code, "error": sig["error"]}
        daily_rows = fetch_stock_daily_rows(code, months=1)
        vols = [safe_float(r[1]) for r in daily_rows[-5:] if safe_float(r[1]) is not None]
        avg_volume_lots = round(sum(vols) / len(vols) / 1000) if vols else 0
        sig["avg_volume_lots"] = avg_volume_lots
        sig["liquidity_ok"] = avg_volume_lots >= min_volume_lots
        sig["actionable_buy"] = bool(
            sig.get("pending_signal") == "buy" and sig.get("will_execute") and sig["liquidity_ok"]
        )
        return sig

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(check_one, code): code for code in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"code": code, "error": str(e)}
            results.append(r)
    results.sort(key=lambda r: (not r.get("actionable_buy", False), r.get("code", "")))
    return results
