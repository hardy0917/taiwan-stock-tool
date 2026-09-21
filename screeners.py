"""
兩支選股篩選器：
- run_screener：做多低接篩選（布林下軌拉回，月線走平或上揚／處置回檔低接）
- run_short_screener：放空篩選（脫離布林上軌 + 隔天進處置）
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app_core import safe_float, fetch_json
from indicators import compute_ma20_series, compute_bollinger_now, compute_volume_bias
from market_data import fetch_market_snapshot, fetch_stock_daily_rows
from fundamentals import fetch_monthly_revenue, fetch_eps, fetch_valuation
from disposition import fetch_disposition, fetch_attention, fetch_margin_data
from holders import get_holder_data

# ---------- 選股篩選：拉回低接 + 財務體質 ----------

_screener_cache = {}
_screener_lock = threading.Lock()

MAX_TREND_CANDIDATES = 300
MIN_RELIABLE_HOLDERS = 5  # 大戶人數低於此門檻時，樣本太小、變化%沒有統計意義，不列入評分


def compute_long_term_bull_pct(code, years=2):
    """近 N 年裡，收盤價站上 20 日均線（月線）的交易日比例——
    用來大致衡量這檔股票長期是否傾向多頭（比單純看近 10 天更能反映長期走法）"""
    rows = fetch_stock_daily_rows(code, months=years * 12 + 1)
    closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
    ma20 = compute_ma20_series(rows)
    if not ma20:
        return None
    aligned_closes = closes[len(closes) - len(ma20):]
    if not aligned_closes:
        return None
    above = sum(1 for c, m in zip(aligned_closes, ma20) if c > m)
    return round(above / len(ma20) * 100, 1)


BOLL_PULLBACK_FLAT_SLOPE_PCT = -1.0  # 月線斜率 >= 這個值才算「走平或上揚」，不是明顯下彎


def run_screener(boll_level_threshold=3.0, trend_days=10, long_term=False, min_trade_value=0):
    """做多低接篩選：找兩種拉回低接的股票——
    (A) 股價已經回檔到布林通道下軌附近（位階 <= 門檻），但月線本身還是走平或上揚，不是趨勢
        已經轉空的下殺，是「健康上升／盤整趨勢中的正常拉回」；
    (B) 已經被公告處置的股票，股價回檔到布林通道下軌附近——處置生效後流動性變差、
        籌碼容易洗出浮額，位階夠低時也是常見的短線低接切入參考。
    兩種都只是規則過濾出的觀察名單，不是預測、不是買進訊號。"""
    cache_key = (round(boll_level_threshold, 2), trend_days, bool(long_term), int(min_trade_value))
    with _screener_lock:
        hit = _screener_cache.get(cache_key)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]

    snapshot = fetch_market_snapshot()
    disposition_map = fetch_disposition()

    # 第一階段粗篩（只針對條件A）：布林下軌通常落在月線下方，這裡用寬鬆範圍先抓可能
    # 候選，真正精準的布林位階一律在第二階段用每檔個股的實際日收盤價重新計算。
    # 條件B（處置股）不受此粗篩限制，直接對處置公告清單逐檔精算。
    candidates = []
    for code, v in snapshot.items():
        rough_proximity = (v["close"] - v["monthly_avg"]) / v["monthly_avg"] * 100
        if -35 <= rough_proximity <= 5:
            candidates.append((code, v))
    candidates = candidates[:MAX_TREND_CANDIDATES]

    # 抓夠長的歷史，確保 20 日均線序列長度足以比對 trend_days 天前的月線
    history_months = max(3, -(-(20 + trend_days) // 20) + 1)

    def check_pullback(item):
        code, v = item
        rows = fetch_stock_daily_rows(code, months=history_months)
        closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
        ma20 = compute_ma20_series(rows)
        if len(ma20) <= trend_days or not closes:
            return None

        # 流動性過濾：近20個交易日平均成交金額，太小的股票即使技術面符合條件，
        # 實際上也難以用像樣的部位進出而不大幅影響股價，所以先濾掉
        recent_values = [safe_float(r[2]) for r in rows[-20:] if safe_float(r[2]) is not None]
        avg_trade_value = sum(recent_values) / len(recent_values) if recent_values else 0
        if min_trade_value > 0 and avg_trade_value < min_trade_value:
            return None

        boll = compute_bollinger_now(rows)
        if not boll or boll["level"] > boll_level_threshold:
            return None  # 還沒回檔到位（布林位階高於門檻）

        slope_pct = (ma20[-1] - ma20[-1 - trend_days]) / ma20[-1 - trend_days] * 100
        if slope_pct < BOLL_PULLBACK_FLAT_SLOPE_PCT:
            return None  # 月線仍在明顯下彎，不算「走平或上揚」中的拉回

        return {
            "code": code, "name": v["name"], "close": boll["close"],
            "monthly_avg": round(ma20[-1], 2),
            "boll_upper": boll["upper"], "boll_middle": boll["middle"], "boll_lower": boll["lower"],
            "boll_level": boll["level"],
            "ma20_slope_pct": round(slope_pct, 2),
            "chip_bias_5": compute_volume_bias(rows, 5),
            "chip_bias_20": compute_volume_bias(rows, 20),
            "avg_trade_value_wan": round(avg_trade_value / 10000),
            "entry_type": ["boll_pullback"],
        }

    results_by_code = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_pullback, item) for item in candidates]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                results_by_code[r["code"]] = r

    def check_disposition_pullback(code, info):
        rows = fetch_stock_daily_rows(code, months=history_months)
        closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
        if not closes:
            return None
        ma20 = compute_ma20_series(rows)

        recent_values = [safe_float(r[2]) for r in rows[-20:] if safe_float(r[2]) is not None]
        avg_trade_value = sum(recent_values) / len(recent_values) if recent_values else 0
        if min_trade_value > 0 and avg_trade_value < min_trade_value:
            return None

        boll = compute_bollinger_now(rows)
        if not boll or boll["level"] > boll_level_threshold:
            return None

        slope_pct = None
        if len(ma20) > trend_days:
            slope_pct = round((ma20[-1] - ma20[-1 - trend_days]) / ma20[-1 - trend_days] * 100, 2)

        return {
            "code": code, "name": info.get("name", ""), "close": boll["close"],
            "monthly_avg": round(ma20[-1], 2) if ma20 else None,
            "boll_upper": boll["upper"], "boll_middle": boll["middle"], "boll_lower": boll["lower"],
            "boll_level": boll["level"],
            "ma20_slope_pct": slope_pct,
            "chip_bias_5": compute_volume_bias(rows, 5),
            "chip_bias_20": compute_volume_bias(rows, 20),
            "avg_trade_value_wan": round(avg_trade_value / 10000),
            "entry_type": ["disposition_pullback"],
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_disposition_pullback, code, info) for code, info in disposition_map.items()]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                r = None
            if not r:
                continue
            if r["code"] in results_by_code:
                results_by_code[r["code"]]["entry_type"].append("disposition_pullback")
            else:
                results_by_code[r["code"]] = r

    results = list(results_by_code.values())

    revenue_map = fetch_monthly_revenue()
    eps_map = fetch_eps()
    valuation_map = fetch_valuation()
    attention_set = fetch_attention()
    try:
        holder_map = get_holder_data()
    except Exception:
        holder_map = {}

    for r in results:
        code = r["code"]
        rev = revenue_map.get(code, {})
        r["industry"] = rev.get("industry", "未分類")
        r["revenue_mom_pct"] = rev.get("revenue_mom_pct")
        r["revenue_yoy_pct"] = rev.get("revenue_yoy_pct")
        r["revenue_cum_yoy_pct"] = rev.get("revenue_cum_yoy_pct")
        eps = eps_map.get(code)
        r["eps"] = eps["eps"] if eps else None
        r["eps_period"] = f"{eps['eps_year']}年Q{eps['eps_quarter']}" if eps else None
        disp = disposition_map.get(code)
        r["is_disposition"] = disp is not None
        r["disposition_reason"] = disp["reason"] if disp else None
        r["is_attention"] = code in attention_set

        val = valuation_map.get(code, {})
        r["pe_ratio"] = val.get("pe_ratio")
        r["dividend_yield"] = val.get("dividend_yield")
        r["pb_ratio"] = val.get("pb_ratio")

        holder = holder_map.get(code, {})
        r["holders_1000"] = holder.get("holders_1000")
        r["holders_1000_change"] = holder.get("holders_1000_change")
        r["holders_report_date"] = holder.get("report_date")
        # 大戶人數太少時（基數小），人數增減 1、2 人就是幾十%的變化，統計上沒有意義，
        # 這種情況不列入評分依據，並在結果裡標記出來讓你自己判斷要不要參考這個數字
        r["holders_reliable"] = r["holders_1000"] is not None and r["holders_1000"] >= MIN_RELIABLE_HOLDERS

        # 籌碼與營收背離警示：近20日籌碼明顯偏多、但營收年增卻明顯衰退，
        # 代表買盤可能是消息面／題材面推動、不是基本面支撐，這種背離本身是警訊而非加分
        r["chip_revenue_divergence"] = bool(
            r["chip_bias_20"] is not None and r["chip_bias_20"] > 20
            and r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] < -10
        )

        # 綜合評分：純粹統計「符合你設定的低接＋體質＋籌碼條件」的程度，不是預測、不是買進訊號
        score = 0
        if r["revenue_mom_pct"] is not None and r["revenue_mom_pct"] > 0:
            score += 1
        if r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] > 0:
            score += 1
        if r["revenue_cum_yoy_pct"] is not None and r["revenue_cum_yoy_pct"] > 0:
            score += 1
        if r["eps"] is not None and r["eps"] > 0:
            score += 1
        if r["ma20_slope_pct"] is not None and r["ma20_slope_pct"] > 3:
            score += 1
        # 本益比：沒有「絕對合理值」，這裡只用寬鬆的門檻標示相對便宜／偏貴，
        # 缺值（近四季虧損等）不加分也不扣分，避免誤把轉機股當成地雷股
        r["pe_high"] = r["pe_ratio"] is not None and r["pe_ratio"] > 40
        if r["pe_ratio"] is not None and 0 < r["pe_ratio"] <= 20:
            score += 1
        elif r["pe_high"]:
            score -= 1
        if r["chip_revenue_divergence"]:
            score -= 2  # 籌碼買超但營收衰退：視為警訊，不給籌碼加分，額外倒扣
        elif r["chip_bias_20"] is not None and r["chip_bias_20"] > 0:
            score += 1
        if r["holders_reliable"] and r["holders_1000_change"] is not None and r["holders_1000_change"] > 0:
            score += 1
        # 處置公告：如果本來就是靠「處置回檔低接」這個理由才入選，處置本身就是進場論點
        # 的一部分，不倒扣；如果是條件A（一般拉回）卻意外中處置，才視為額外風險倒扣
        if "disposition_pullback" not in r["entry_type"] and r["is_disposition"]:
            score -= 3
        if r["is_attention"]:
            score -= 1
        # 「出貨」風險粗略警示：近20日籌碼明顯偏空且大戶人數減少 → 拉回可能不是健康換手
        r["distribution_risk"] = bool(
            r["chip_bias_20"] is not None and r["chip_bias_20"] < -10
            and r["holders_reliable"] and r["holders_1000_change"] is not None and r["holders_1000_change"] < 0
        )
        if r["distribution_risk"]:
            score -= 2
        r["fit_score"] = score
        # 進場參考價＝布林下軌（拉回低接的技術參考價，不是預測明天價格）
        r["entry_ref_price"] = r["boll_lower"]

    if long_term:
        with ThreadPoolExecutor(max_workers=6) as pool:
            future_map = {pool.submit(compute_long_term_bull_pct, r["code"]): r for r in results}
            for fut in as_completed(future_map):
                try:
                    future_map[fut]["long_term_bull_pct"] = fut.result()
                except Exception:
                    future_map[fut]["long_term_bull_pct"] = None
    else:
        for r in results:
            r["long_term_bull_pct"] = None

    results.sort(key=lambda r: (-r["fit_score"], r["boll_level"]))

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "boll_level_threshold": boll_level_threshold,
        "trend_days": trend_days,
        "min_trade_value": min_trade_value,
        "long_term": bool(long_term),
        "candidates_scanned": len(candidates) + len(disposition_map),
        "results": results,
    }
    with _screener_lock:
        _screener_cache[cache_key] = (time.time(), payload)
    return payload


# ---------- 選股篩選：放空篩選（脫離布林上軌 + 隔天進處置） ----------

_short_screener_cache = {}
_short_screener_lock = threading.Lock()


def _next_trading_day_roc():
    """明天（若遇週六日則順延到下週一）的民國年日期字串，格式跟處置公告的
    DispositionPeriod 起始日一致。不含台灣國定假日行事曆，遇連假會有落差，
    這是本工具目前的已知限制。"""
    t = time.time() + 86400
    lt = time.localtime(t)
    while lt.tm_wday >= 5:  # 5=六, 6=日
        t += 86400
        lt = time.localtime(t)
    return f"{lt.tm_year - 1911}/{lt.tm_mon:02d}/{lt.tm_mday:02d}"


def _disposition_period_start(period_str):
    for sep in ("～", "~", "-"):
        if sep in period_str:
            return period_str.split(sep)[0].strip()
    return None


def _bollinger_breakout_check(rows, period=20, k=2):
    """跟 compute_bollinger_now 的差別：這裡不把 pct_b 夾在 [0,1]，
    而是算出「收盤價相對上軌高出多少%」，才能分辨『貼著上軌』跟『已經噴出上軌一大截』。"""
    closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    sd = (sum((c - mean) ** 2 for c in window) / period) ** 0.5
    upper = mean + k * sd
    if upper <= 0:
        return None
    close = closes[-1]
    return {
        "close": close, "upper": round(upper, 2), "mid": round(mean, 2), "lower": round(mean - k * sd, 2),
        "breakout_pct": round((close - upper) / upper * 100, 2),
    }


def run_short_screener(min_trade_value=0):
    """放空篩選：找「股價已經脫離布林通道上軌（收盤價高於上軌，籌碼面偏向超漲）」
    且「下一個交易日就要開始被列為處置股」的股票——處置股開始執行當天，因為撮合
    方式改成人工管制、每筆委託都要收足全額價金，流動性瞬間變差，籌碼派對前一天
    股價通常已經被炒得偏離均值，是台股常見的短線放空切入參考日，但不保證一定
    下跌，處置後也可能軋空。這是規則過濾出的觀察名單，不是進場建議。"""
    cache_key = int(min_trade_value)
    with _short_screener_lock:
        hit = _short_screener_cache.get(cache_key)
        if hit and time.time() - hit[0] < 900:
            return hit[1]

    disposition_map = fetch_disposition()
    next_day = _next_trading_day_roc()
    upcoming = {
        code: info for code, info in disposition_map.items()
        if _disposition_period_start(info.get("period", "")) == next_day
    }

    def check_one(code, info):
        rows = fetch_stock_daily_rows(code, months=3)
        if not rows:
            return None
        boll = _bollinger_breakout_check(rows)
        if not boll or boll["breakout_pct"] <= 0:
            return None
        recent_values = [safe_float(r[2]) for r in rows[-20:] if safe_float(r[2]) is not None]
        avg_trade_value = sum(recent_values) / len(recent_values) if recent_values else 0
        if min_trade_value > 0 and avg_trade_value < min_trade_value:
            return None
        return {
            "code": code, "name": info.get("name", ""),
            "close": boll["close"], "boll_upper": boll["upper"], "boll_mid": boll["mid"],
            "boll_lower": boll["lower"], "breakout_pct": boll["breakout_pct"],
            "disposition_reason": info.get("reason", ""),
            "disposition_period": info.get("period", ""),
            "disposition_start_date": next_day,
            "avg_trade_value_wan": round(avg_trade_value / 10000),
        }

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_one, code, info) for code, info in upcoming.items()]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                results.append(r)
    results.sort(key=lambda r: r["breakout_pct"], reverse=True)

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "next_trading_day": next_day,
        "min_trade_value": min_trade_value,
        "disposition_candidates_scanned": len(upcoming),
        "results": results,
    }
    with _short_screener_lock:
        _short_screener_cache[cache_key] = (time.time(), payload)
    return payload


# ---------- 選股篩選：高點反轉黑K（放空短線觸發訊號）----------

_reversal_screener_cache = {}
_reversal_screener_lock = threading.Lock()


def fetch_today_ohlc_snapshot():
    """全市場今日開高低收＋成交量（一次 API 呼叫涵蓋所有上市個股），直接來自證交所，
    當天收盤後就有，不像 Yahoo 有時候要延遲一兩天才回補最新一天。用來低成本地先篩出
    「今天收黑K、且上影線夠長」的候選股，再對這些候選股才去抓歷史資料細算。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    data = fetch_json(url, ttl=300)
    out = {}
    for row in data:
        code = row.get("Code", "")
        if len(code) != 4 or not code.isdigit() or code.startswith("00"):
            continue
        o = safe_float(row.get("OpeningPrice"))
        h = safe_float(row.get("HighestPrice"))
        l = safe_float(row.get("LowestPrice"))
        c = safe_float(row.get("ClosingPrice"))
        vol = safe_float(row.get("TradeVolume"))
        if None in (o, h, l, c) or h <= 0:
            continue
        out[code] = {"name": row.get("Name", ""), "open": o, "high": h, "low": l, "close": c, "volume": vol}
    return out


