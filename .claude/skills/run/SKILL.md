---
name: run
description: Launch or restart the Taiwan Stock Tool local server (server.py on 127.0.0.1:8787) reliably on Windows without getting stuck on stale zombie processes.
---

# 啟動 / 重啟台股分析工具伺服器

This project is a Python stdlib HTTP server (`server.py`) serving a static frontend
(`static/index.html` + `static/app.js`) on `127.0.0.1:8787`. No dependencies to install.

**The one rule that matters:** never assume the process you just launched is the one
that ended up bound to the port. In long sessions, multiple `python server.py`
background launches can get queued; killing "the PID you think is running" and
starting a new one can still leave an old process holding the port if a second
queued launch wins the race. Always find-kill-verify by **port**, not by task ID.

## Restart procedure (do all 4 steps, in order, every time)

1. **Find and kill whatever is actually listening on 8787:**
   ```powershell
   Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
   Start-Sleep -Milliseconds 800
   ```
2. **Confirm the port is free** (should return nothing):
   ```powershell
   Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
   ```
3. **Start the server** from the project directory, in the background:
   ```bash
   cd /d/TaiwanStockTool && python server.py
   ```
4. **Verify the NEW code is actually live** — hit a route that only exists in the
   latest edits (not `/`, which won't prove anything about API changes):
   ```powershell
   Invoke-WebRequest -Uri "http://localhost:8787/api/sector_flow" -UseBasicParsing -TimeoutSec 20
   ```
   If a route you just added 404s, there's still a stale process on the port —
   go back to step 1. To see exactly what's running and when it started:
   ```powershell
   Get-CimInstance Win32_Process -Filter "name='python3.12.exe'" | Select-Object ProcessId, CreationDate, CommandLine
   ```

## Double-clicking 啟動.bat instead
`啟動.bat` in this folder does the launch + opens the browser, but it does **not**
do the kill-stale-process step above. If the server is already running (e.g. from
a previous Claude session), double-clicking it will fail to bind and silently
leave the old instance serving old code. Use the manual procedure above whenever
code just changed.

## Static file caching
`server.py` sends `Cache-Control: no-store` on `index.html` / `app.js`, so once
step 4 above confirms the server process itself is on the latest code, a normal
browser refresh (no hard-refresh / cache-clear needed) will show the latest
frontend immediately.

## The `static/_render_test.html` / debug-hook pattern
When a bug report can't be reproduced by reasoning about the code alone (e.g.
"chart X doesn't render"), don't guess — get a real answer via a same-origin
debug page instead of fighting headless-Chrome click simulation (unreliable with
`--virtual-time-budget` + real network fetches):

1. Temporarily add a tiny block at the end of `static/app.js`'s init section that
   reads `?debugCode=XXXX&debugMonths=N` from the URL, calls the real
   `selectStock()`, then after a `setTimeout` writes a JSON summary
   (`chartPoints.length`, any caught `window.onerror`, etc.) into `document.title`.
2. Fetch it with:
   ```powershell
   & $edge --headless=old --disable-gpu --virtual-time-budget=6000 --dump-dom "http://localhost:8787/?debugCode=2233&debugMonths=1" | Out-File out.html
   [regex]::Match((Get-Content out.html -Raw), '<title>(.*?)</title>').Groups[1].Value
   ```
3. Remove the debug block before shipping.

This exercises the *actual* app code (not a reimplementation), and `--dump-dom`
+ `document.title` sidesteps the fact that headless screenshots taken with
`--virtual-time-budget` often fire before real `fetch()` calls resolve.
