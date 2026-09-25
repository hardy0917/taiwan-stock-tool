"""
市場資料：即時報價、大盤/櫃買/費半/台指期指數、個股日線與分鐘K、當日分時、
日內模式統計、股票代碼目錄、全市場快照。全部是原始資料的抓取與格式轉換，
不含任何選股/評分邏輯。
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter

from app_core import HEADERS, fetch_json, safe_float, throttled_urlopen


def parse_mis_quote(raw):
    out = []
    for item in raw.get("msgArray", []):
        def f(key, default=None):
            v = item.get(key)
            try:
                return float(v) if v not in (None, "", "-") else default
            except ValueError:
                return default

        price = f("z")
        if price is None:
            price = f("y")  # 未開盤/收盤時 z 可能是 '-'，退回昨收
        prev_close = f("y")
        change = None
        change_pct = None
        if price is not None and prev_close:
            change = round(price - prev_close, 2)
            change_pct = round(change / prev_close * 100, 2) if prev_close else None
        out.append({
            "code": item.get("c"),
            "name": item.get("n"),
            "price": price,
            "prevClose": prev_close,
            "change": change,
            "changePct": change_pct,
            "open": f("o"),
            "high": f("h"),
            "low": f("l"),
            "volume": f("v"),
            "time": item.get("t"),
            "date": item.get("d"),
        })
    return out


# 逐代碼快取，不是逐個「查詢字串」快取：不同使用者的觀察清單常常重疊
# （2330、2317這種常見代碼幾乎人人都有），用代碼當 key 才能讓大家共用同一份快取，
# 不然像以前把整串代碼串成一個 URL 當 key，兩個使用者的代碼清單只要順序或組合
# 不完全一樣，就會被當成不同的查詢，等於每次都是即時查。
_quote_cache = {}  # code -> (timestamp, quote)
_quote_cache_lock = threading.Lock()
QUOTE_TTL = 8


def fetch_quotes_for_codes(codes):
    """查一批股票代碼的即時報價，只對「快取已經過期的代碼」才真的發請求給證交所，
    新鮮的直接從快取回傳。"""
    now = time.time()
    fresh = {}
    stale_codes = []
    with _quote_cache_lock:
        for code in codes:
            hit = _quote_cache.get(code)
            if hit and now - hit[0] < QUOTE_TTL:
                fresh[code] = hit[1]
            else:
                stale_codes.append(code)

    if stale_codes:
        ex_list = []
        for c in stale_codes:
            ex_list.append(f"tse_{c}.tw")
            ex_list.append(f"otc_{c}.tw")
        url = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch="
               + urllib.parse.quote("|".join(ex_list)) + "&json=1&delay=0")
        raw = fetch_json(url, ttl=QUOTE_TTL)
        quotes = parse_mis_quote(raw)
        merged = {}
        for q in quotes:
            # 每檔代碼只留第一筆有效資料（tse 優先於 otc，跟原本的合併邏輯一致）
            if q["code"] not in merged or (merged[q["code"]]["price"] is None and q["price"] is not None):
                merged[q["code"]] = q
        with _quote_cache_lock:
            for code, q in merged.items():
                _quote_cache[code] = (now, q)
        fresh.update(merged)

    return [fresh[c] for c in codes if c in fresh]


# ---------- 大盤／櫃買／費半／台指期指數 ----------

def _mis_index_quote(ex_ch, name):
    """從證交所 MIS 即時揭示抓大盤類指數（跟個股報價同一個端點、同一種欄位格式）"""
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&json=1&delay=0"
    raw = fetch_json(url, ttl=15)
    arr = raw.get("msgArray") or []
    if not arr:
        return None
    item = arr[0]
    price = safe_float(item.get("z"))
    prev_close = safe_float(item.get("y"))
    if price is None:
        price = prev_close
    change = round(price - prev_close, 2) if price is not None and prev_close else None
    change_pct = round(change / prev_close * 100, 2) if change is not None and prev_close else None
    return {
        "name": name, "price": price, "prev_close": prev_close,
        "change": change, "change_pct": change_pct, "time": item.get("t"),
    }


def fetch_yahoo_quote(symbol, name, ttl=60):
    """用 Yahoo Finance 公開圖表 API 的 meta 欄位抓即時（或近即時）報價，
    通用於美股指數、外匯等 TWSE MIS 沒有的標的。"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=5d"
        data = fetch_json(url, ttl=ttl)
        meta = ((data.get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        change = round(price - prev_close, 4) if price is not None and prev_close else None
        change_pct = round(change / prev_close * 100, 2) if change is not None and prev_close else None
        return {"name": name, "price": price, "prev_close": prev_close,
                "change": change, "change_pct": change_pct, "time": None}
    except Exception:
        return None


def fetch_sox_index():
    """費城半導體指數（美股，用 Yahoo Finance 公開圖表 API 的 meta 欄位）"""
    return fetch_yahoo_quote("^SOX", "費城半導體指數")


def fetch_txf_futures():
    """台指期近月合約（日盤／夜盤共用同一個合約，依查詢當下所屬的交易時段回報最新成交）"""
    try:
        req = urllib.request.Request(
            "https://mis.taifex.com.tw/futures/api/getQuoteList",
            data=b'{"MarketType":"0","SymbolType":"F","KindID":"1"}',
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        with throttled_urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        quotes = ((data.get("RtData") or {}).get("QuoteList")) or []
        txf = next((q for q in quotes if q.get("SymbolID") == "TXF-S"), None)
        if not txf:
            return None
        price = safe_float(txf.get("CLastPrice"))
        prev_close = safe_float(txf.get("CRefPrice"))
        change = safe_float(txf.get("CDiff"))
        change_pct = round(change / prev_close * 100, 2) if change is not None and prev_close else None
        return {"name": "台指期（近月，日盤／夜盤共用）", "price": price, "prev_close": prev_close,
                "change": change, "change_pct": change_pct, "time": txf.get("CTime")}
    except Exception:
        return None


def fetch_indices():
    return {
        "taiex": _mis_index_quote("tse_t00.tw", "台股加權指數"),
        "tpex": _mis_index_quote("otc_o00.tw", "櫃買指數"),
        "sox": fetch_sox_index(),
        "txf": fetch_txf_futures(),
        "usdjpy": fetch_yahoo_quote("JPY=X", "美元／日圓"),
        "usdtwd": fetch_yahoo_quote("TWD=X", "美元／新台幣"),
    }


# key -> (Yahoo Finance symbol, 顯示名稱)。台指期沒有可靠的免費歷史K線來源，
# 用加權指數（現貨）的走勢代替，因為近月期貨價格幾乎貼著現貨走。匯率（JPY=X／TWD=X）
# 是 Yahoo 的標準寫法，代表「1美元兌換多少該幣別」。
INDEX_SYMBOLS = {
    "taiex": ("^TWII", "台股加權指數"),
    "tpex": ("^TWOII", "櫃買指數"),
    "sox": ("^SOX", "費城半導體指數"),
    "txf": ("^TWII", "台指期（近月，用加權指數現貨走勢代替，期貨無公開歷史K線來源）"),
    "usdjpy": ("JPY=X", "美元／日圓"),
    "usdtwd": ("TWD=X", "美元／新台幣"),
}


def _yahoo_range_str(months):
    """把「月數」換算成 Yahoo Finance chart API 的 range 參數。
    超過 10 年一律用 max，一次拿到該標的全部可查歷史（Yahoo 單次請求即可回傳，
    比 TWSE STOCK_DAY 逐月請求快非常多，也才有辦法支援長達 20 年的區間。"""
    months = max(months, 1)
    if months <= 24:
        return f"{months}mo"
    years = -(-months // 12)  # 無條件進位
    return f"{years}y" if years <= 10 else "max"


def _yahoo_chart_result_to_rows(data, intraday=False):
    """把 Yahoo Finance chart API 的回應轉成跟 TWSE STOCK_DAY 一樣的 row 格式，
    這樣前端可以直接沿用個股走勢圖同一套解析／繪圖邏輯。intraday=True 時日期欄位
    改成含時分的完整時間字串（給分鐘K回測用），否則維持民國年日期字串。"""
    result = ((data.get("chart") or {}).get("result")) or []
    if not result:
        return []
    r0 = result[0]
    timestamps = r0.get("timestamp") or []
    quote0 = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote0.get("open") or []
    highs = quote0.get("high") or []
    lows = quote0.get("low") or []
    closes = quote0.get("close") or []
    volumes = quote0.get("volume") or []

    rows = []
    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        dt = time.localtime(ts)
        if intraday:
            date_label = f"{dt.tm_year:04d}-{dt.tm_mon:02d}-{dt.tm_mday:02d} {dt.tm_hour:02d}:{dt.tm_min:02d}"
        else:
            date_label = f"{dt.tm_year - 1911}/{dt.tm_mon:02d}/{dt.tm_mday:02d}"
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        h = highs[i] if i < len(highs) and highs[i] is not None else c
        l = lows[i] if i < len(lows) and lows[i] is not None else c
        v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
        # Yahoo 沒有直接提供成交金額欄位，用「成交量 × 收盤價」估算，
        # 供流動性過濾等只需要量級（而非精確金額）的用途使用。
        value_est = round(v * c)
        rows.append([date_label, str(int(v)), str(value_est), str(round(o, 2)), str(round(h, 2)),
                     str(round(l, 2)), str(round(c, 2)), "", "", ""])
    return rows


def fetch_index_daily_rows(key, months=3):
    entry = INDEX_SYMBOLS.get(key)
    if not entry:
        return None, None
    symbol, display_name = entry
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?interval=1d&range={_yahoo_range_str(months)}")
    data = fetch_json(url, ttl=300)
    return display_name, _yahoo_chart_result_to_rows(data)


# ---------- 個股日線／分鐘K ----------

def fetch_stock_daily_rows(code, months=3):
    """透過 Yahoo Finance 一次性抓個股日線資料（單一請求，取代 TWSE STOCK_DAY
    逐月請求的作法），速度快很多，也才能支援數年～數十年的長期區間。"""
    range_str = _yahoo_range_str(months)
    for suffix in (".TW", ".TWO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range={range_str}"
        try:
            data = fetch_json(url, ttl=300)
        except Exception:
            continue
        rows = _yahoo_chart_result_to_rows(data)
        if rows:
            return rows
    return []


def fetch_stock_daily_rows_for_chart(code, months=3):
    """給單一股票走勢圖用：Yahoo 收盤後常常要延遲一段時間才會回補最新一兩個
    交易日的資料，導致圖表看起來卡在前幾天。這裡額外用 TWSE 官方當月資料補上
    Yahoo 還沒回補的最近交易日。只用在使用者主動點開單一股票的時候，
    不用在全市場批次掃描（選股篩選）裡，避免拖慢掃描速度。"""
    rows = fetch_stock_daily_rows(code, months=months)
    if not rows:
        return rows
    last_date = rows[-1][0]
    today = time.localtime()
    date_str = f"{today.tm_year:04d}{today.tm_mon:02d}01"
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date_str}&stockNo={code}&response=json"
    try:
        d = fetch_json(url, ttl=1800)
        if d.get("stat") == "OK":
            extra = [r for r in d.get("data", []) if r[0] > last_date]
            rows = rows + extra
    except Exception:
        pass
    return rows


BACKTEST_INTRADAY_MAX_DAYS = {"5m": 59, "60m": 729}  # Yahoo Finance 免費資料源的區間上限


def fetch_stock_intraday_rows_for_backtest(code, interval, days):
    """給回測用：抓 Yahoo Finance 分鐘K。5分K最長約60天、60分K最長約2年，
    這是 Yahoo 免費資料源的限制，超過上限會自動縮減到上限天數。"""
    max_days = BACKTEST_INTRADAY_MAX_DAYS.get(interval, 59)
    days = max(1, min(int(days), max_days))
    for suffix in (".TW", ".TWO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval={interval}&range={days}d"
        try:
            data = fetch_json(url, ttl=1800)
        except Exception:
            continue
        rows = _yahoo_chart_result_to_rows(data, intraday=True)
        if rows:
            return rows
    return []


def fetch_intraday(code):
    """抓最近一個「有資料」的交易日分時走勢。用 range=5d 一次多抓幾天份的
    1 分鐘資料，再取其中最後一個出現的日期──這樣遇到假日、還沒開盤、
    或連假之後，會自動退回最近一個真正有交易的日子，而不是抓「今天」
    抓到空的。"""
    for suffix in (".TW", ".TWO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1m&range=5d"
        try:
            data = fetch_json(url, ttl=30)
        except Exception:
            continue
        result = (data.get("chart") or {}).get("result")
        if not result:
            continue
        r0 = result[0]
        timestamps = r0.get("timestamp") or []
        quote0 = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote0.get("close") or []

        trade_date = None
        for ts, c in zip(reversed(timestamps), reversed(closes)):
            if c is not None:
                trade_date = time.strftime("%Y-%m-%d", time.localtime(ts))
                break
        if trade_date is None:
            continue

        points = []
        for ts, c in zip(timestamps, closes):
            if c is None:
                continue
            if time.strftime("%Y-%m-%d", time.localtime(ts)) != trade_date:
                continue
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            points.append({"time": t, "price": round(c, 2)})
        meta = r0.get("meta") or {}
        return {
            "points": points,
            "trade_date": trade_date,
            "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
            "day_high": meta.get("regularMarketDayHigh"),
            "day_low": meta.get("regularMarketDayLow"),
        }
    return None


INTRADAY_PATTERN_BUCKET_MIN = 15
INTRADAY_SESSION_MIN = 270  # 09:00-13:30
_INTRADAY_PERIOD_BOUNDS = [(0, 45), (45, 90), (90, 135), (135, 180), (180, 225), (225, 270)]
_INTRADAY_PERIOD_LABELS = ["09:00-09:45", "09:45-10:30", "10:30-11:15", "11:15-12:00", "12:00-12:45", "12:45-13:30"]


def fetch_intraday_pattern(code):
    """統計近一個月（約20個交易日）的日內模式：平均走勢曲線（含每日高低變異帶）、
    當日高/低點通常出現在哪個時段、各時段的典型震幅、開盤跳空與回補比例。
    這些全部是「過去已經發生過的事」的客觀統計整理，不是對明天的預測，
    樣本數通常只有20天上下，不構成任何勝率保證。"""
    rows_by_day = {}
    for suffix in (".TW", ".TWO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=5m&range=1mo"
        try:
            data = fetch_json(url, ttl=1800)
        except Exception:
            continue
        result = (data.get("chart") or {}).get("result")
        if not result:
            continue
        r0 = result[0]
        timestamps = r0.get("timestamp") or []
        if not timestamps:
            continue
        quote0 = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote0.get("close") or []
        for ts, c in zip(timestamps, closes):
            if c is None:
                continue
            dt = time.localtime(ts)
            minute_of_session = (dt.tm_hour * 60 + dt.tm_min) - 9 * 60
            if minute_of_session < 0 or minute_of_session >= INTRADAY_SESSION_MIN:
                continue
            day_key = time.strftime("%Y-%m-%d", dt)
            rows_by_day.setdefault(day_key, []).append((minute_of_session, c))
        break
    if not rows_by_day:
        return None

    n_buckets = INTRADAY_SESSION_MIN // INTRADAY_PATTERN_BUCKET_MIN

    def bucket_label(i):
        h, m = divmod(9 * 60 + i * INTRADAY_PATTERN_BUCKET_MIN, 60)
        return f"{h:02d}:{m:02d}"

    per_day_bucket_pct = []
    per_day_bucket_range_pct = []
    high_periods, low_periods = [], []
    day_first_price, day_last_close = {}, {}

    for day in sorted(rows_by_day.keys()):
        points = sorted(rows_by_day[day])
        if len(points) < 5:
            continue
        open_price = points[0][1]
        day_first_price[day] = open_price
        day_last_close[day] = points[-1][1]

        buckets = {}
        for minute, price in points:
            b = min(minute // INTRADAY_PATTERN_BUCKET_MIN, n_buckets - 1)
            buckets.setdefault(b, []).append(price)
        day_bucket_pct, day_bucket_range_pct = {}, {}
        for b, prices in buckets.items():
            avg_price = sum(prices) / len(prices)
            day_bucket_pct[b] = (avg_price - open_price) / open_price * 100
            day_bucket_range_pct[b] = (max(prices) - min(prices)) / open_price * 100
        per_day_bucket_pct.append(day_bucket_pct)
        per_day_bucket_range_pct.append(day_bucket_range_pct)

        high_minute = max(points, key=lambda p: p[1])[0]
        low_minute = min(points, key=lambda p: p[1])[0]
        for idx, (lo, hi) in enumerate(_INTRADAY_PERIOD_BOUNDS):
            if lo <= high_minute < hi:
                high_periods.append(_INTRADAY_PERIOD_LABELS[idx])
                break
        for idx, (lo, hi) in enumerate(_INTRADAY_PERIOD_BOUNDS):
            if lo <= low_minute < hi:
                low_periods.append(_INTRADAY_PERIOD_LABELS[idx])
                break

    avg_path = []
    for b in range(n_buckets):
        vals = [d[b] for d in per_day_bucket_pct if b in d]
        if not vals:
            continue
        avg_path.append({
            "time": bucket_label(b),
            "avg_pct": round(sum(vals) / len(vals), 3),
            "min_pct": round(min(vals), 3),
            "max_pct": round(max(vals), 3),
        })

    volatility_by_bucket = []
    for b in range(n_buckets):
        vals = [d[b] for d in per_day_bucket_range_pct if b in d]
        if not vals:
            continue
        volatility_by_bucket.append({"time": bucket_label(b), "avg_range_pct": round(sum(vals) / len(vals), 3)})

    high_hist = Counter(high_periods)
    low_hist = Counter(low_periods)

    gap_up = gap_down = gap_up_filled = gap_down_filled = 0
    gap_pcts = []
    valid_days = [d for d in sorted(rows_by_day.keys()) if d in day_first_price]
    for i in range(1, len(valid_days)):
        prev_day, cur_day = valid_days[i - 1], valid_days[i]
        prev_close = day_last_close.get(prev_day)
        cur_open = day_first_price.get(cur_day)
        if prev_close is None or cur_open is None:
            continue
        gap_pct = (cur_open - prev_close) / prev_close * 100
        gap_pcts.append(gap_pct)
        cur_prices = [p for _, p in rows_by_day[cur_day]]
        if gap_pct > 0.1:
            gap_up += 1
            if min(cur_prices) <= prev_close:
                gap_up_filled += 1
        elif gap_pct < -0.1:
            gap_down += 1
            if max(cur_prices) >= prev_close:
                gap_down_filled += 1

    gap_stats = {
        "gap_up_days": gap_up,
        "gap_down_days": gap_down,
        "gap_up_filled_pct": round(gap_up_filled / gap_up * 100, 1) if gap_up else None,
        "gap_down_filled_pct": round(gap_down_filled / gap_down * 100, 1) if gap_down else None,
        "avg_abs_gap_pct": round(sum(abs(g) for g in gap_pcts) / len(gap_pcts), 2) if gap_pcts else None,
    }

    return {
        "days_analyzed": len(per_day_bucket_pct),
        "avg_path": avg_path,
        "volatility_by_bucket": volatility_by_bucket,
        "high_time_histogram": [{"period": p, "count": high_hist.get(p, 0)} for p in _INTRADAY_PERIOD_LABELS],
        "low_time_histogram": [{"period": p, "count": low_hist.get(p, 0)} for p in _INTRADAY_PERIOD_LABELS],
        "gap_stats": gap_stats,
    }


# ---------- 股票目錄／全市場快照 ----------

def fetch_stock_directory():
    """代碼＋名稱清單，合併上市（TWSE）與上櫃（TPEx）個股，給前端「加入觀察清單」
    的自動完成搜尋用。上市直接用 STOCK_DAY_ALL（含一般股票與ETF）；上櫃來源涵蓋
    公司債ETF／權證等上萬檔非個股商品，只保留4碼純數字的一般股票代碼，過濾雜訊。"""
    out = []
    seen = set()
    try:
        twse = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", ttl=3600)
        for row in twse:
            code, name = row.get("Code", ""), row.get("Name", "")
            if code and name and code not in seen:
                seen.add(code)
                out.append({"code": code, "name": name})
    except Exception:
        pass
    try:
        tpex = fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", ttl=3600)
        for row in tpex:
            code = row.get("SecuritiesCompanyCode", "")
            name = row.get("CompanyName", "")
            if not (len(code) == 4 and code.isdigit()):
                continue
            if code and name and code not in seen:
                seen.add(code)
                out.append({"code": code, "name": name})
    except Exception:
        pass
    return out


def fetch_market_snapshot():
    """全市場今日收盤價與月平均價（一次 API 呼叫涵蓋所有上市個股）"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL"
    data = fetch_json(url, ttl=1800)
    out = {}
    for row in data:
        code = row.get("Code", "")
        # 只保留一般個股（4 碼數字、非 00 開頭），排除 ETF／權證／期信受益證券
        if len(code) != 4 or not code.isdigit() or code.startswith("00"):
            continue
        close = safe_float(row.get("ClosingPrice"))
        ma = safe_float(row.get("MonthlyAveragePrice"))
        if close is None or ma is None or ma <= 0:
            continue
        out[code] = {"name": row.get("Name", ""), "close": close, "monthly_avg": ma}
    return out


def fetch_stock_day_all():
    """全市場今日成交資訊原始資料（STOCK_DAY_ALL），給 /api/day_all 用；
    抽成獨立函式讓排程可以直接呼叫，不用在 server.py 裡硬寫 URL。"""
    return fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", ttl=300)
