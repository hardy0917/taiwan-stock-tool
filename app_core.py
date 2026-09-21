"""
共用基礎設施：設定常數、簡單快取、HTTP 抓取工具。
其他模組都從這裡 import，這支檔案本身不依賴任何其他自訂模組（避免循環 import）。
"""
import json
import sys
import time
import threading
import urllib.request
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


def safe_float(v, default=None):
    if v in (None, "", "-", "－"):
        return default
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return default
