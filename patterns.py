"""
K棒型態辨識＋量價分析。全部是對「已經發生的K棒」做客觀分類，用的是教科書上有明確定義的
型態，不是對明天走勢的預測——型態本身在傳統技術分析裡代表什麼意思，會如實說明，
但不會下「所以會漲/會跌」這種結論。
"""
from app_core import safe_float


def _candle(row):
    o, h, l, c = safe_float(row[3]), safe_float(row[4]), safe_float(row[5]), safe_float(row[6])
    if None in (o, h, l, c):
        return None
    return {"date": row[0], "open": o, "high": h, "low": l, "close": c,
            "body": abs(c - o), "is_bull": c > o, "is_bear": c < o}


def detect_candlestick_patterns(rows, lookback_days=5):
    """掃描最近 lookback_days 個交易日，偵測有明確定義的K棒型態（多空各數種）。
    回傳依日期由新到舊排序的型態清單，每筆包含型態名稱、日期、多空分類、白話說明。"""
    candles = [_candle(r) for r in rows]
    candles = [c for c in candles if c is not None]
    if len(candles) < 12:
        return []

    avg_body_10 = lambda i: sum(candles[j]["body"] for j in range(i - 10, i)) / 10

    found = []
    start_i = max(11, len(candles) - lookback_days)
    for i in range(start_i, len(candles)):
        c0 = candles[i]
        c1 = candles[i - 1]
        c2 = candles[i - 2] if i >= 2 else None
        avg_body = avg_body_10(i)
        if avg_body <= 0:
            continue

        # 長黑K／長紅K：實體長度明顯大於近10日平均
        if c0["is_bear"] and c0["body"] > avg_body * 1.8:
            found.append({"date": c0["date"], "name": "長黑K", "bias": "bear",
                           "desc": "當天實體遠比近期平均長，收盤明顯遠低於開盤，代表當天賣壓強勁、賣方主導。"})
        elif c0["is_bull"] and c0["body"] > avg_body * 1.8:
            found.append({"date": c0["date"], "name": "長紅K", "bias": "bull",
                           "desc": "當天實體遠比近期平均長，收盤明顯遠高於開盤，代表當天買氣強勁、買方主導。"})

        # 空頭吞噬／多頭吞噬：今天實體完全包住昨天實體，方向相反
        if c1["is_bull"] and c0["is_bear"] and c0["open"] > c1["close"] and c0["close"] < c1["open"]:
            found.append({"date": c0["date"], "name": "空頭吞噬", "bias": "bear",
                           "desc": "今天的黑K實體完全包住昨天的紅K實體，代表原本的多方力道被一天之內完全反轉、賣壓明顯壓過買盤。"})
        elif c1["is_bear"] and c0["is_bull"] and c0["open"] < c1["close"] and c0["close"] > c1["open"]:
            found.append({"date": c0["date"], "name": "多頭吞噬", "bias": "bull",
                           "desc": "今天的紅K實體完全包住昨天的黑K實體，代表原本的空方力道被一天之內完全反轉、買盤明顯壓過賣壓。"})

        # 烏雲罩頂：昨天紅K，今天開高走低、收盤跌破昨天實體中點（但沒有完全吞噬，否則算吞噬）
        if (c1["is_bull"] and c0["is_bear"] and c0["open"] > c1["close"]
                and c0["close"] < (c1["open"] + c1["close"]) / 2 and c0["close"] > c1["open"]):
            found.append({"date": c0["date"], "name": "烏雲罩頂", "bias": "bear",
                           "desc": "今天開盤比昨天收盤還高，但收盤卻跌破昨天紅K實體的中點，代表高點有明顯獲利了結賣壓，是常見的高檔反轉警示型態。"})

        # 三黑兵／紅三兵：連續三天同方向、實體都不算小、收盤價依序遞減/遞增
        if c2 is not None:
            if (c2["is_bear"] and c1["is_bear"] and c0["is_bear"]
                    and c1["close"] < c2["close"] and c0["close"] < c1["close"]
                    and c2["body"] > avg_body * 0.5 and c1["body"] > avg_body * 0.5 and c0["body"] > avg_body * 0.5):
                found.append({"date": c0["date"], "name": "三黑兵", "bias": "bear",
                               "desc": "連續三天收黑且一天比一天低，代表空方連續三天主導，跌勢有延續性、不是單一天的雜訊。"})
            elif (c2["is_bull"] and c1["is_bull"] and c0["is_bull"]
                    and c1["close"] > c2["close"] and c0["close"] > c1["close"]
                    and c2["body"] > avg_body * 0.5 and c1["body"] > avg_body * 0.5 and c0["body"] > avg_body * 0.5):
                found.append({"date": c0["date"], "name": "紅三兵", "bias": "bull",
                               "desc": "連續三天收紅且一天比一天高，代表多方連續三天主導，漲勢有延續性、不是單一天的雜訊。"})

            # 黃昏之星／早晨之星：大實體 + 跳空小實體(十字星) + 反向深入第一天實體
            mid2 = (c2["open"] + c2["close"]) / 2
            small_body = candles[i - 1]["body"] < avg_body_10(i - 1) * 0.5 if avg_body_10(i - 1) > 0 else False
            if (c2["is_bull"] and c2["body"] > avg_body * 1.2 and small_body
                    and min(c1["open"], c1["close"]) > c2["close"]
                    and c0["is_bear"] and c0["close"] < mid2):
                found.append({"date": c0["date"], "name": "黃昏之星", "bias": "bear",
                               "desc": "第一天長紅K，第二天跳空收小實體（多空猶豫），第三天長黑K深入第一天實體，是經典的高檔三日反轉警示型態。"})
            elif (c2["is_bear"] and c2["body"] > avg_body * 1.2 and small_body
                    and max(c1["open"], c1["close"]) < c2["close"]
                    and c0["is_bull"] and c0["close"] > mid2):
                found.append({"date": c0["date"], "name": "早晨之星", "bias": "bull",
                               "desc": "第一天長黑K，第二天跳空收小實體（多空猶豫），第三天長紅K深入第一天實體，是經典的低檔三日反轉型態。"})

    found.sort(key=lambda p: p["date"], reverse=True)
    return found


