"""
個股籌碼：三大法人（外資／投信／自營商）買賣超歷史、融資融券餘額，
以及「股價 vs 籌碼」是否背離的判斷。

資料來源說明：
- 三大法人買賣超（T86）不在證交所正式 OpenAPI（openapi.twse.com.tw）的目錄裡，
  是證交所網站本身在用的舊式 JSON 端點（www.twse.com.tw/rwd/...），沒有官方文件，
  但格式穩定、很多台股工具都是這樣抓，跟這支程式已經在用的 MIS 即時報價端點
  屬於同一類（都是「證交所自己網站在用、但沒收進 OpenAPI 目錄」的端點）。
- 券商分點進出（分點籌碼）證交所沒有提供公開 JSON API，只有一個需要逐次網頁查詢、
  沒有穩定資料格式的舊系統（bsr.twse.com.tw），這支程式故意不去抓它——
  同一個 session 稍早想抓工商時報官網新聞就被反爬蟲擋掉（403），改走比較穩的
  Google 新聞 RSS；分點資料同理，與其做一個容易忽然失效的爬蟲，不如老實不做。
  三大法人（外資/投信/自營商）買賣超是市場上最主流、也最穩定可靠的籌碼指標，
  已經能涵蓋「主力/外資買賣超」這個需求的核心。
"""
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from app_core import BASE_DIR, atomic_write_json, fetch_json, safe_float
from market_data import fetch_stock_daily_rows_for_chart

INSTITUTIONAL_TTL = 3600 * 12  # 過去交易日的資料不會再變，長快取沒關係
MARGIN_TTL = 1800


def _fetch_json_with_retry(url, ttl, retries=3, backoff=1.2):
    """證交所/櫃買中心的舊式端點在短時間內被平行打好幾個請求時，偶爾會被前面的
    CDN 短暫限流（回傳 307 轉址、甚至 428，不是真的「這天沒有資料」，過一下通常
    會恢復），單次失敗就直接當作「這天沒有資料」會誤刪掉其實存在的交易日。
    重試幾次、每次間隔拉長一點，避免把限流誤判成假日。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fetch_json(url, ttl=ttl)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last_err


# 逐日歷史查詢本身很慢（每個交易日是一次全市場請求），所以額外做兩層加速，
# 三大法人買賣超、融資融券每日增減兩種歷史都共用同一套機制：
# (1) 同一批要查的交易日一次平行發出去，不要逐日循序等；
# (2) 查過的「某天、某檔股票」的結果存成一個很小的本機檔案，重開伺服器也不用重查
#     ——這裡刻意只存「使用者實際查過的股票」那一列，不是整天全市場好幾千檔都存起來，
#     檔案才不會越養越大。
INSTITUTIONAL_SNAPSHOT_FILE = BASE_DIR / "institutional_snapshots.json"
MARGIN_SNAPSHOT_FILE = BASE_DIR / "margin_history_snapshots.json"
_snapshot_lock = threading.Lock()


def _load_snapshot_file(path):
    with _snapshot_lock:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (json.JSONDecodeError, OSError):
            return {}


def _save_snapshot_file(path, snapshots):
    with _snapshot_lock:
        atomic_write_json(path, snapshots)


def _fetch_institutional_day_full(date_str):
    """單一交易日、全市場三大法人買賣超（T86），回傳 dict: code -> {...}。
    遇到假日或還沒公佈（當天盤後才會更新）時，證交所會回傳 stat != "OK"，
    這種情況視為「這天沒有資料」，回傳 None 讓呼叫端跳過這天。"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALL"
    try:
        data = _fetch_json_with_retry(url, INSTITUTIONAL_TTL)
    except Exception:
        return None
    if data.get("stat") != "OK":
        return None
    out = {}
    for row in data.get("data", []):
        if len(row) < 19:
            continue
        code = row[0].strip()
        out[code] = {
            "foreign_net": safe_float(row[4]),      # 外資及陸資買賣超（不含外資自營商）——一般俗稱的「外資買賣超」
            "foreign_dealer_net": safe_float(row[7]),  # 外資自營商買賣超（金額通常很小，多數股票是0）
            "trust_net": safe_float(row[10]),         # 投信買賣超
            "dealer_net": safe_float(row[11]),        # 自營商買賣超合計（自行買賣+避險）
            "total_net": safe_float(row[18]),         # 三大法人合計買賣超
        }
    return out


