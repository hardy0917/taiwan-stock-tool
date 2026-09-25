"""
大戶持股（集保股權分散表，每週五更新）。本機累積快照，跟目前抓到的最新一週跟
上一週比較增減——工具剛開始使用的前幾天還沒跨過一次週報更新，增減會是 None。
"""
import json
import threading

from app_core import BASE_DIR, atomic_write_json, fetch_text, safe_float

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
            atomic_write_json(TDCC_SNAPSHOT_FILE, snapshots)

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
