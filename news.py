"""
重要新聞：工商時報官網有反爬蟲擋掉伺服器端直接抓取（403），改走 Google 新聞 RSS
以 site:ctee.com.tw 過濾，一樣是工商時報的新聞，只是連結會先經過 news.google.com 轉址。
"""
import re
import urllib.parse
import xml.etree.ElementTree as ET

from app_core import fetch_text

NEWS_TTL = 900  # 15 分鐘

_TITLE_SOURCE_RE = re.compile(r"\s*-\s*工商時報\s*$")


def fetch_ctee_news(limit=30, keyword=None):
    """回傳最近兩天工商時報新聞清單：[{title, link, pub_date, source}, ...]
    keyword 可選，加了會一併帶入查詢字串（例如產業名稱），縮小範圍。"""
    q = "site:ctee.com.tw when:2d"
    if keyword:
        q = f"{keyword} {q}"
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        xml_text = fetch_text(url, ttl=NEWS_TTL)
    except Exception:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        title = _TITLE_SOURCE_RE.sub("", title)
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "工商時報"
        if not title or not link:
            continue
        items.append({"title": title, "link": link, "pub_date": pub_date, "source": source})
    return items
