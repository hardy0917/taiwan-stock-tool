"""
產業資金流向：今日各產業成交值加權漲跌幅排行，以及本機累積快照做出的
近期（最多20個交易日）熱力圖。
"""
import json
import threading

from app_core import BASE_DIR, fetch_json, safe_float
from fundamentals import fetch_monthly_revenue

SECTOR_FLOW_SNAPSHOT_FILE = BASE_DIR / "sector_flow_snapshots.json"
SECTOR_FLOW_HISTORY_DAYS = 20  # 熱力圖保留的交易日數上限
_sector_flow_snapshot_lock = threading.Lock()


def _roc_date_from_yyyymmdd(date_str):
    """把 STOCK_DAY_ALL 的 Date 欄位（民國年，如 "1150918"）轉成跟其他地方一致
    的 "115/09/18" 格式，當作快照的日期鍵值。"""
    if not date_str or len(date_str) < 5:
        return None
    year, month, day = date_str[:-4], date_str[-4:-2], date_str[-2:]
    return f"{year}/{month}/{day}"


def _save_sector_flow_snapshot(trade_date, results):
    """把今天算好的產業資金流向存進本機檔案，累積成歷史紀錄，供熱力圖使用。
    這支工具沒有付費資料源可以直接查「過去N天的產業歷史」，只能像 TDCC 大戶
    持股一樣，靠每次執行時累積快照——剛開始用的前幾天資料會比較少，屬正常現象，
    用得越久資料越完整（最多保留 20 個交易日）。"""
    if not trade_date:
        return
    with _sector_flow_snapshot_lock:
        try:
            snapshots = json.loads(SECTOR_FLOW_SNAPSHOT_FILE.read_text(encoding="utf-8")) \
                if SECTOR_FLOW_SNAPSHOT_FILE.exists() else {}
        except (json.JSONDecodeError, OSError):
            snapshots = {}
        snapshots[trade_date] = {
            r["industry"]: {
                "change_pct": r["value_weighted_change_pct"],
                "total_value_billion": r["total_value_billion"],
                "advance": r["advance"], "decline": r["decline"], "stock_count": r["stock_count"],
            } for r in results
        }
        # 只保留最近 N 個交易日，避免檔案無限長大
        for old_date in sorted(snapshots.keys())[:-SECTOR_FLOW_HISTORY_DAYS]:
            del snapshots[old_date]
        try:
            SECTOR_FLOW_SNAPSHOT_FILE.write_text(json.dumps(snapshots, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def load_sector_flow_history():
    """回傳累積到目前為止的產業資金流向歷史快照，給熱力圖用。天數視本機已經
    執行過幾個不同交易日而定，不保證滿 20 天。"""
    with _sector_flow_snapshot_lock:
        try:
            return json.loads(SECTOR_FLOW_SNAPSHOT_FILE.read_text(encoding="utf-8")) \
                if SECTOR_FLOW_SNAPSHOT_FILE.exists() else {}
        except (json.JSONDecodeError, OSError):
            return {}


def fetch_sector_flow():
    """依產業別彙總今日漲跌家數與成交值加權漲跌幅，作為資金流向的代理指標：
    成交值加權漲跌% 越高，代表資金越集中湧入該產業；越低代表資金流出。
    順便把結果存進本機快照檔，累積成熱力圖用的歷史資料。"""
    day_data = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", ttl=300)
    revenue_map = fetch_monthly_revenue()
    trade_date = _roc_date_from_yyyymmdd(day_data[0].get("Date")) if day_data else None

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
    _save_sector_flow_snapshot(trade_date, results)
    return results


def fetch_sector_stocks(industry):
    """回傳指定產業別的成分股清單（今日收盤價、漲跌%、成交值），依成交值排序，
    供熱力圖「點產業看成分股」功能使用。"""
    day_data = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", ttl=300)
    revenue_map = fetch_monthly_revenue()

    rows = []
    for row in day_data:
        code = row.get("Code", "")
        if len(code) != 4 or not code.isdigit() or code.startswith("00"):
            continue
        if revenue_map.get(code, {}).get("industry", "未分類") != industry:
            continue
        close = safe_float(row.get("ClosingPrice"))
        change = safe_float(row.get("Change"))
        value = safe_float(row.get("TradeValue"))
        if close is None or change is None or value is None or close <= 0:
            continue
        base = close - change
        change_pct = round(change / base * 100, 2) if base else 0
        rows.append({
            "code": code,
            "name": row.get("Name", ""),
            "close": close,
            "change_pct": change_pct,
            "value_billion": round(value / 1e8, 3),
        })
    rows.sort(key=lambda r: r["value_billion"], reverse=True)
    return rows


def build_sector_flow_heatmap():
    """把累積的產業資金流向快照整理成熱力圖用的矩陣：依日期排序的欄、依「最新一天
    漲跌幅」排序的列。天數視本機累積到多少快照而定，不保證滿 20 天（詳見
    load_sector_flow_history 的說明）。"""
    snapshots = load_sector_flow_history()
    dates = sorted(snapshots.keys())
    industries = set()
    for day in snapshots.values():
        industries.update(day.keys())

    def latest_change(industry):
        for d in reversed(dates):
            v = snapshots[d].get(industry)
            if v is not None:
                return v["change_pct"]
        return -999

    industries = sorted(industries, key=latest_change, reverse=True)
    rows = []
    for industry in industries:
        changes = [snapshots[d].get(industry, {}).get("change_pct") for d in dates]
        if all(c is None for c in changes):
            continue
        rows.append({"industry": industry, "changes": changes})

    return {"dates": dates, "rows": rows}
