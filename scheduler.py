"""
背景排程：固定頻率更新「全市場共用資料」（不管是誰查，結果都一樣的那種），
寫進這支模組自己的記憶體字典（下面稱 Tier 2）。伺服器的每個 API 路由都只讀
這裡，不會自己再去打上游——這樣不管同時多少人在看，對外請求量只取決於
排程頻率，不會隨使用者數增加。這是把工具從「一個人在本機用」改成「公開給
很多人用」時最重要的一個架構調整，細節見 clever-conjuring-deer 那份規劃。

這裡跟 app_core.py 的 URL 快取（Tier 1）不是同一層：Tier 1 是「同一個 URL
短時間內不要重打」，這裡是「同一份邏輯上的資料整批定期更新」——有些資料
（例如 fetch_indices）本身是好幾個 URL 組合起來的，沒辦法只靠 URL 快取涵蓋；
也有一些原本完全沒有快取的資料（例如處置股回檔觀察），排進來就順便補上了。

某一項資料這次更新失敗（例如剛好遇到上游限流）時，保留上一次成功的結果繼續用，
不會讓排程整條線因為一項失敗就掛掉，也不會讓使用者突然看到空資料。
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app_core import BASE_DIR, atomic_write_json
import market_data
import sector_flow
import disposition
import fundamentals
import holders
import news
import screeners

STATE_FILE = BASE_DIR / "scheduler_state.json"

_state = {}  # name -> (timestamp, payload)
_state_lock = threading.Lock()
_last_run = {}

# 排程項目跟頻率，對應各自原本的 TTL／更新頻率，不是憑空發明的數字。
# 選股篩選器可調參數，這裡只預熱「預設參數」那組（對應前端表單的預設值，
# 大多數人不會改）；非預設參數維持現有的 on-demand 快取（single-flight 也保護到了）。
_JOBS = [
    ("indices", lambda: market_data.fetch_indices(), 15),
    ("stock_directory", lambda: market_data.fetch_stock_directory(), 3600),
    ("day_all", lambda: market_data.fetch_stock_day_all(), 300),
    ("market_snapshot", lambda: market_data.fetch_market_snapshot(), 1800),
    ("sector_flow", lambda: sector_flow.fetch_sector_flow(), 300),
    ("disposition", lambda: disposition.fetch_disposition(), 1800),
    ("attention", lambda: sorted(disposition.fetch_attention()), 1800),  # set 不能存進 JSON，排程階段先轉成排序過的 list
    ("margin_data", lambda: disposition.fetch_margin_data(), 1800),
    ("disposition_watch", lambda: disposition.fetch_disposition_pullback_watch(), 900),
    ("monthly_revenue", lambda: fundamentals.fetch_monthly_revenue(), 3600),
    ("eps", lambda: fundamentals.fetch_eps(), 3600),
    ("valuation", lambda: fundamentals.fetch_valuation(), 3600),
    ("material_info", lambda: fundamentals.fetch_material_info_feed(), 1800),
    ("holders", lambda: holders.get_holder_data(), 21600),
    ("news", lambda: news.fetch_ctee_news(), 900),
    ("screener_default", lambda: screeners.run_screener(
        boll_level_threshold=3.0, trend_days=10, long_term=False, min_trade_value=30_000_000), 1800),
    ("short_screener_default", lambda: screeners.run_short_screener(min_trade_value=10_000_000), 900),
    ("reversal_screener_default", lambda: screeners.run_reversal_short_screener(
        near_high_pct=3.0, min_shadow_ratio=1.0, min_trade_value=30_000_000), 1800),
]


def get(name, default=None):
    """給 server.py 的 route 讀排程結果，永遠不會觸發即時對外請求。"""
    with _state_lock:
        hit = _state.get(name)
        return hit[1] if hit else default


def stale_job_names():
    """哪些排程項目已經超過「2倍更新頻率」還沒成功更新過——通常代表那項資料
    持續抓取失敗（例如上游一直限流），給 /api/health 顯示，方便正式站台上
    發現排程是不是卡住了，不用整個伺服器當掉才被發現。"""
    now = time.time()
    stale = []
    with _state_lock:
        for name, _, interval in _JOBS:
            hit = _state.get(name)
            if hit is None or now - hit[0] > interval * 2:
                stale.append(name)
    return stale


def _load_persisted_state():
    try:
        if not STATE_FILE.exists():
            return
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        with _state_lock:
            for name, entry in saved.items():
                ts, payload = entry  # JSON 往返後 tuple 會變成 list，這裡解包成一樣的形狀
                _state[name] = (ts, payload)
    except Exception:
        pass  # 檔案不存在／壞掉都當作「還沒有暖資料」，讓後面的同步第一輪重新抓


def _persist_state():
    with _state_lock:
        snapshot = dict(_state)
    atomic_write_json(STATE_FILE, snapshot)


def _run_job(name, func):
    try:
        payload = func()
        with _state_lock:
            _state[name] = (time.time(), payload)
    except Exception as e:
        print(f"[scheduler] job {name!r} failed，沿用上一次的結果: {e}")


def _run_batch(jobs):
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_run_job, name, func) for name, func in jobs]
        for fut in futures:
            fut.result()
    _persist_state()


def _loop():
    while True:
        now = time.time()
        due = [(name, func) for name, func, interval in _JOBS if now - _last_run.get(name, 0) >= interval]
        if due:
            _run_batch(due)
            now2 = time.time()
            for name, _ in due:
                _last_run[name] = now2
        time.sleep(1)


def start():
    """伺服器啟動時呼叫：先讀本機持久化的舊資料 warm-start。已經有、而且還沒過期的
    項目直接沿用（重開伺服器/程式當掉自動重啟時不用整批重抓一次，啟動速度快很多）；
    缺漏或已過期的項目才同步抓一輪——確保伺服器開始接受連線前，Tier 2 裡每一項至少
    都有「夠新」的資料，路由不用處理「資料是空的」的情況。之後才開一條背景 thread
    依各自頻率持續更新。"""
    _load_persisted_state()
    now = time.time()
    stale_or_missing = []
    for name, func, interval in _JOBS:
        with _state_lock:
            hit = _state.get(name)
        if hit is None or now - hit[0] >= interval:
            stale_or_missing.append((name, func))
        else:
            _last_run[name] = hit[0]
    if stale_or_missing:
        _run_batch(stale_or_missing)
    now2 = time.time()
    for name, _, _ in _JOBS:
        _last_run.setdefault(name, now2)
    threading.Thread(target=_loop, daemon=True, name="scheduler").start()
