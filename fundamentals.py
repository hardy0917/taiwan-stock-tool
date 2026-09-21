"""
個股基本面分析：月營收、單季EPS、本益比／殖利率／股價淨值比、本益比河流圖
（合理價格帶）、重大訊息公告。
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app_core import fetch_json, safe_float
from market_data import fetch_stock_daily_rows_for_chart


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


def fetch_stock_pe_month(code, year_month):
    """抓單一股票、單一月份的每日本益比／殖利率／股價淨值比（只支援上市，上櫃無此資料源）。
    year_month 是西元 "YYYYMM"。"""
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU?stockNo={code}&date={year_month}01&response=json"
    try:
        data = fetch_json(url, ttl=86400)
    except Exception:
        return []
    if data.get("stat") != "OK":
        return []
    rows = []
    for row in data.get("data", []):
        # 日期格式 "115年09月01日" -> "115/09/01"，跟其他地方的日期格式一致
        date_raw = row[0]
        roc_date = date_raw.replace("年", "/").replace("月", "/").replace("日", "")
        pe = safe_float(row[3])
        pb = safe_float(row[4])
        dividend_yield = safe_float(row[1])
        rows.append({"date": roc_date, "pe_ratio": pe, "pb_ratio": pb, "dividend_yield": dividend_yield})
    return rows


def fetch_stock_pe_history(code, months=24):
    """抓過去 N 個月，某檔股票的每日本益比歷史（逐月請求，平行處理）。
    只支援上市股票——TWSE 官方沒有提供上櫃股票的本益比歷史查詢，上櫃股票這裡會回傳空清單。"""
    today = time.localtime()
    year_months = []
    y, m = today.tm_year, today.tm_mon
    for _ in range(months):
        year_months.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    rows = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_stock_pe_month, code, ym) for ym in year_months]
        for fut in as_completed(futures):
            try:
                rows.extend(fut.result())
            except Exception:
                pass
    rows.sort(key=lambda r: r["date"])
    return rows


def _percentile(sorted_values, pct):
    """線性插值百分位數，sorted_values 必須已經由小到大排序。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def compute_pe_band(code, months=24):
    """本益比河流圖：用股票自己過去的本益比區間（25%／50%／75%分位數）× 目前的隱含EPS
    （近四季，用「目前股價 ÷ 目前本益比」反推，因為證交所本來就用近四季EPS算本益比，
    不用我們自己另外抓四季財報湊），算出一個歷史相對的合理價格帶。這是用該股票自己的
    估值歷史區間當參考，不是絕對合理值，更不是預測未來股價，公司體質、產業展望改變時
    這個區間本身也會改變。"""
    pe_rows = fetch_stock_pe_history(code, months=months)
    price_rows = fetch_stock_daily_rows_for_chart(code, months=months)
    price_by_date = {r[0]: safe_float(r[6]) for r in price_rows if safe_float(r[6]) is not None}

    series = []
    for r in pe_rows:
        close = price_by_date.get(r["date"])
        pe = r["pe_ratio"]
        if close is None or pe is None or pe <= 0:
            continue
        series.append({"date": r["date"], "close": close, "pe_ratio": pe, "implied_eps_ttm": round(close / pe, 3)})

    if len(series) < 20:
        return {"error": "本益比歷史資料不足，可能是上櫃股票（本益比河流圖只支援上市）或近期剛掛牌"}

    pe_values = sorted(s["pe_ratio"] for s in series)
    current_eps_ttm = series[-1]["implied_eps_ttm"]
    current_price = series[-1]["close"]
    current_pe = series[-1]["pe_ratio"]

    low_pe = _percentile(pe_values, 0.25)
    mid_pe = _percentile(pe_values, 0.5)
    high_pe = _percentile(pe_values, 0.75)

    return {
        "current_price": current_price,
        "current_pe": current_pe,
        "current_eps_ttm": current_eps_ttm,
        "pe_low": round(low_pe, 2),
        "pe_mid": round(mid_pe, 2),
        "pe_high": round(high_pe, 2),
        "pe_min": round(pe_values[0], 2),
        "pe_max": round(pe_values[-1], 2),
        "fair_price_low": round(low_pe * current_eps_ttm, 2),
        "fair_price_mid": round(mid_pe * current_eps_ttm, 2),
        "fair_price_high": round(high_pe * current_eps_ttm, 2),
        "series": series,
    }


MATERIAL_INFO_TTL = 1800


def fetch_material_info_feed():
    """上市公司每日重大訊息公告（公開資訊觀測站經證交所整理的開放資料）。
    這支 API 只回傳最近一個交易日的公告批次，不是完整新聞來源，也不含上櫃公司。"""
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
    data = fetch_json(url, ttl=MATERIAL_INFO_TTL)
    out = {}
    for row in data:
        code = row.get("公司代號", "")
        if not code:
            continue
        out.setdefault(code, []).append({
            "date": row.get("發言日期", ""),
            "time": row.get("發言時間", ""),
            "subject": (row.get("主旨 ") or row.get("主旨") or "").strip(),
            "clause": row.get("符合條款", ""),
        })
    return out


def fetch_fundamentals(code, months=24):
    """個股基本面分析總覽：最新月營收、最新單季EPS、本益比河流圖（合理價格帶）、
    最近的重大訊息公告，整合在一起給前端做單一面板顯示。"""
    revenue = fetch_monthly_revenue().get(code)
    eps = fetch_eps().get(code)
    pe_band = compute_pe_band(code, months=months)
    material_info = fetch_material_info_feed().get(code, [])
    return {
        "code": code,
        "revenue": revenue,
        "eps": eps,
        "pe_band": pe_band,
        "material_info": material_info,
    }
