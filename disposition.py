"""
處置股／注意股公告，以及處置股回檔觀察名單（回檔到布林中線以下的清單，
給想接刀／搶反彈的人做參考觀察，不是進場建議）。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from app_core import fetch_json, safe_float
from indicators import compute_bollinger_now
from market_data import fetch_stock_daily_rows


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
