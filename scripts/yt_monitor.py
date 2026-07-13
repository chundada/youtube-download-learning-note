#!/usr/bin/env python3
"""
YouTube 频道监控 — 完整版 (yt_monitor.py)
扫描频道最新视频，过滤中文标题，自动下载新视频。
跨平台支持：Windows / macOS / Linux

用法：
  python yt_monitor.py [--dry-run] [--channel CHANNEL] [--list]
  python yt_monitor.py --dry-run          # 仅扫描不下载
  python yt_monitor.py --channel xxx      # 只处理指定频道
  python yt_monitor.py --list             # 只列出频道

依赖：
  pip install requests yt-dlp
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ─── 配置 ────────────────────────────────────────

PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:2080")
MIN_DATE = "20260101"
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
DB_PATH = SCRIPT_DIR / "videos_shorts_list.db"
CHANNEL_FILE = SCRIPT_DIR / "youtuber_list.md"


# ─── 工具函数 ────────────────────────────────────


def has_chinese(text):
    """检查文本是否包含中文字符"""
    return bool(re.search(r'[\u4e00-\u9fff]', text or ""))


def parse_relative_date(text):
    """解析 YouTube 相对时间（如"3天前"）为日期字符串"""
    now = datetime.now()
    text = (text or "").strip()

    m = re.search(r'(\d+)\s*小时前', text)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).strftime("%Y%m%d")
    m = re.search(r'(\d+)\s*天前', text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y%m%d")
    m = re.search(r'(\d+)\s*周前', text)
    if m:
        return (now - timedelta(weeks=int(m.group(1)))).strftime("%Y%m%d")
    m = re.search(r'(\d+)\s*个月前', text)
    if m:
        return (now - timedelta(days=int(m.group(1)) * 30)).strftime("%Y%m%d")
    m = re.search(r'(\d+)\s*年前', text)
    if m:
        return (now - timedelta(days=int(m.group(1)) * 365)).strftime("%Y%m%d")

    return None


def fetch_page(url, headers=None, timeout=15):
    """带代理发送 HTTP GET 请求"""
    proxies = {"http": PROXY, "https": PROXY} if PROXY else None
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if headers:
        default_headers.update(headers)

    try:
        resp = requests.get(url, headers=default_headers, proxies=proxies, timeout=timeout)
        return resp
    except Exception as e:
        print(f"  请求失败: {e}")
        return None


def extract_yt_initial_data(html):
    """从 YouTube 页面 HTML 中提取 ytInitialData JSON"""
    patterns = [
        r'var ytInitialData\s*=\s*({.*?});</script>',
        r'ytInitialData\s*=\s*({.*?});',
    ]
    for p in patterns:
        m = re.search(p, html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    return None


# ─── 数据库 ──────────────────────────────────────


def init_db():
    """初始化 SQLite 数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtuber TEXT NOT NULL,
            video_id TEXT UNIQUE NOT NULL,
            title TEXT,
            duration TEXT,
            views TEXT,
            pub_date TEXT,
            downloaded INTEGER DEFAULT 0,
            file_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS shorts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtuber TEXT NOT NULL,
            short_id TEXT UNIQUE NOT NULL,
            title TEXT,
            duration TEXT,
            views TEXT,
            pub_date TEXT,
            downloaded INTEGER DEFAULT 0,
            file_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn


def video_exists(conn, video_id):
    """检查视频是否已下载"""
    c = conn.cursor()
    c.execute("SELECT 1 FROM videos WHERE video_id = ? AND downloaded = 1", (video_id,))
    return c.fetchone() is not None


def insert_video(conn, youtuber, video_id, title, duration="", views="", pub_date=""):
    """将视频信息插入数据库"""
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR IGNORE INTO videos (youtuber, video_id, title, duration, views, pub_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (youtuber, video_id, title, duration, views, pub_date))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f"  数据库插入失败: {e}")
        return False


def mark_downloaded(conn, video_id, file_path):
    """标记视频为已下载"""
    c = conn.cursor()
    c.execute(
        "UPDATE videos SET downloaded = 1, file_path = ? WHERE video_id = ?",
        (file_path, video_id)
    )
    conn.commit()


# ─── 频道扫描 ─────────────────────────────────────


