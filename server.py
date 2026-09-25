"""
台股分析工具 - 本機伺服器
用純 Python 標準函式庫代理證交所 API（避開瀏覽器 CORS 限制），並提供前端網頁。
執行方式: python server.py
然後開啟瀏覽器: http://localhost:8787

程式碼依功能拆成多個模組（app_core / indicators / patterns / market_data /
backtest / holders / sector_flow / fundamentals / disposition / screeners），
這支檔案只負責 HTTP 路由與伺服器啟動。
"""
import json
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app_core import PORT, STATIC_DIR, check_backend_health
from patterns import detect_candlestick_patterns, analyze_volume_trend
from market_data import (
    fetch_quotes_for_codes,
    fetch_index_daily_rows,
    fetch_stock_daily_rows_for_chart,
    fetch_intraday,
    fetch_intraday_pattern,
)
from backtest import (
    _backtest_params_from_qs,
    run_backtest,
    compare_backtest_strategies,
    run_live_signal,
    scan_backtest_buy_signals,
)
from sector_flow import build_sector_flow_heatmap, fetch_sector_stocks
from fundamentals import fetch_fundamentals
from screeners import run_screener, run_short_screener, run_reversal_short_screener
from chips import fetch_stock_institutional_and_margin_history, fetch_margin_detail, analyze_chip_divergence
import scheduler

MAX_BACKTEST_SCAN_CODES = 150  # 使用者輸入、沒有上限的話是最容易被濫用來打爆上游的端點

# 組好的 JS bundle 快取在記憶體裡，key 是所有原始檔案裡最新的修改時間——正式環境
# 檔案不會變，每個請求都是直接回傳快取，不用再重讀+串接13-14支檔案；本機開發時
# 改了任何一支 js 檔案，mtime 會變，下一個請求自動重新組一次，不用額外的 dev/prod
# 開關，也不會忘記切換。
_js_bundle_cache = {"mtime": None, "body": b""}
_js_bundle_lock = threading.Lock()