def analyze_volume_trend(rows):
    """比較近5日與近20日均量、近5日價格變化，分類成價量配合／背離的白話描述。
    這是對已發生量價關係的客觀分類，不是預測。"""
    closes = [safe_float(r[6]) for r in rows if safe_float(r[6]) is not None]
    volumes = [safe_float(r[1]) for r in rows if safe_float(r[1]) is not None]
    if len(closes) < 21 or len(volumes) < 21:
        return None
    vol_avg_5 = sum(volumes[-5:]) / 5
    vol_avg_20 = sum(volumes[-20:]) / 20
    if vol_avg_20 <= 0:
        return None
    vol_ratio = vol_avg_5 / vol_avg_20
    vol_trend = "量增" if vol_ratio > 1.1 else "量縮" if vol_ratio < 0.9 else "量能持平"

    price_chg_5_pct = (closes[-1] - closes[-6]) / closes[-6] * 100 if closes[-6] else 0
    price_up = price_chg_5_pct > 0.5
    price_down = price_chg_5_pct < -0.5

    if price_up and vol_ratio > 1.1:
        label, desc = "價漲量增", "近5日上漲，且成交量比近20日均量放大，動能有量能支撐，是相對健康的上漲型態。"
    elif price_up and vol_ratio < 0.9:
        label, desc = "價漲量縮", "近5日上漲，但成交量比近20日均量萎縮，追價意願不足，若持續量縮要留意上漲力道是否減弱。"
    elif price_down and vol_ratio > 1.1:
        label, desc = "價跌量增", "近5日下跌，且成交量比近20日均量放大，賣壓相對明確、不是無量陰跌。"
    elif price_down and vol_ratio < 0.9:
        label, desc = "價跌量縮", "近5日下跌，但成交量比近20日均量萎縮，賣壓可能逐漸鈍化，也可能只是觀望氣氛濃厚。"
    else:
        label, desc = "價量無明顯訊號", "近5日價格變化不大或量能變化不明顯，暫時看不出價量背離或配合的跡象。"

    return {
        "vol_trend": vol_trend, "vol_ratio_pct": round((vol_ratio - 1) * 100, 1),
        "price_chg_5_pct": round(price_chg_5_pct, 2), "label": label, "desc": desc,
    }