def get_channel_list():
    """从 youtuber_list.md 读取频道列表"""
    channels = []
    if not CHANNEL_FILE.exists():
        print(f"[X] 频道列表不存在: {CHANNEL_FILE}")
        return []

    with open(CHANNEL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^-\s*([A-Za-z0-9_-]+)$', line)
            if m:
                channels.append(m.group(1))
    return channels


def scrape_channel_videos(channel):
    """扫描频道的 videos 页面，返回视频列表"""
    url = f"https://www.youtube.com/@{channel}/videos"
    print(f"  请求页面: {url}")

    resp = fetch_page(url)
    if not resp or resp.status_code != 200:
        print(f"  [X] 页面获取失败 (状态码: {getattr(resp, 'status_code', 'N/A')})")
        return []

    data = extract_yt_initial_data(resp.text)
    if not data:
        print(f"  [X] 无法从页面提取视频数据 (ytInitialData 未找到)")
        return []

    videos = []

    try:
        tabs = (
            data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])
        )

        for tab in tabs:
            tab_renderer = tab.get("tabRenderer", {})
            content = tab_renderer.get("content", {})
            rich_grid = content.get("richGridRenderer", {})

            if not rich_grid:
                continue

            for item in rich_grid.get("contents", []):
                video_renderer = (
                    item.get("richItemRenderer", {})
                    .get("content", {})
                    .get("videoRenderer", {})
                )
                if not video_renderer:
                    continue

                video_id = video_renderer.get("videoId", "")
                title_runs = video_renderer.get("title", {}).get("runs", [])
                title = title_runs[0].get("text", "") if title_runs else ""

                duration = video_renderer.get("lengthText", {}).get("simpleText", "")
                views = video_renderer.get("viewCountText", {}).get("simpleText", "")
                pub_text = video_renderer.get("publishedTimeText", {}).get("simpleText", "")
                pub_date = parse_relative_date(pub_text) or ""

                if video_id and title:
                    videos.append({
                        "video_id": video_id,
                        "title": title,
                        "duration": duration,
                        "views": views,
                        "pub_date": pub_date,
                    })
    except Exception as e:
        print(f"  [X] 解析视频列表时出错: {e}")
        return []

    return videos


def download_video(video_id, title, youtuber, out_dir):
    """使用 yt-dlp 下载视频到指定目录"""
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:200]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_template = str(out_dir / safe_title)

    # 检查是否已存在
    for ext in [".mp4", ".mkv", ".webm"]:
        candidate = out_dir / f"{safe_title}{ext}"
        if candidate.exists():
            print(f"    ✅ 已存在: {candidate.name}")
            return str(candidate)

    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=web_embedded",
        "--js-runtimes", "node",
        "-f", "bv[ext=mp4]+140-16/bv[ext=mp4]+ba*",
        "--merge-output-format", "mp4",
        "-o", out_template,
    ]
    if PROXY:
        cmd.insert(1, "--proxy")
        cmd.insert(2, PROXY)
    cmd.append(url)

    print(f"    📥 下载: {title[:60]}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        downloaded = list(out_dir.glob(f"{safe_title}.*"))
        for f in downloaded:
            if f.suffix in (".mp4", ".mkv", ".webm"):
                print(f"    ✅ 下载完成: {f.name}")
                return str(f)

    print(f"    [X] 下载失败: {result.stderr[:200]}")
    return None


# ─── 主流程 ──────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="YouTube 频道监控下载")
    parser.add_argument("--dry-run", action="store_true", help="仅扫描不下载")
    parser.add_argument("--channel", help="只处理指定频道")
    parser.add_argument("--list", action="store_true", help="只列出已配置频道")
    parser.add_argument("--out-dir", default=str(Path.home() / "youtube-downloads"), help="下载目录")
    args = parser.parse_args()

    channels = get_channel_list()
    if not channels:
        print("⚠️ 频道列表为空，请编辑 youtuber_list.md 添加频道")
        sys.exit(1)

    print("=" * 50)
    print("  YouTube 频道监控 — 完整版")
    print("=" * 50)
    print(f"  频道: {', '.join(channels)}")
    print(f"  代理: {PROXY}")
    print(f"  下载目录: {args.out_dir}")
    print("")

    if args.list:
        print("已配置频道:")
        for ch in channels:
            print(f"  - {ch}")
        return

    # 检查 yt-dlp
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[X] yt-dlp 未安装。运行: pip install yt-dlp")
        sys.exit(1)

    # 初始化数据库
    conn = init_db()

    # 过滤指定频道
    if args.channel:
        channels = [c for c in channels if c == args.channel]
        if not channels:
            print(f"[X] 未找到频道: {args.channel}")
            sys.exit(1)

    # 扫描每个频道
    for channel in channels:
        print(f"\n{'='*50}")
        print(f"  📺 频道: @{channel}")
        print(f"{'='*50}")

        videos = scrape_channel_videos(channel)
        if not videos:
            print("  [i] 未找到视频或解析失败")
            continue

        print(f"  发现 {len(videos)} 个视频")
        print("")

        new_count = 0
        for v in videos:
            # 检查是否已下载
            if video_exists(conn, v["video_id"]):
                continue

            # 过滤中文标题
            if not has_chinese(v["title"]):
                print(f"  [skip] {v['title'][:50]}... (无中文标题)")
                continue

            # 是新视频且含中文
            new_count += 1
            is_new = insert_video(
                conn, channel, v["video_id"], v["title"],
                v["duration"], v["views"], v["pub_date"]
            )
            status = "[NEW]" if is_new else "[已知]"
            print(f"  {status} {v['title'][:60]}")

            if args.dry_run:
                continue

            # 下载
            file_path = download_video(v["video_id"], v["title"], channel, args.out_dir)
            if file_path:
                mark_downloaded(conn, v["video_id"], file_path)

        if new_count == 0:
            print("  [i] 没有新的中文标题视频")

        time.sleep(2)  # 避免请求过快

    conn.close()
    print("\n" + "=" * 50)
    print("  ✅ 扫描完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