def _build_js_bundle():
    js_dir = STATIC_DIR / "js"
    files = sorted(js_dir.glob("*.js"))
    latest_mtime = max((p.stat().st_mtime for p in files), default=0)
    with _js_bundle_lock:
        if _js_bundle_cache["mtime"] == latest_mtime and _js_bundle_cache["body"]:
            return _js_bundle_cache["body"]
    # 每個檔案本身已經以換行結尾，直接相接就好，不用再插入換行
    parts = [p.read_text(encoding="utf-8") for p in files]
    body = "".join(parts).encode("utf-8")
    with _js_bundle_lock:
        _js_bundle_cache["mtime"] = latest_mtime
        _js_bundle_cache["body"] = body
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 安靜一點，不要洗控制台

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 明確禁止瀏覽器把 JSON 回應當成 HTML 嗅探解析，多一層防護
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # 開發中頻繁改動 app.js/index.html，避免瀏覽器快取舊版造成「明明改了還是舊行為」
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_bundled_js(self):
        """前端原始碼拆成 static/js/ 底下多個依編號排序的檔案（方便維護／導覽），
        但瀏覽器仍然只拿到一支合併後的 app.js——這些檔案原本就是同一個大 IIFE
        的內部區塊，靠檔名編號串接回單一執行環境，語意跟拆檔前完全一樣。"""
        body = _build_js_bundle()
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if parsed.path == "/" or parsed.path == "/index.html":
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/app.js":
                self._send_bundled_js()
                return

            if parsed.path == "/api/quote":
                codes = qs.get("codes", [""])[0]
                codes = [c.strip() for c in codes.split(",") if c.strip()]
                if not codes:
                    self._send_json({"error": "missing codes"}, 400)
                    return
                self._send_json({"quotes": fetch_quotes_for_codes(codes)})
                return

            if parsed.path == "/api/health":
                self._send_json({
                    "ok": check_backend_health(),
                    "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "stale_jobs": scheduler.stale_job_names(),
                })
                return

            if parsed.path == "/api/indices":
                self._send_json(scheduler.get("indices", {}))
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
                self._send_json({"data": scheduler.get("day_all", [])})
                return

            if parsed.path == "/api/stock_directory":
                self._send_json({"data": scheduler.get("stock_directory", [])})
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

            if parsed.path == "/api/pattern_analysis":
                code = qs.get("code", [""])[0].strip()
                key = qs.get("key", [""])[0].strip()
                if key:
                    _display_name, rows = fetch_index_daily_rows(key, months=3)
                elif code:
                    rows = fetch_stock_daily_rows_for_chart(code, months=3)
                else:
                    self._send_json({"error": "missing code or key"}, 400)
                    return
                self._send_json({
                    "patterns": detect_candlestick_patterns(rows),
                    "volume": analyze_volume_trend(rows),
                })
                return

            if parsed.path == "/api/backtest":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                strategy = qs.get("strategy", ["ma_cross"])[0].strip()
                timeframe = qs.get("timeframe", ["daily"])[0].strip()
                months = int(qs.get("months", ["24"])[0])
                days = int(qs.get("days", ["30"])[0])
                initial_capital = float(qs.get("initial_capital", ["100000"])[0])
                include_fee = qs.get("include_fee", ["1"])[0] == "1"
                params = _backtest_params_from_qs(qs)
                result = run_backtest(code, timeframe=timeframe, months=months, days=days, strategy=strategy,
                                       params=params, initial_capital=initial_capital, include_fee=include_fee)
                if "error" in result:
                    self._send_json(result, 400)
                    return
                self._send_json(result)
                return

            if parsed.path == "/api/backtest_compare":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                timeframe = qs.get("timeframe", ["daily"])[0].strip()
                months = int(qs.get("months", ["24"])[0])
                days = int(qs.get("days", ["30"])[0])
                initial_capital = float(qs.get("initial_capital", ["100000"])[0])
                include_fee = qs.get("include_fee", ["1"])[0] == "1"
                result = compare_backtest_strategies(code, timeframe=timeframe, months=months, days=days,
                                                      initial_capital=initial_capital, include_fee=include_fee)
                if "error" in result:
                    self._send_json(result, 400)
                    return
                self._send_json(result)
                return

            if parsed.path == "/api/backtest_live":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                strategy = qs.get("strategy", ["ma_cross"])[0].strip()
                timeframe = qs.get("timeframe", ["daily"])[0].strip()
                months = int(qs.get("months", ["24"])[0])
                days = int(qs.get("days", ["30"])[0])
                params = _backtest_params_from_qs(qs)
                result = run_live_signal(code, timeframe=timeframe, strategy=strategy, params=params,
                                          months=months, days=days)
                if "error" in result:
                    self._send_json(result, 400)
                    return
                self._send_json(result)
                return

            if parsed.path == "/api/backtest_scan":
                codes = qs.get("codes", [""])[0]
                codes = [c.strip() for c in codes.split(",") if c.strip()]
                if not codes:
                    self._send_json({"error": "missing codes"}, 400)
                    return
                if len(codes) > MAX_BACKTEST_SCAN_CODES:
                    self._send_json(
                        {"error": f"最多一次掃描 {MAX_BACKTEST_SCAN_CODES} 檔，請減少代碼數量"}, 400)
                    return
                strategy = qs.get("strategy", ["ma_cross"])[0].strip()
                timeframe = qs.get("timeframe", ["daily"])[0].strip()
                months = int(qs.get("months", ["24"])[0])
                days = int(qs.get("days", ["30"])[0])
                min_volume_lots = float(qs.get("min_volume_lots", ["1000"])[0])
                params = _backtest_params_from_qs(qs)
                results = scan_backtest_buy_signals(codes, timeframe=timeframe, strategy=strategy, params=params,
                                                     months=months, days=days, min_volume_lots=min_volume_lots)
                self._send_json({"results": results})
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
                boll_level_threshold = float(qs.get("boll_level_threshold", ["3"])[0])
                trend_days = int(qs.get("trend_days", ["10"])[0])
                long_term = qs.get("long_term", ["0"])[0] == "1"
                min_trade_value_wan = float(qs.get("min_trade_value_wan", ["3000"])[0])
                payload = run_screener(
                    boll_level_threshold=boll_level_threshold, trend_days=trend_days, long_term=long_term,
                    min_trade_value=min_trade_value_wan * 10000,
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/short_screener":
                min_trade_value_wan = float(qs.get("min_trade_value_wan", ["1000"])[0])
                payload = run_short_screener(min_trade_value=min_trade_value_wan * 10000)
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
                self._send_json({"data": scheduler.get("sector_flow", []), "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
                return

            if parsed.path == "/api/sector_flow_history":
                self._send_json(build_sector_flow_heatmap())
                return

            if parsed.path == "/api/sector_stocks":
                industry = qs.get("industry", [""])[0].strip()
                if not industry:
                    self._send_json({"error": "missing industry"}, 400)
                    return
                self._send_json({"industry": industry, "data": fetch_sector_stocks(industry)})
                return

            if parsed.path == "/api/news":
                self._send_json({"data": scheduler.get("news", [])})
                return

            if parsed.path == "/api/fundamentals":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                months = int(qs.get("months", ["24"])[0])
                self._send_json(fetch_fundamentals(code, months=months))
                return

            if parsed.path == "/api/chips":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                days = max(3, min(int(qs.get("days", ["20"])[0]), 120))
                history, margin_history = fetch_stock_institutional_and_margin_history(code, days=days)
                self._send_json({
                    "code": code,
                    "history": history,
                    "margin": fetch_margin_detail(code),
                    "margin_history": margin_history,
                    "divergence": analyze_chip_divergence(code, days=days, history=history),
                })
                return

            if parsed.path == "/api/holders":
                code = qs.get("code", [""])[0].strip()
                if not code:
                    self._send_json({"error": "missing code"}, 400)
                    return
                holders = scheduler.get("holders", {}).get(code)
                if holders is None:
                    self._send_json({"code": code, "error": "not found"})
                    return
                self._send_json({"code": code, **holders})
                return

            if parsed.path == "/api/disposition":
                disp = scheduler.get("disposition", {})
                rows = [{"code": c, **v} for c, v in disp.items()]
                self._send_json({"data": rows})
                return

            if parsed.path == "/api/disposition_watch":
                self._send_json({
                    "data": scheduler.get("disposition_watch", []),
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                return

            if parsed.path == "/api/attention":
                self._send_json({"data": scheduler.get("attention", [])})
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
    print("正在預熱背景資料快取…")
    scheduler.start()
    url = f"http://localhost:{PORT}"
    print(f"台股分析工具已啟動: {url}")
    print("按 Ctrl+C 停止伺服器（關閉這個視窗也會停止）")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
