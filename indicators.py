"""
通用技術指標計算：月線（20日均線）、布林通道、量價背離代理指標。
被回測引擎、選股篩選、處置股回檔觀察等多個模組共用。
"""
from app_core import safe_float


def compute_ma20_series(rows):
    """rows: STOCK_DAY 的 data 陣列（[日期,量,額,開,高,低,收,漲跌,筆數,註記]）
    回傳依日期排序的 20 日均線（月線）數值序列"""
    closes = []
    for r in rows:
        c = safe_float(r[6])
        if c is not None:
            closes.append(c)
    if len(closes) < 20:
        return []
    return [sum(closes[i - 19:i + 1]) / 20 for i in range(19, len(closes))]


def compute_bollinger_now(rows, period=20, k=2):
    """回傳最新一天的布林通道（上軌／中軌／下軌）與「位階」（1～10，5.5＝中軌，
    10＝觸及上軌，1＝觸及下軌以下）。位階 ≤5 代表股價回檔到通道中線以下。"""
    closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((c - mean) ** 2 for c in window) / period
    sd = variance ** 0.5
    upper = mean + k * sd
    lower = mean - k * sd
    close = closes[-1]
    if upper == lower:
        level = 5.5
    else:
        pct_b = (close - lower) / (upper - lower)
        level = round(max(0.0, min(1.0, pct_b)) * 10, 1)
    return {"upper": round(upper, 2), "middle": round(mean, 2), "lower": round(lower, 2),
            "close": close, "level": level}


def compute_volume_bias(rows, days):
    """量價背離代理指標：近N個交易日「上漲日成交量」減「下跌日成交量」的差，
    正值代表量能偏向上漲日、負值代表偏向下跌日。這不是真正的主力進出（那需要券商分點資料，
    公開資料無法取得），只是用價量關係推算的近似代理指標，回傳 -100～100。"""
    closes = [safe_float(r[6]) for r in rows]
    volumes = [safe_float(r[1]) for r in rows]
    n = len(rows)
    if n < days + 1:
        return None
    up_vol = down_vol = 0.0
    for i in range(n - days, n):
        if closes[i] is None or closes[i - 1] is None or volumes[i] is None:
            continue
        if closes[i] > closes[i - 1]:
            up_vol += volumes[i]
        elif closes[i] < closes[i - 1]:
            down_vol += volumes[i]
    total = up_vol + down_vol
    if total <= 0:
        return None
    return round((up_vol - down_vol) / total * 100, 1)