def run_reversal_short_screener(near_high_pct=3.0, min_shadow_ratio=1.0, min_trade_value=0):
    """抓「衝高後拉回」的反轉黑K：今天股價逼近或創近20日新高，卻收出上影線夠長的黑K
    （代表高點有明顯賣壓、當天買盤沒能守住），用來抓短線放空的早期轉弱訊號——
    比「多頭轉弱（月線下彎）」篩選器更早一步，月線甚至可能都還沒轉向。基本面／籌碼／
    融券資料只當輔助確認，主要訊號是當天這根K棒的型態本身。跟其他篩選器一樣，
    這是對已發生K棒型態的客觀統計，不是對明天走勢的預測。"""
    cache_key = (round(near_high_pct, 2), round(min_shadow_ratio, 2), int(min_trade_value))
    with _reversal_screener_lock:
        hit = _reversal_screener_cache.get(cache_key)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]

    ohlc = fetch_today_ohlc_snapshot()

    # 第一階段：光用今天的開高低收就能算出「上影線黑K」，完全不用額外打 API，
    # 把候選股數量壓到可以接受的範圍，再對這些候選股抓歷史資料細算。
    stage1 = []
    for code, v in ohlc.items():
        o, h, c = v["open"], v["high"], v["close"]
        if c >= o:
            continue  # 不是黑K（收盤沒有比開盤低），跳過
        body = o - c
        upper_shadow = h - o
        if body <= 0 or upper_shadow <= 0:
            continue
        shadow_ratio = upper_shadow / body
        if shadow_ratio < min_shadow_ratio:
            continue
        stage1.append((code, v, shadow_ratio))
    stage1.sort(key=lambda x: -x[2])
    candidates = stage1[:MAX_TREND_CANDIDATES]

    today = time.localtime()
    today_roc = f"{today.tm_year - 1911}/{today.tm_mon:02d}/{today.tm_mday:02d}"

    def check_one(item):
        code, v, shadow_ratio = item
        rows = fetch_stock_daily_rows(code, months=2)
        if rows and rows[-1][0] == today_roc:
            rows = rows[:-1]  # 避免 Yahoo 剛好已經回補今天，跟自己比較高點
        if len(rows) < 20:
            return None

        highs = [safe_float(r[4]) for r in rows if safe_float(r[4]) is not None]
        if len(highs) < 20:
            return None
        prior_high = max(highs[-20:])
        if prior_high <= 0 or v["high"] < prior_high * (1 - near_high_pct / 100):
            return None  # 沒有逼近／創近20日新高，不算「高點」反轉

        recent_values = [safe_float(r[2]) for r in rows[-20:] if safe_float(r[2]) is not None]
        avg_trade_value = sum(recent_values) / len(recent_values) if recent_values else 0
        if min_trade_value > 0 and avg_trade_value < min_trade_value:
            return None

        volumes = [safe_float(r[1]) for r in rows[-5:] if safe_float(r[1]) is not None]
        avg_vol_5 = sum(volumes) / len(volumes) if volumes else None
        volume_confirmed = bool(avg_vol_5 and v["volume"] and v["volume"] > avg_vol_5)

        return {
            "code": code,
            "name": v["name"],
            "open": v["open"],
            "high": v["high"],
            "low": v["low"],
            "close": v["close"],
            "shadow_ratio": round(shadow_ratio, 2),
            "prior_high": round(prior_high, 2),
            "pct_from_high": round((v["close"] - prior_high) / prior_high * 100, 2),
            "avg_trade_value_wan": round(avg_trade_value / 10000),
            "volume_confirmed": volume_confirmed,
            "chip_bias_5": compute_volume_bias(rows, 5),
            "chip_bias_20": compute_volume_bias(rows, 20),
        }

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_one, item) for item in candidates]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                results.append(r)

    revenue_map = fetch_monthly_revenue()
    eps_map = fetch_eps()
    valuation_map = fetch_valuation()
    disposition_map = fetch_disposition()
    attention_set = fetch_attention()
    margin_map = fetch_margin_data()
    try:
        holder_map = get_holder_data()
    except Exception:
        holder_map = {}

    # 融券限額不存在或為 0：這檔股票根本不能用融券放空，直接排除
    filtered = []
    for r in results:
        margin = margin_map.get(r["code"], {})
        r["margin_short_limit"] = margin.get("margin_short_limit")
        r["margin_short_balance"] = margin.get("margin_short_balance")
        r["margin_short_usage_pct"] = margin.get("margin_short_usage_pct")
        if r["margin_short_limit"] and r["margin_short_limit"] > 0:
            filtered.append(r)
    results = filtered

    for r in results:
        code = r["code"]
        rev = revenue_map.get(code, {})
        r["industry"] = rev.get("industry", "未分類")
        r["revenue_mom_pct"] = rev.get("revenue_mom_pct")
        r["revenue_yoy_pct"] = rev.get("revenue_yoy_pct")
        r["revenue_cum_yoy_pct"] = rev.get("revenue_cum_yoy_pct")
        eps = eps_map.get(code)
        r["eps"] = eps["eps"] if eps else None
        r["eps_period"] = f"{eps['eps_year']}年Q{eps['eps_quarter']}" if eps else None
        disp = disposition_map.get(code)
        r["is_disposition"] = disp is not None
        r["disposition_reason"] = disp["reason"] if disp else None
        r["is_attention"] = code in attention_set

        val = valuation_map.get(code, {})
        r["pe_ratio"] = val.get("pe_ratio")
        r["dividend_yield"] = val.get("dividend_yield")

        holder = holder_map.get(code, {})
        r["holders_1000"] = holder.get("holders_1000")
        r["holders_1000_change"] = holder.get("holders_1000_change")
        r["holders_reliable"] = r["holders_1000"] is not None and r["holders_1000"] >= MIN_RELIABLE_HOLDERS

        # 綜合評分：主要訊號是K棒型態本身（能不能進候選清單看的是上影線比例），
        # 這裡的分數只是拿量能／基本面／籌碼當「輔助確認」用，不是主要判斷依據
        score = 0
        if r["volume_confirmed"]:
            score += 1  # 當天爆量收黑K，賣壓比較有說服力，不是隨便一根雜訊K棒
        if r["chip_bias_5"] is not None and r["chip_bias_5"] < 0:
            score += 1
        if r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] < 0:
            score += 1
        if r["eps"] is not None and r["eps"] < 0:
            score += 1
        r["pe_high"] = r["pe_ratio"] is not None and r["pe_ratio"] > 40
        r["pe_missing"] = r["pe_ratio"] is None
        if r["pe_high"] or r["pe_missing"]:
            score += 1
        r["margin_crowded"] = r["margin_short_usage_pct"] is not None and r["margin_short_usage_pct"] >= 80
        if r["margin_crowded"]:
            score -= 2
        if r["is_disposition"] or r["is_attention"]:
            score -= 3
        r["fit_score"] = score
        # 參考價：當天最高價（黑K拒絕的高點，短線放空常用的停損／壓力參考）
        r["entry_ref_price"] = r["high"]

    results.sort(key=lambda r: (-r["fit_score"], -r["shadow_ratio"]))

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "near_high_pct": near_high_pct,
        "min_shadow_ratio": min_shadow_ratio,
        "min_trade_value": min_trade_value,
        "candidates_scanned": len(candidates),
        "results": results,
    }
    with _reversal_screener_lock:
        _reversal_screener_cache[cache_key] = (time.time(), payload)
    return payload
