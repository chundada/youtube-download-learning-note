#!/usr/bin/env python3
"""
get_yt_title.py — 获取 YouTube 视频中文标题
从 YouTube 页面解析中文标题，用于文件名命名。

用法:
  python3 get_yt_title.py <URL>
  python3 get_yt_title.py <URL1> [URL2] ...
  cat urls.txt | python3 get_yt_title.py

输出: URL \t 中文标题
"""

import sys, re, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

PROXY = "http://127.0.0.1:2080"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def fetch_page(url: str) -> str:
    """请求 YouTube 页面，返回 HTML"""
    proxy = PROXY
    # 优先使用环境变量
    import os
    if os.environ.get("HTTP_PROXY"):
        proxy = os.environ["HTTP_PROXY"]
    elif os.environ.get("HTTPS_PROXY"):
        proxy = os.environ["HTTPS_PROXY"]

    proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with opener.open(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def has_zh(text: str) -> bool:
    """检查是否含中文字符"""
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def parse_title_from_html(html: str) -> str:
    """从 YouTube 页面 HTML 提取中文标题"""

    # 1) ytInitialData — Shorts 标题
    m = re.search(r"ytInitialData\s*=\s*({.*?});", html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            # Shorts: reelPlayerOverlayRenderer
            overlay = data.get("overlay", {})
            reel = overlay.get("reelPlayerOverlayRenderer", {})
            metapanel = reel.get("metapanel", {}).get("reelMetapanelViewModel", {})
            for item in metapanel.get("metadataItems", []):
                content = (
                    item.get("shortsVideoTitleViewModel", {})
                    .get("text", {})
                    .get("content", "")
                )
                if content and has_zh(content):
                    return content

            # 普通视频: videoDescriptionHeaderRenderer
            for panel in data.get("engagementPanels", []):
                items = (
                    panel.get("engagementPanelSectionListRenderer", {})
                    .get("content", {})
                    .get("structuredDescriptionContentRenderer", {})
                    .get("items", [])
                )
                for item in items:
                    runs = (
                        item.get("videoDescriptionHeaderRenderer", {})
                        .get("title", {})
                        .get("runs", [])
                    )
                    text = "".join(r.get("text", "") for r in runs)
                    if text and has_zh(text):
                        return text
        except Exception:
            pass

    # 2) og:title 回退
    m = re.search(r'og:title"\s*content="([^"]+)"', html)
    if m:
        return m.group(1)

    # 3) <title> 回退
    m = re.search(r"<title>([^<]+)</title>", html)
    if m:
        t = m.group(1).replace(" - YouTube", "").strip()
        return t

    return ""


def get_zh_title(url: str) -> str:
    """获取单个视频的中文标题"""
    try:
        html = fetch_page(url)
        return parse_title_from_html(html)
    except Exception:
        return ""


def main():
    urls = list(sys.argv[1:]) if len(sys.argv) > 1 else []
    if not sys.stdin.isatty():
        urls += [l.strip() for l in sys.stdin if l.strip()]

    if not urls:
        print("用法: get_yt_title.py <URL> [URL2] ...", file=sys.stderr)
        sys.exit(1)

    # 多线程批量获取
    results = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        fut_map = {ex.submit(get_zh_title, u): u for u in urls}
        for f in as_completed(fut_map):
            url = fut_map[f]
            results[url] = f.result()

    for url in urls:
        title = results.get(url, "")
        if title:
            print(f"{url}\t{title}")
        else:
            print(f"{url}\t(获取失败)")


if __name__ == "__main__":
    main()
