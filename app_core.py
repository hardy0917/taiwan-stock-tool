"""
共用基礎設施：設定常數、快取（含 single-flight／全域流量閥）、HTTP 抓取工具。
其他模組都從這裡 import，這支檔案本身不依賴任何其他自訂模組（避免循環 import）。
"""
import json
import os
import sys
import time
import threading
import urllib.request
from collections import OrderedDict
from pathlib import Path

PORT = 8787
# 打包成 .exe（PyInstaller）執行時，用執行檔所在目錄找 static/；
# 用 python server.py 執行時，用這支程式所在目錄找 static/。
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockTool/1.0)"}

# ---------- 全域對外流量閥 ----------
# 不管是背景排程還是使用者觸發的查詢，所有真正打到證交所/櫃買中心/Yahoo 的請求
# 都要先拿到這個閥門，同時最多 N 個在飛行中——這是在公開給很多人用時，防止把
# 上游打到限流/封鎖的硬保險（這個 session 已經實測過，太密集的平行請求會被
# 證交所 CDN 擋掉），比個別模組各自控制併發數更可靠，因為所有來源都共用同一個上限。
OUTBOUND_CONCURRENCY = int(os.environ.get("TST_OUTBOUND_CONCURRENCY", "10"))
_outbound_semaphore = threading.Semaphore(OUTBOUND_CONCURRENCY)
_outbound_stats_lock = threading.Lock()
_outbound_stats = {"total": 0, "current": 0, "peak": 0}


def get_outbound_stats():
    """對外請求的統計數字（累計次數／目前飛行中／歷史尖峰），只給本機驗證用
    （TST_DEBUG_STATS=1 時定期印出），不對外開放成 API。"""
    with _outbound_stats_lock:
        return dict(_outbound_stats)


class throttled_urlopen:
    """跟 urllib.request.urlopen 用法一樣（with 區塊拿到 response），但受全域流量閥保護。
    給沒有走 fetch_json/fetch_text 的少數地方用（例如自己發 POST 的 fetch_txf_futures），
    讓「所有對外請求都經過同一個閥門」這件事沒有例外。"""

    def __init__(self, req, timeout=15):
        self.req = req
        self.timeout = timeout
        self._resp = None

    def __enter__(self):
        _outbound_semaphore.acquire()
        with _outbound_stats_lock:
            _outbound_stats["total"] += 1
            _outbound_stats["current"] += 1
            _outbound_stats["peak"] = max(_outbound_stats["peak"], _outbound_stats["current"])
        try:
            self._resp = urllib.request.urlopen(self.req, timeout=self.timeout)
            return self._resp
        except Exception:
            self._release()
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._resp is not None:
            self._resp.close()
        self._release()

    def _release(self):
        with _outbound_stats_lock:
            _outbound_stats["current"] -= 1
        _outbound_semaphore.release()


# ---------- URL 快取（LRU 上限 + single-flight） ----------
_CACHE_MAX_ENTRIES = 20000
_cache = OrderedDict()  # url -> (timestamp, data)
_cache_lock = threading.Lock()

# 同一個 URL 如果同時有好幾個 request 都發現快取沒中，只讓第一個真的去打（leader），
# 其他人排隊等它的結果（waiter），不要每個人各自重打一次——這是公開給很多人用時
# 最重要的一個修正：沒有這層保護的話，1000人同時看同一支熱門股票，會瞬間對上游
# 發出1000次一樣的請求。
_inflight = {}
_inflight_lock = threading.Lock()


def _fetch_cached(url, ttl, timeout, decode_fn):
    with _cache_lock:
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < ttl:
            _cache.move_to_end(url)
            return hit[1]

    with _inflight_lock:
        entry = _inflight.get(url)
        if entry is None:
            entry = {"event": threading.Event(), "result": None, "error": None}
            _inflight[url] = entry
            is_leader = True
        else:
            is_leader = False

    if not is_leader:
        entry["event"].wait()
        if entry["error"] is not None:
            raise entry["error"]
        return entry["result"]

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with throttled_urlopen(req, timeout=timeout) as resp:
            data = decode_fn(resp.read())
        with _cache_lock:
            _cache[url] = (time.time(), data)
            _cache.move_to_end(url)
            while len(_cache) > _CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)
        entry["result"] = data
        return data
    except Exception as e:
        entry["error"] = e
        raise
    finally:
        entry["event"].set()
        with _inflight_lock:
            _inflight.pop(url, None)


def fetch_json(url, ttl=10):
    return _fetch_cached(url, ttl, timeout=15, decode_fn=lambda b: json.loads(b.decode("utf-8")))


def fetch_text(url, ttl=10):
    return _fetch_cached(url, ttl, timeout=30, decode_fn=lambda b: b.decode("utf-8-sig"))


# ---------- 通用的「整包結果快取」single-flight 工具 ----------
# 跟上面 URL 快取的邏輯一樣，但套用在「用 (dict, lock, key) 存彙總結果」的地方
# （例如選股篩選器把整包篩選結果存進自己的 module-level cache）——避免同一組
# 參數在快取剛好過期的瞬間，被好幾個併發請求同時重算一次。
_call_inflight = {}
_call_inflight_lock = threading.Lock()


def cached_call(cache_dict, lock, key, ttl, compute_fn):
    with lock:
        hit = cache_dict.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]

    inflight_key = (id(cache_dict), key)
    with _call_inflight_lock:
        entry = _call_inflight.get(inflight_key)
        if entry is None:
            entry = {"event": threading.Event(), "result": None, "error": None}
            _call_inflight[inflight_key] = entry
            is_leader = True
        else:
            is_leader = False

    if not is_leader:
        entry["event"].wait()
        if entry["error"] is not None:
            raise entry["error"]
        return entry["result"]

    try:
        result = compute_fn()
        with lock:
            cache_dict[key] = (time.time(), result)
        entry["result"] = result
        return result
    except Exception as e:
        entry["error"] = e
        raise
    finally:
        entry["event"].set()
        with _call_inflight_lock:
            _call_inflight.pop(inflight_key, None)


def atomic_write_json(path, obj):
    """寫暫存檔再 rename，避免本機快取檔案在高併發讀寫下被寫壞
    （寫到一半程式被中斷，原檔案內容還是完整的舊版本，不會變成半截 JSON）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def check_backend_health():
    """輕量探測：能不能連到證交所（不是本機伺服器本身，是本機伺服器→證交所這段）"""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw&json=1&delay=0"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with throttled_urlopen(req, timeout=5) as resp:
            resp.read(200)  # 只要證明連得到、有在回應，不用整包讀完
        return True
    except Exception:
        return False


def safe_float(v, default=None):
    if v in (None, "", "-", "－"):
        return default
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return default