def _fetch_institutional_day_full_tpex(date_str):
    """單一交易日、全市場三大法人買賣超，上櫃（TPEx）版本——T86 只有上市（TWSE）股票，
    上櫃股票（例如信昌電 6173）要改查櫃買中心自己的等價端點，欄位順序跟 T86 不一樣。"""
    date_param = urllib.parse.quote(f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}")
    url = f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={date_param}&id=&response=json"
    try:
        data = _fetch_json_with_retry(url, INSTITUTIONAL_TTL)
    except Exception:
        return None
    tables = data.get("tables") or []
    if not tables:
        return None
    rows = tables[0].get("data") or []
    out = {}
    for row in rows:
        if len(row) < 24:
            continue
        code = row[0].strip()
        out[code] = {
            "foreign_net": safe_float(row[10]),      # 外資合計（含外資自營商）買賣超
            "foreign_dealer_net": safe_float(row[7]),  # 外資自營商買賣超
            "trust_net": safe_float(row[13]),         # 投信買賣超
            "dealer_net": safe_float(row[22]),        # 自營商買賣超合計（自行買賣+避險）
            "total_net": safe_float(row[23]),         # 三大法人合計買賣超
        }
    return out


def _recent_weekdays(n):
    """由新到舊，最近 n 個非週六日的西元日期字串（YYYYMMDD）——不含國定假日判斷，
    假日的部分會在抓資料時自然被證交所回傳的 stat != "OK" 濾掉，呼叫端再多抓幾天補上。"""
    out = []
    d = datetime.now()
    while len(out) < n:
        if d.weekday() < 5:  # 0=一 ... 4=五
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _fetch_batch(batch, fetch_fn, code):
    """平行抓一批交易日的全市場資料，只留下 code 這一檔股票的那一列。
    worker 數字特意壓低（不是像其他篇幅較短的批次那樣開到 6-8）：實測發現一次
    開太多平行請求會被證交所/櫃買中心的 CDN 短暫限流（甚至擋到明明前一刻才成功
    過的日期也跟著失敗），與其抓比較快但常常抓不齊，寧可稍微慢一點但抓得穩。"""
    hits = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_fn, d): d for d in batch}
        for fut in as_completed(futures):
            date_str = futures[fut]
            try:
                day_data = fut.result()
            except Exception:
                day_data = None
            if day_data and code in day_data:
                hits[date_str] = day_data[code]
    return hits


