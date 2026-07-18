"""
台股分析工具 - 本機伺服器
用純 Python 標準函式庫代理證交所 API（避開瀏覽器 CORS 限制），並提供前端網頁。
執行方式: python server.py
然後開啟瀏覽器: http://localhost:8787
"""
import json
import sys
import time
import threading
import webbrowser
import urllib.request
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8787
# 打包成 .exe（PyInstaller）執行時，用執行檔所在目錄找 static/；
# 用 python server.py 執行時，用這支程式所在目錄找 static/。
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockTool/1.0)"}

# 簡單快取，避免短時間內重複打證交所 API
_cache = {}
_cache_lock = threading.Lock()


def fetch_json(url, ttl=10):
    with _cache_lock:
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    with _cache_lock:
        _cache[url] = (time.time(), data)
    return data


def fetch_text(url, ttl=10):
    with _cache_lock:
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8-sig")
    with _cache_lock:
        _cache[url] = (time.time(), text)
    return text


def check_backend_health():
    """輕量探測：能不能連到證交所（不是本機伺服器本身，是本機伺服器→證交所這段）"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw&json=1&delay=0"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read(200)  # 只要證明連得到、有在回應，不用整包讀完
        return True
    except Exception:
        return False


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


def safe_float(v, default=None):
    if v in (None, "", "-", "－"):
        return default
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return default


def compute_ma20_series(rows):
    """rows: STOCK_DAY 的 data 陣列（[日期,量,額,開,高,低,收,漲跌,筆數,註記]）
    回傳依日期排序的 20 日均線（月線）數值序列"""
    closes = []
    for r in rows:
        c = safe_float(r[6])
        if c is not None:
            closes.append(c)
    if len(closes) < 20:
        return []
    return [sum(closes[i - 19:i + 1]) / 20 for i in range(19, len(closes))]


def compute_bollinger_now(rows, period=20, k=2):
    """回傳最新一天的布林通道（上軌／中軌／下軌）與「位階」（1～10，5.5＝中軌，
    10＝觸及上軌，1＝觸及下軌以下）。位階 ≤5 代表股價回檔到通道中線以下。"""
    closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((c - mean) ** 2 for c in window) / period
    sd = variance ** 0.5
    upper = mean + k * sd
    lower = mean - k * sd
    close = closes[-1]
    if upper == lower:
        level = 5.5
    else:
        pct_b = (close - lower) / (upper - lower)
        level = round(max(0.0, min(1.0, pct_b)) * 10, 1)
    return {"upper": round(upper, 2), "middle": round(mean, 2), "lower": round(lower, 2),
            "close": close, "level": level}


# ---------- 個股今日分時走勢（Yahoo Finance） ----------
# 證交所沒有公開的個股分時歷史 API，改用 Yahoo Finance 公開圖表 API（免金鑰、業界常見用法）。

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


def fetch_sox_index():
    """費城半導體指數（美股，用 Yahoo Finance 公開圖表 API 的 meta 欄位）"""
    try:
        data = fetch_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ESOX?interval=1d&range=5d", ttl=60)
        meta = ((data.get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        change = round(price - prev_close, 2) if price is not None and prev_close else None
        change_pct = round(change / prev_close * 100, 2) if change is not None and prev_close else None
        return {"name": "費城半導體指數", "price": price, "prev_close": prev_close,
                "change": change, "change_pct": change_pct, "time": None}
    except Exception:
        return None


def fetch_txf_futures():
    """台指期近月合約（日盤／夜盤共用同一個合約，依查詢當下所屬的交易時段回報最新成交）"""
    try:
        req = urllib.request.Request(
            "https://mis.taifex.com.tw/futures/api/getQuoteList",
            data=b'{"MarketType":"0","SymbolType":"F","KindID":"1"}',
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
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
    }


# key -> (Yahoo Finance symbol, 顯示名稱)。台指期沒有可靠的免費歷史K線來源，
# 用加權指數（現貨）的走勢代替，因為近月期貨價格幾乎貼著現貨走。
INDEX_SYMBOLS = {
    "taiex": ("^TWII", "台股加權指數"),
    "tpex": ("^TWOII", "櫃買指數"),
    "sox": ("^SOX", "費城半導體指數"),
    "txf": ("^TWII", "台指期（近月，用加權指數現貨走勢代替，期貨無公開歷史K線來源）"),
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


def _yahoo_chart_result_to_rows(data):
    """把 Yahoo Finance chart API 的回應轉成跟 TWSE STOCK_DAY 一樣的 row 格式，
    這樣前端可以直接沿用個股走勢圖同一套解析／繪圖邏輯。"""
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
        roc_date = f"{dt.tm_year - 1911}/{dt.tm_mon:02d}/{dt.tm_mday:02d}"
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        h = highs[i] if i < len(highs) and highs[i] is not None else c
        l = lows[i] if i < len(lows) and lows[i] is not None else c
        v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
        # Yahoo 沒有直接提供成交金額欄位，用「成交量 × 收盤價」估算，
        # 供流動性過濾等只需要量級（而非精確金額）的用途使用。
        value_est = round(v * c)
        rows.append([roc_date, str(int(v)), str(value_est), str(round(o, 2)), str(round(h, 2)),
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


# ---------- 大戶持股（集保股權分散表，每週更新）----------

TDCC_SNAPSHOT_FILE = BASE_DIR / "tdcc_snapshots.json"
BIG_HOLDER_BRACKET = "15"  # TDCC 標準持股分級：15 = 1,000,001股以上，一般俗稱「大戶（1,000張以上）」
TOTAL_BRACKET = "17"       # 17 = 全體合計（用來算佔比基準）
_tdcc_lock = threading.Lock()


def fetch_tdcc_holders():
    """集保股權分散表（開放資料）：每檔股票各持股級距的人數／股數，每週五更新一次"""
    text = fetch_text("https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5", ttl=21600)
    lines = text.strip().split("\n")
    report_date = None
    current = {}
    for line in lines[1:]:  # 第一行是標題列
        parts = line.strip().split(",")
        if len(parts) < 6:
            continue
        date, code, bracket, people, _shares, _pct = (p.strip() for p in parts[:6])
        if report_date is None:
            report_date = date
        if bracket == BIG_HOLDER_BRACKET:
            current.setdefault(code, {})["holders_1000"] = safe_float(people)
        elif bracket == TOTAL_BRACKET:
            current.setdefault(code, {})["total_holders"] = safe_float(people)
    return report_date, current


def load_tdcc_snapshots():
    if TDCC_SNAPSHOT_FILE.exists():
        try:
            return json.loads(TDCC_SNAPSHOT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def get_holder_data():
    """回傳 {code: {holders_1000, holders_1000_change, report_date, prev_report_date}}。
    change 是跟「上一次抓到的週報」比較；如果本機才剛開始跑這個工具、還沒跨過一次週報更新，
    change 會是 None（沒有比較基準，不是資料錯誤）。"""
    with _tdcc_lock:
        report_date, current = fetch_tdcc_holders()
        snapshots = load_tdcc_snapshots()
        if snapshots.get("latest_date") == report_date:
            prev = snapshots.get("prev") or {}
            prev_date = snapshots.get("prev_date")
        else:
            prev = snapshots.get("latest") or {}
            prev_date = snapshots.get("latest_date")
            snapshots = {
                "latest_date": report_date, "latest": current,
                "prev_date": prev_date, "prev": prev,
            }
            try:
                TDCC_SNAPSHOT_FILE.write_text(json.dumps(snapshots, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass

        out = {}
        for code, v in current.items():
            p = prev.get(code)
            change = None
            if p and p.get("holders_1000") is not None and v.get("holders_1000") is not None:
                change = v["holders_1000"] - p["holders_1000"]
            out[code] = {
                "holders_1000": v.get("holders_1000"),
                "holders_1000_change": change,
                "report_date": report_date,
                "prev_report_date": prev_date,
            }
        return out


def compute_volume_bias(rows, days):
    """量價背離代理指標：近N個交易日「上漲日成交量」減「下跌日成交量」的差，
    正值代表量能偏向上漲日、負值代表偏向下跌日。這不是真正的主力進出（那需要券商分點資料，
    公開資料無法取得），只是用價量關係推算的近似代理指標，回傳 -100～100。"""
    closes = [safe_float(r[6]) for r in rows]
    volumes = [safe_float(r[1]) for r in rows]
    n = len(rows)
    if n < days + 1:
        return None
    up_vol = down_vol = 0.0
    for i in range(n - days, n):
        if closes[i] is None or closes[i - 1] is None or volumes[i] is None:
            continue
        if closes[i] > closes[i - 1]:
            up_vol += volumes[i]
        elif closes[i] < closes[i - 1]:
            down_vol += volumes[i]
    total = up_vol + down_vol
    if total <= 0:
        return None
    return round((up_vol - down_vol) / total * 100, 1)


# ---------- 產業資金流向 ----------

def fetch_sector_flow():
    """依產業別彙總今日漲跌家數與成交值加權漲跌幅，作為資金流向的代理指標：
    成交值加權漲跌% 越高，代表資金越集中湧入該產業；越低代表資金流出。"""
    day_data = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", ttl=300)
    revenue_map = fetch_monthly_revenue()

    sectors = {}
    for row in day_data:
        code = row.get("Code", "")
        if len(code) != 4 or not code.isdigit() or code.startswith("00"):
            continue
        close = safe_float(row.get("ClosingPrice"))
        change = safe_float(row.get("Change"))
        value = safe_float(row.get("TradeValue"))
        if close is None or change is None or value is None or close <= 0:
            continue
        base = close - change
        change_pct = (change / base * 100) if base else 0
        industry = revenue_map.get(code, {}).get("industry", "未分類")

        s = sectors.setdefault(industry, {
            "advance": 0, "decline": 0, "flat": 0,
            "total_value": 0.0, "weighted_change_sum": 0.0, "stock_count": 0,
        })
        s["stock_count"] += 1
        s["total_value"] += value
        s["weighted_change_sum"] += change_pct * value
        if change_pct > 0.01:
            s["advance"] += 1
        elif change_pct < -0.01:
            s["decline"] += 1
        else:
            s["flat"] += 1

    results = []
    for industry, s in sectors.items():
        if s["stock_count"] < 2 or s["total_value"] <= 0:
            continue
        results.append({
            "industry": industry,
            "stock_count": s["stock_count"],
            "advance": s["advance"],
            "decline": s["decline"],
            "flat": s["flat"],
            "breadth_pct": round((s["advance"] - s["decline"]) / s["stock_count"] * 100, 1),
            "value_weighted_change_pct": round(s["weighted_change_sum"] / s["total_value"], 2),
            "total_value_billion": round(s["total_value"] / 1e8, 2),
        })
    results.sort(key=lambda r: r["value_weighted_change_pct"], reverse=True)
    return results


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


# ---------- 選股篩選：月線多頭 + 財務體質 ----------

_screener_cache = {}
_screener_lock = threading.Lock()


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


def fetch_monthly_revenue():
    """上市公司每月營業收入彙總表：產業別、月增率、年增率、累計年增率"""
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    data = fetch_json(url, ttl=3600)
    out = {}
    for row in data:
        code = row.get("公司代號", "")
        out[code] = {
            "industry": row.get("產業別") or "未分類",
            "revenue_month": safe_float(row.get("營業收入-當月營收")),
            "revenue_mom_pct": safe_float(row.get("營業收入-上月比較增減(%)")),
            "revenue_yoy_pct": safe_float(row.get("營業收入-去年同月增減(%)")),
            "revenue_cum_yoy_pct": safe_float(row.get("累計營業收入-前期比較增減(%)")),
        }
    return out


def fetch_eps():
    """上市公司綜合損益表（一般業）：最新一期基本每股盈餘。金融/證券/保險業不在此表，EPS 會缺漏"""
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
    data = fetch_json(url, ttl=3600)
    out = {}
    for row in data:
        code = row.get("公司代號", "")
        eps = safe_float(row.get("基本每股盈餘（元）"))
        if eps is None:
            continue
        out[code] = {
            "eps": eps,
            "eps_year": row.get("年度"),
            "eps_quarter": row.get("季別"),
        }
    return out


def fetch_valuation():
    """全上市股票每日本益比／殖利率／股價淨值比彙總表（單一請求抓全市場，
    不用逐檔查）。PEratio 空字串代表當期無法計算本益比（例如近四季虧損）。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
    data = fetch_json(url, ttl=3600)
    out = {}
    for row in data:
        code = row.get("Code", "")
        if not code:
            continue
        out[code] = {
            "pe_ratio": safe_float(row.get("PEratio")),
            "dividend_yield": safe_float(row.get("DividendYield")),
            "pb_ratio": safe_float(row.get("PBratio")),
        }
    return out


def fetch_disposition():
    """集中市場公布處置股票"""
    url = "https://openapi.twse.com.tw/v1/announcement/punish"
    data = fetch_json(url, ttl=1800)
    out = {}
    for row in data:
        code = row.get("Code", "")
        if not code:
            continue
        out[code] = {
            "name": row.get("Name", ""),
            "reason": row.get("ReasonsOfDisposition", ""),
            "period": row.get("DispositionPeriod", ""),
        }
    return out


def fetch_disposition_pullback_watch(level_threshold=5.0):
    """處置股回檔觀察：處置股裡，股價已經回檔到布林通道中線（位階5）以下的清單，
    給想接刀／搶反彈的人做參考觀察名單，不是進場建議。"""
    disposition_map = fetch_disposition()
    if not disposition_map:
        return []

    def check_one(code, info):
        rows = fetch_stock_daily_rows(code, months=3)
        boll = compute_bollinger_now(rows)
        if not boll or boll["level"] > level_threshold:
            return None
        return {
            "code": code,
            "name": info.get("name", ""),
            "close": boll["close"],
            "boll_upper": boll["upper"],
            "boll_middle": boll["middle"],
            "boll_lower": boll["lower"],
            "boll_level": boll["level"],
            "disposition_reason": info.get("reason", ""),
            "disposition_period": info.get("period", ""),
        }

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_one, code, info) for code, info in disposition_map.items()]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                results.append(r)
    results.sort(key=lambda r: r["boll_level"])
    return results