def _fetch_stock_day_history(code, snapshot_file, fetch_twse_fn, fetch_tpex_fn, days, max_calendar_days):
    """通用的「某檔股票最近 N 個交易日、逐日全市場資料」抓取邏輯（依日期由舊到新排序），
    三大法人買賣超歷史、融資融券每日增減歷史都是套這一套：
    先查本機小型快取檔（之前查過的股票、日期不用再打 API），缺的部分才平行發請求
    （一次一批，而不是逐日循序等，是主要的加速來源）；平常只會缺國定假日造成的落差，
    用一個小緩衝值一次補齊，極端情況才需要多補一輪。
    上市（TWSE）跟上櫃（TPEx）是兩個不同的資料來源、欄位也不一樣，這裡先猜上市
    （比較多股票在那邊），第一批完全撲空的話（例如信昌電 6173 這種上櫃股）就整批
    改查上櫃重試一次，之後確定是哪邊就固定用那邊，不用每批都兩邊猜。"""
    snapshots = _load_snapshot_file(snapshot_file)
    candidate_dates = _recent_weekdays(max_calendar_days)

    results = {}
    remaining = []
    for date_str in candidate_dates:
        cached = snapshots.get(date_str, {}).get(code)
        if cached is not None:
            results[date_str] = cached
        else:
            remaining.append(date_str)

    newly_fetched = {}
    fetch_fn = fetch_twse_fn  # 先猜上市（TWSE）
    market_confirmed = False
    idx = 0
    while len(results) < days and idx < len(remaining):
        batch_size = max(days - len(results), 0) + 7  # +7 蓋掉一般連假長度，通常一輪就夠
        batch = remaining[idx:idx + batch_size]
        idx += batch_size
        hits = _fetch_batch(batch, fetch_fn, code)
        if not hits and not market_confirmed:
            fetch_fn = fetch_tpex_fn
            hits = _fetch_batch(batch, fetch_fn, code)
        if hits:
            market_confirmed = True
            results.update(hits)
            newly_fetched.update(hits)

    if newly_fetched:
        snapshots = _load_snapshot_file(snapshot_file)  # 重新讀一次，避免蓋掉同時間查別檔股票寫入的結果
        for date_str, row in newly_fetched.items():
            snapshots.setdefault(date_str, {})[code] = row
        _save_snapshot_file(snapshot_file, snapshots)

    ordered_dates = sorted(results.keys())[-days:]
    return [{"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **results[d]} for d in ordered_dates]


def fetch_stock_institutional_history(code, days=20, max_calendar_days=None):
    """回傳指定股票最近 N 個交易日的三大法人買賣超歷史（依日期由舊到新排序）。"""
    return _fetch_stock_day_history(
        code, INSTITUTIONAL_SNAPSHOT_FILE,
        _fetch_institutional_day_full, _fetch_institutional_day_full_tpex,
        days, max_calendar_days or max(90, days * 2),
    )


def _fetch_margin_detail_twse(code):
    """融資融券完整資料，上市（TWSE）版本。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    data = _fetch_json_with_retry(url, MARGIN_TTL)
    for row in data:
        if row.get("股票代號") == code:
            margin_limit = safe_float(row.get("融資限額"))
            margin_balance = safe_float(row.get("融資今日餘額"))
            short_limit = safe_float(row.get("融券限額"))
            short_balance = safe_float(row.get("融券今日餘額"))
            return {
                "margin_buy": safe_float(row.get("融資買進")),
                "margin_sell": safe_float(row.get("融資賣出")),
                "margin_balance": margin_balance,
                "margin_prev_balance": safe_float(row.get("融資前日餘額")),
                "margin_limit": margin_limit,
                "margin_usage_pct": (
                    round(margin_balance / margin_limit * 100, 1)
                    if margin_limit and margin_limit > 0 and margin_balance is not None else None
                ),
                "short_buy": safe_float(row.get("融券賣出")),  # 融券的「賣」是放空建倉，欄位語意本來就跟融資相反
                "short_balance": short_balance,
                "short_prev_balance": safe_float(row.get("融券前日餘額")),
                "short_limit": short_limit,
                "short_usage_pct": (
                    round(short_balance / short_limit * 100, 1)
                    if short_limit and short_limit > 0 and short_balance is not None else None
                ),
            }
    return None


def _fetch_margin_detail_tpex(code):
    """融資融券完整資料，上櫃（TPEx）版本——欄位名稱、單位（都是張）都跟 TWSE 不同，
    不帶 date 參數時櫃買中心會自動回傳最新一個交易日的資料，跟 TWSE 那支端點行為一致。"""
    url = "https://www.tpex.org.tw/www/zh-tw/margin/balance?type=Daily&id=&response=json"
    try:
        data = _fetch_json_with_retry(url, MARGIN_TTL)
    except Exception:
        return None
    tables = data.get("tables") or []
    if not tables:
        return None
    for row in tables[0].get("data") or []:
        if len(row) < 18 or row[0].strip() != code:
            continue
        margin_limit = safe_float(row[9])
        margin_balance = safe_float(row[6])
        short_limit = safe_float(row[17])
        short_balance = safe_float(row[14])
        return {
            "margin_buy": safe_float(row[3]),
            "margin_sell": safe_float(row[4]),
            "margin_balance": margin_balance,
            "margin_prev_balance": safe_float(row[2]),
            "margin_limit": margin_limit,
            "margin_usage_pct": (
                round(margin_balance / margin_limit * 100, 1)
                if margin_limit and margin_limit > 0 and margin_balance is not None else None
            ),
            "short_buy": safe_float(row[11]),
            "short_balance": short_balance,
            "short_prev_balance": safe_float(row[10]),
            "short_limit": short_limit,
            "short_usage_pct": (
                round(short_balance / short_limit * 100, 1)
                if short_limit and short_limit > 0 and short_balance is not None else None
            ),
        }
    return None


def fetch_margin_detail(code):
    """單一股票的融資融券完整資料（買進/賣出/今日餘額/限額，融資融券都有）。
    跟 disposition.py 的 fetch_margin_data 不同——那支只留放空篩選要用的融券欄位，
    這裡是給籌碼分析看的完整版本。先查上市，查不到再查上櫃（信昌電這類股票）。"""
    return _fetch_margin_detail_twse(code) or _fetch_margin_detail_tpex(code)


def _fetch_margin_day_full_twse(date_str):
    """單一交易日、全市場融資融券餘額，上市（TWSE）版本——跟 fetch_margin_detail 用的
    openapi.twse.com.tw 端點不同，那支不支援查歷史日期（帶 date 參數也永遠回傳最新一天），
    這裡改用證交所網站自己在用的舊式端點，才能像 T86 一樣逐日查到過去的資料。"""
    url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={date_str}&selectType=ALL&response=json"
    try:
        data = _fetch_json_with_retry(url, INSTITUTIONAL_TTL)
    except Exception:
        return None
    if data.get("stat") != "OK":
        return None
    tables = data.get("tables") or []
    if len(tables) < 2:
        return None
    out = {}
    for row in tables[1].get("data") or []:
        if len(row) < 14:
            continue
        code = row[0].strip()
        margin_balance = safe_float(row[6])
        margin_prev_balance = safe_float(row[5])
        short_balance = safe_float(row[12])
        short_prev_balance = safe_float(row[11])
        out[code] = {
            "margin_buy": safe_float(row[2]),
            "margin_sell": safe_float(row[3]),
            "margin_balance": margin_balance,
            "margin_change": (
                margin_balance - margin_prev_balance if margin_balance is not None and margin_prev_balance is not None else None
            ),
            "short_open": safe_float(row[9]),    # 融券賣出＝放空建倉
            "short_cover": safe_float(row[8]),   # 融券買進＝回補平倉
            "short_balance": short_balance,
            "short_change": (
                short_balance - short_prev_balance if short_balance is not None and short_prev_balance is not None else None
            ),
        }
    return out


def _fetch_margin_day_full_tpex(date_str):
    """單一交易日、全市場融資融券餘額，上櫃（TPEx）版本，欄位順序跟 TWSE 不同。"""
    date_param = urllib.parse.quote(f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}")
    url = f"https://www.tpex.org.tw/www/zh-tw/margin/balance?type=Daily&date={date_param}&id=&response=json"
    try:
        data = _fetch_json_with_retry(url, INSTITUTIONAL_TTL)
    except Exception:
        return None
    tables = data.get("tables") or []
    if not tables:
        return None
    out = {}
    for row in tables[0].get("data") or []:
        if len(row) < 18:
            continue
        code = row[0].strip()
        margin_balance = safe_float(row[6])
        margin_prev_balance = safe_float(row[2])
        short_balance = safe_float(row[14])
        short_prev_balance = safe_float(row[10])
        out[code] = {
            "margin_buy": safe_float(row[3]),
            "margin_sell": safe_float(row[4]),
            "margin_balance": margin_balance,
            "margin_change": (
                margin_balance - margin_prev_balance if margin_balance is not None and margin_prev_balance is not None else None
            ),
            "short_open": safe_float(row[11]),   # 券賣＝放空建倉
            "short_cover": safe_float(row[12]),  # 券買＝回補平倉
            "short_balance": short_balance,
            "short_change": (
                short_balance - short_prev_balance if short_balance is not None and short_prev_balance is not None else None
            ),
        }
    return out


def fetch_stock_margin_history(code, days=20, max_calendar_days=None):
    """回傳指定股票最近 N 個交易日的融資融券餘額每日增減歷史（依日期由舊到新排序）。"""
    return _fetch_stock_day_history(
        code, MARGIN_SNAPSHOT_FILE,
        _fetch_margin_day_full_twse, _fetch_margin_day_full_tpex,
        days, max_calendar_days or max(90, days * 2),
    )


def fetch_stock_institutional_and_margin_history(code, days=20):
    """三大法人歷史、融資融券每日增減歷史，兩組互不相關的逐日查詢平行一起做，
    不要一個做完才做下一個——這兩個是 /api/chips 裡最花時間的兩塊。"""
    with ThreadPoolExecutor(max_workers=2) as pool:
        institutional_future = pool.submit(fetch_stock_institutional_history, code, days=days)
        margin_future = pool.submit(fetch_stock_margin_history, code, days=days)
        return institutional_future.result(), margin_future.result()


# 股價／籌碼要變動多少才算「有方向性」，這兩個門檻是以 10 個交易日為校準基準——
# 觀察期拉長或縮短時，正常的價格波動、籌碼累積量本來就會跟著變大/變小，門檻如果
# 固定不變，長天期幾乎永遠會觸發（隨便都超過2%），短天期又幾乎永遠不會觸發，
# 所以改用時間開根號去縮放（波動度大致跟時間開根號成正比的粗略經驗法則），
# 讓「背離」在短線、長線視角下都還算是一個有意義的門檻，不會變得太鬆或太緊。
DIVERGENCE_PRICE_THRESHOLD_PCT_BASE = 2.0   # 10 個交易日的股價變動門檻%
DIVERGENCE_CHIP_THRESHOLD_PCT_BASE = 3.0    # 10 個交易日的籌碼佔量比門檻%
DIVERGENCE_CALIBRATION_DAYS = 10


def _divergence_thresholds(days):
    scale = (days / DIVERGENCE_CALIBRATION_DAYS) ** 0.5
    return DIVERGENCE_PRICE_THRESHOLD_PCT_BASE * scale, DIVERGENCE_CHIP_THRESHOLD_PCT_BASE * scale


def analyze_chip_divergence(code, days=10, history=None):
    """判斷「股價」跟「三大法人籌碼」這段期間走的方向是否一致（背離判斷）：
    - 股價漲、法人卻賣超 → 價漲籌碼背離（俗稱「價漲量縮/出貨嫌疑」的籌碼版）
    - 股價跌、法人卻買超 → 價跌籌碼背離（可能是逢低承接，非保證止跌訊號）
    - 兩者同方向 → 價籌同步
    - 任一方變化不夠明顯 → 無明顯背離（觀察期太短或盤整）
    這是對已發生資料的客觀統計比對，不是預測，也不是買賣訊號。
    days 可以自由調整（短線抓 5-10 天，長線抓 40-60 天都可以），判斷門檻會跟著
    觀察期天數自動縮放，不會因為抓比較長的天數就變得隨便都觸發背離。
    history 可選：呼叫端如果已經抓過同一檔股票的三大法人歷史，直接傳進來避免重抓；
    不傳的話這裡會自己抓最近 days 個交易日的資料。"""
    if history is None:
        history = fetch_stock_institutional_history(code, days=days)
    else:
        history = history[-days:]
    if len(history) < 3:
        return {"error": "三大法人歷史資料不足（可能是新股，或最近交易日資料還沒公佈）"}

    # 抓夠長的股價歷史才能對得上最舊的那個交易日：一個月大約21個交易日，多留一點緩衝
    price_months = max(2, days // 18 + 2)
    price_rows = fetch_stock_daily_rows_for_chart(code, months=price_months)
    closes_by_date = {}
    volumes_by_date = {}
    for r in price_rows:
        # r[0] 是民國年日期 "115/09/18"，這裡轉成跟三大法人資料一致的西元 "2026-09-18"
        m = re.match(r"^(\d+)/(\d{2})/(\d{2})$", r[0] or "")
        if not m:
            continue
        y, mo, da = int(m.group(1)) + 1911, m.group(2), m.group(3)
        date_key = f"{y}-{mo}-{da}"
        close = safe_float(r[6])
        if close is not None:
            closes_by_date[date_key] = close
        volume = safe_float(r[1])
        if volume is not None:
            volumes_by_date[date_key] = volume

    first_date, last_date = history[0]["date"], history[-1]["date"]
    close_start = closes_by_date.get(first_date)
    close_end = closes_by_date.get(last_date)
    if close_start is None or close_end is None or close_start <= 0:
        return {"error": "股價資料跟三大法人資料的交易日對不起來，暫時無法比對"}

    price_change_pct = round((close_end - close_start) / close_start * 100, 2)

    total_net_shares = sum(h["total_net"] for h in history if h["total_net"] is not None)
    foreign_net_shares = sum(h["foreign_net"] for h in history if h["foreign_net"] is not None)
    trust_net_shares = sum(h["trust_net"] for h in history if h["trust_net"] is not None)
    dealer_net_shares = sum(h["dealer_net"] for h in history if h["dealer_net"] is not None)

    period_volume_shares = sum(volumes_by_date.get(h["date"], 0) for h in history)
    chip_bias_pct = round(total_net_shares / period_volume_shares * 100, 2) if period_volume_shares else 0.0

    price_threshold_pct, chip_threshold_pct = _divergence_thresholds(len(history))
    price_up = price_change_pct >= price_threshold_pct
    price_down = price_change_pct <= -price_threshold_pct
    chip_in = chip_bias_pct >= chip_threshold_pct
    chip_out = chip_bias_pct <= -chip_threshold_pct

    if price_up and chip_out:
        verdict, label = "bearish_divergence", "價漲籌碼背離：股價上漲，但三大法人這段期間是淨賣超"
    elif price_down and chip_in:
        verdict, label = "bullish_divergence", "價跌籌碼背離：股價下跌，但三大法人這段期間是淨買超"
    elif (price_up and chip_in) or (price_down and chip_out):
        verdict, label = "aligned", "價籌同步：股價方向跟三大法人買賣超方向一致，沒有背離"
    else:
        verdict, label = "neutral", "無明顯背離：股價或籌碼變化幅度不夠明顯，暫時看不出方向性"

    return {
        "code": code,
        "days": len(history),
        "period_from": first_date,
        "period_to": last_date,
        "price_change_pct": price_change_pct,
        "total_net_lots": round(total_net_shares / 1000),
        "foreign_net_lots": round(foreign_net_shares / 1000),
        "trust_net_lots": round(trust_net_shares / 1000),
        "dealer_net_lots": round(dealer_net_shares / 1000),
        "chip_bias_pct": chip_bias_pct,
        "price_threshold_pct": round(price_threshold_pct, 2),
        "chip_threshold_pct": round(chip_threshold_pct, 2),
        "verdict": verdict,
        "verdict_label": label,
    }