def fetch_attention():
    """集中市場當日公布注意股票"""
    url = "https://openapi.twse.com.tw/v1/announcement/notice"
    data = fetch_json(url, ttl=1800)
    out = set()
    for row in data:
        code = row.get("Code", "")
        if code:
            out.add(code)
    return out


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


def run_screener(pct_threshold=5.0, trend_days=10, long_term=False, min_trade_value=0):
    cache_key = (round(pct_threshold, 2), trend_days, bool(long_term), int(min_trade_value))
    with _screener_lock:
        hit = _screener_cache.get(cache_key)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]

    snapshot = fetch_market_snapshot()

    # 第一階段只用來「粗篩」縮小要抓歷史資料的股票數：證交所這支 API 給的
    # MonthlyAveragePrice 其實是「當月至今平均價」，月初時跟真正的月線（20日均線）
    # 可能差很多，所以這裡用寬鬆的門檻（threshold + 15%）先過濾，真正精準的
    # 乖離%／月線數值一律在第二階段用每檔個股的實際日收盤價重新計算 20 日均線。
    stage1_margin = pct_threshold + 15
    candidates = []
    for code, v in snapshot.items():
        rough_proximity = (v["close"] - v["monthly_avg"]) / v["monthly_avg"] * 100
        if abs(rough_proximity) <= stage1_margin:
            candidates.append((code, v, rough_proximity))
    candidates.sort(key=lambda x: abs(x[2]))
    candidates = candidates[:MAX_TREND_CANDIDATES]

    # 抓夠長的歷史，確保 20 日均線序列長度足以比對 trend_days 天前的月線
    history_months = max(3, -(-(20 + trend_days) // 20) + 1)

    def check_trend(item):
        code, v, _rough_proximity = item
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

        latest_close = closes[-1]
        ma20_now = ma20[-1]
        proximity_pct = (latest_close - ma20_now) / ma20_now * 100
        if abs(proximity_pct) > pct_threshold:
            return None
        trend_up = ma20[-1] > ma20[-1 - trend_days]
        slope_pct = (ma20[-1] - ma20[-1 - trend_days]) / ma20[-1 - trend_days] * 100
        if not trend_up:
            return None
        return {
            "code": code,
            "name": v["name"],
            "close": latest_close,
            "monthly_avg": round(ma20_now, 2),
            "proximity_pct": round(proximity_pct, 2),
            "ma20_slope_pct": round(slope_pct, 2),
            "chip_bias_5": compute_volume_bias(rows, 5),
            "chip_bias_20": compute_volume_bias(rows, 20),
            "avg_trade_value_wan": round(avg_trade_value / 10000),
        }

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_trend, item) for item in candidates]
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

        # 綜合評分：純粹統計「符合你設定的多頭＋體質＋籌碼條件」的程度，不是預測、不是買進訊號
        score = 0
        if r["revenue_mom_pct"] is not None and r["revenue_mom_pct"] > 0:
            score += 1
        if r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] > 0:
            score += 1
        if r["revenue_cum_yoy_pct"] is not None and r["revenue_cum_yoy_pct"] > 0:
            score += 1
        if r["eps"] is not None and r["eps"] > 0:
            score += 1
        if r["ma20_slope_pct"] > 3:
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
        if r["is_disposition"] or r["is_attention"]:
            score -= 3  # 有處置/注意公告的不列入「較符合條件」，但仍保留在清單中讓你自己判斷
        # 「出貨」風險粗略警示：均線仍在漲、但近20日籌碼傾向偏空且大戶人數減少 → 價量／籌碼背離
        r["distribution_risk"] = bool(
            r["chip_bias_20"] is not None and r["chip_bias_20"] < -10
            and r["holders_reliable"] and r["holders_1000_change"] is not None and r["holders_1000_change"] < 0
        )
        if r["distribution_risk"]:
            score -= 2
        r["fit_score"] = score
        # 進場參考價＝月線本身（技術面常見的拉回支撐參考，不是預測明天價格）
        r["entry_ref_price"] = r["monthly_avg"]

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

    results.sort(key=lambda r: (-r["fit_score"], abs(r["proximity_pct"])))

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pct_threshold": pct_threshold,
        "trend_days": trend_days,
        "min_trade_value": min_trade_value,
        "long_term": bool(long_term),
        "candidates_scanned": len(candidates),
        "results": results,
    }
    with _screener_lock:
        _screener_cache[cache_key] = (time.time(), payload)
    return payload


# ---------- 選股篩選：空頭轉弱 + 放空篩選 ----------

_short_screener_cache = {}
_short_screener_lock = threading.Lock()


def fetch_margin_data():
    """全市場當日融資融券餘額（一次請求）。放空篩選只需要融券相關欄位：
    融券限額（沒有值或是 0，代表這檔股票根本不能用融券放空）、融券今日餘額
    （目前已經被放空的張數）。額度使用率（餘額／限額）越高，代表能加碼放空的
    空間越小，市場上已經有很多人卡位放空、軋空風險也可能較高。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    data = fetch_json(url, ttl=1800)
    out = {}
    for row in data:
        code = row.get("股票代號", "")
        if not code:
            continue
        limit = safe_float(row.get("融券限額"))
        balance = safe_float(row.get("融券今日餘額"))
        out[code] = {
            "margin_short_limit": limit,
            "margin_short_balance": balance,
            "margin_short_usage_pct": (
                round(balance / limit * 100, 1) if limit and limit > 0 and balance is not None else None
            ),
        }
    return out


def run_short_screener(pct_threshold=5.0, trend_days=7, min_trade_value=0):
    """跟 run_screener 結構完全對稱，但條件全部反過來找空頭轉弱的股票：
    月線走勢向下、營收/EPS/籌碼轉弱、大戶減碼——用來抓 5~10 個交易日左右的短線放空
    切入點參考，不是預測、不是保證獲利。額外用融資融券餘額表過濾掉沒辦法用
    融券放空的股票，並對融券額度快用完的標的扣分示警（軋空風險）。"""
    cache_key = (round(pct_threshold, 2), trend_days, int(min_trade_value))
    with _short_screener_lock:
        hit = _short_screener_cache.get(cache_key)
        if hit and time.time() - hit[0] < 1800:
            return hit[1]

    snapshot = fetch_market_snapshot()
    stage1_margin = pct_threshold + 15
    candidates = []
    for code, v in snapshot.items():
        rough_proximity = (v["close"] - v["monthly_avg"]) / v["monthly_avg"] * 100
        if abs(rough_proximity) <= stage1_margin:
            candidates.append((code, v, rough_proximity))
    candidates.sort(key=lambda x: abs(x[2]))
    candidates = candidates[:MAX_TREND_CANDIDATES]

    history_months = max(3, -(-(20 + trend_days) // 20) + 1)

    def check_trend(item):
        code, v, _rough_proximity = item
        rows = fetch_stock_daily_rows(code, months=history_months)
        closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
        ma20 = compute_ma20_series(rows)
        if len(ma20) <= trend_days or not closes:
            return None

        recent_values = [safe_float(r[2]) for r in rows[-20:] if safe_float(r[2]) is not None]
        avg_trade_value = sum(recent_values) / len(recent_values) if recent_values else 0
        if min_trade_value > 0 and avg_trade_value < min_trade_value:
            return None

        latest_close = closes[-1]
        ma20_now = ma20[-1]
        proximity_pct = (latest_close - ma20_now) / ma20_now * 100
        if abs(proximity_pct) > pct_threshold:
            return None
        trend_down = ma20[-1] < ma20[-1 - trend_days]
        slope_pct = (ma20[-1] - ma20[-1 - trend_days]) / ma20[-1 - trend_days] * 100
        if not trend_down:
            return None
        return {
            "code": code,
            "name": v["name"],
            "close": latest_close,
            "monthly_avg": round(ma20_now, 2),
            "proximity_pct": round(proximity_pct, 2),
            "ma20_slope_pct": round(slope_pct, 2),
            "chip_bias_5": compute_volume_bias(rows, 5),
            "chip_bias_20": compute_volume_bias(rows, 20),
            "avg_trade_value_wan": round(avg_trade_value / 10000),
        }

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(check_trend, item) for item in candidates]
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

    # 融券限額不存在或為 0：這檔股票根本不能用融券放空，直接排除，不然清單沒有意義
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
        r["pb_ratio"] = val.get("pb_ratio")

        holder = holder_map.get(code, {})
        r["holders_1000"] = holder.get("holders_1000")
        r["holders_1000_change"] = holder.get("holders_1000_change")
        r["holders_report_date"] = holder.get("report_date")
        r["holders_reliable"] = r["holders_1000"] is not None and r["holders_1000"] >= MIN_RELIABLE_HOLDERS

        # 籌碼背離警示（放空版）：近20日籌碼明顯偏空、但營收年增卻明顯成長，
        # 代表賣壓可能只是短線超跌、不是基本面真的在惡化，追空風險較高
        r["chip_revenue_divergence"] = bool(
            r["chip_bias_20"] is not None and r["chip_bias_20"] < -20
            and r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] > 10
        )

        # 綜合評分：純粹統計「符合你設定的空頭＋體質轉弱＋籌碼條件」的程度，不是預測、不是放空訊號
        score = 0
        if r["revenue_mom_pct"] is not None and r["revenue_mom_pct"] < 0:
            score += 1
        if r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] < 0:
            score += 1
        if r["revenue_cum_yoy_pct"] is not None and r["revenue_cum_yoy_pct"] < 0:
            score += 1
        if r["eps"] is not None and r["eps"] < 0:
            score += 1
        if r["ma20_slope_pct"] < -3:
            score += 1
        # 本益比（放空版）：估值偏貴或近四季虧損都算是支持放空論點；已經跌到便宜估值代表下檔有限，扣分
        r["pe_high"] = r["pe_ratio"] is not None and r["pe_ratio"] > 40
        r["pe_missing"] = r["pe_ratio"] is None
        if r["pe_high"] or r["pe_missing"]:
            score += 1
        elif r["pe_ratio"] is not None and 0 < r["pe_ratio"] <= 20:
            score -= 1
        if r["chip_revenue_divergence"]:
            score -= 2
        elif r["chip_bias_20"] is not None and r["chip_bias_20"] < 0:
            score += 1
        if r["holders_reliable"] and r["holders_1000_change"] is not None and r["holders_1000_change"] < 0:
            score += 1
        if r["is_disposition"] or r["is_attention"]:
            score -= 3  # 處置/注意股波動大、成交限制多，放空進出場風險高，不列入「較符合條件」
        # 「軋空」風險粗略警示：均線仍在跌，但近20日籌碼傾向偏多且大戶人數增加 → 可能有人低接、醞釀反彈
        r["squeeze_risk"] = bool(
            r["chip_bias_20"] is not None and r["chip_bias_20"] > 10
            and r["holders_reliable"] and r["holders_1000_change"] is not None and r["holders_1000_change"] > 0
        )
        if r["squeeze_risk"]:
            score -= 2
        # 融券額度用得越滿，能加碼放空的空間越小，市場上已經很多人卡位放空，軋空風險也較高
        r["margin_crowded"] = r["margin_short_usage_pct"] is not None and r["margin_short_usage_pct"] >= 80
        if r["margin_crowded"]:
            score -= 2
        r["fit_score"] = score
        # 參考價＝月線本身（技術面常見的反彈壓力參考，不是預測明天價格）
        r["entry_ref_price"] = r["monthly_avg"]

    results.sort(key=lambda r: (-r["fit_score"], abs(r["proximity_pct"])))

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pct_threshold": pct_threshold,
        "trend_days": trend_days,
        "min_trade_value": min_trade_value,
        "candidates_scanned": len(candidates),
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 安靜一點，不要洗控制台

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        # 開發中頻繁改動 app.js/index.html，避免瀏覽器快取舊版造成「明明改了還是舊行為」
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if parsed.path == "/" or parsed.path == "/index.html":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/app.js":
                self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
                return

            if parsed.path == "/api/quote":
                codes = qs.get("codes", [""])[0]
                codes = [c.strip() for c in codes.split(",") if c.strip()]
                if not codes:
                    self._send_json({"error": "missing codes"}, 400)
                    return
                # 同時嘗試上市(tse)與上櫃(otc)，證交所 MIS 會忽略查不到的代碼
                ex_list = []
                for c in codes:
                    ex_list.append(f"tse_{c}.tw")
                    ex_list.append(f"otc_{c}.tw")
                url = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch="
                       + urllib.parse.quote("|".join(ex_list)) + "&json=1&delay=0")
                raw = fetch_json(url, ttl=5)
                quotes = parse_mis_quote(raw)
                # 每檔代碼只留第一筆有效資料（tse 優先）
                merged = {}
                for q in quotes:
                    if q["code"] not in merged or (merged[q["code"]]["price"] is None and q["price"] is not None):
                        merged[q["code"]] = q
                self._send_json({"quotes": [merged[c] for c in codes if c in merged]})
                return

            if parsed.path == "/api/health":
                self._send_json({"ok": check_backend_health(), "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")})
                return

            if parsed.path == "/api/indices":
                self._send_json(fetch_indices())
                return

            if parsed.path == "/api/index_history":
                key = qs.get("key", [""])[0].strip()
                months = int(qs.get("months", ["3"])[0])
                display_name, rows = fetch_index_daily_rows(key, months=months)
                if display_name is None:
                    self._send_json({"error": "unknown index key"}, 400)
                    return
                self._send_json({"key": key, "name": display_name, "rows": rows})
                return

            if parsed.path == "/api/day_all":
                url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
                data = fetch_json(url, ttl=300)
                self._send_json({"data": data})
                return

            if parsed.path == "/api/stock_directory":
                self._send_json({"data": fetch_stock_directory()})
                return

            if parsed.path == "/api/history":
                code = qs.get("code", [""])[0].strip()
                months = int(qs.get("months", ["3"])[0])
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                rows = fetch_stock_daily_rows_for_chart(code, months=months)
                self._send_json({"code": code, "rows": rows})
                return

            if parsed.path == "/api/intraday":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                data = fetch_intraday(code)
                if data is None:
                    self._send_json({"code": code, "points": [], "error": "not found"})
                    return
                self._send_json({"code": code, **data})
                return

            if parsed.path == "/api/intraday_pattern":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                data = fetch_intraday_pattern(code)
                if data is None:
                    self._send_json({"code": code, "error": "not found"}, 404)
                    return
                self._send_json({"code": code, **data})
                return

            if parsed.path == "/api/screener":
                pct = float(qs.get("pct", ["5"])[0])
                trend_days = int(qs.get("trend_days", ["10"])[0])
                long_term = qs.get("long_term", ["0"])[0] == "1"
                min_trade_value_wan = float(qs.get("min_trade_value_wan", ["3000"])[0])
                payload = run_screener(
                    pct_threshold=pct, trend_days=trend_days, long_term=long_term,
                    min_trade_value=min_trade_value_wan * 10000,
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/short_screener":
                pct = float(qs.get("pct", ["5"])[0])
                trend_days = int(qs.get("trend_days", ["7"])[0])
                min_trade_value_wan = float(qs.get("min_trade_value_wan", ["3000"])[0])
                payload = run_short_screener(
                    pct_threshold=pct, trend_days=trend_days,
                    min_trade_value=min_trade_value_wan * 10000,
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/reversal_short_screener":
                near_high_pct = float(qs.get("near_high_pct", ["3"])[0])
                min_shadow_ratio = float(qs.get("min_shadow_ratio", ["1"])[0])
                min_trade_value_wan = float(qs.get("min_trade_value_wan", ["3000"])[0])
                payload = run_reversal_short_screener(
                    near_high_pct=near_high_pct, min_shadow_ratio=min_shadow_ratio,
                    min_trade_value=min_trade_value_wan * 10000,
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/sector_flow":
                self._send_json({"data": fetch_sector_flow(), "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
                return

            if parsed.path == "/api/holders":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                holders = get_holder_data().get(code)
                if holders is None:
                    self._send_json({"code": code, "error": "not found"})
                    return
                self._send_json({"code": code, **holders})
                return

            if parsed.path == "/api/disposition":
                disp = fetch_disposition()
                rows = [{"code": c, **v} for c, v in disp.items()]
                self._send_json({"data": rows})
                return

            if parsed.path == "/api/disposition_watch":
                self._send_json({
                    "data": fetch_disposition_pullback_watch(),
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                return

            if parsed.path == "/api/attention":
                att = fetch_attention()
                self._send_json({"data": sorted(att)})
                return

            self._send_json({"error": "not found"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"啟動失敗：連接埠 {PORT} 已被佔用（可能已經有一個伺服器在跑了）。")
        print(f"請直接開啟瀏覽器連到 http://localhost:{PORT} ，或關閉舊的視窗後再試一次。")
        input("按 Enter 鍵關閉視窗...")
        return
    url = f"http://localhost:{PORT}"
    print(f"台股分析工具已啟動: {url}")
    print("按 Ctrl+C 停止伺服器（關閉這個視窗也會停止）")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
