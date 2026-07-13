#!/usr/bin/env python3
"""
YouTube / Bilibili Transcript Fetcher — 跨平台一站式字幕获取
=============================================================

用法:
  python fetch_transcript.py <视频链接> [--lang LANG] [--output DIR] [--to-desktop]

示例:
  # YouTube
  python fetch_transcript.py https://www.youtube.com/watch?v=rOYlOdDgYUU
  python fetch_transcript.py https://youtu.be/rOYlOdDgYUU --lang zh-Hans

  # Bilibili
  python fetch_transcript.py https://www.bilibili.com/video/BV1GJ411x7j9

  # 输出到桌面
  python fetch_transcript.py https://youtu.be/xxx --to-desktop

  # 指定输出目录
  python fetch_transcript.py https://youtu.be/xxx --output ./my_videos

输出（输出目录）:
  - {video_id}_transcript.json      带时间戳的完整字幕 JSON
  - {video_id}_transcript.txt       纯文本（无时间戳，用于 AI 阅读）
  - {video_id}_timestamped.txt      带 [分:秒] 时间戳的文本
  - {video_id}_info.json            视频标题/时长等元数据

依赖:
  pip install youtube-transcript-api yt-dlp requests
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import textwrap
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

# ─── 依赖导入 ─────────────────────────────────


def _import_requests():
    try:
        import requests
        return requests
    except ImportError:
        print("[X] 缺少依赖：requests")
        print("   安装：pip install requests")
        sys.exit(1)


def _import_youtube_transcript_api():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        return YouTubeTranscriptApi
    except ImportError:
        return None


# ─── 平台 / 编码适配 ─────────────────────────


def ensure_utf8_stdio():
    """确保 stdout 输出 UTF-8（只在 Windows + 非重定向时包装）"""
    if platform.system() == "Windows" and hasattr(sys.stdout, "buffer"):
        sys.stdout = open(
            sys.stdout.buffer.fileno(),
            mode="w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
            closefd=False,
        )


def get_desktop_path() -> Path:
    """跨平台获取桌面路径"""
    home = Path.home()
    if platform.system() == "Windows":
        # Windows: 检查注册表语言环境下的 Desktop
        cand = [home / "Desktop", home / "OneDrive" / "Desktop",
                Path(os.environ.get("USERPROFILE", "")) / "Desktop"]
        for c in cand:
            if c.is_dir():
                return c
        return cand[0]  # 默认
    else:
        # macOS / Linux
        return home / "Desktop"


# ─── 视频 ID 提取 ────────────────────────────


def identify_platform(url: str) -> str:
    """识别视频平台: 'youtube', 'bilibili', 或 'unknown'"""
    url_lower = url.lower().strip()
    if any(d in url_lower for d in ["youtube.com", "youtu.be", "youtube.www"]):
        return "youtube"
    if any(d in url_lower for d in ["bilibili.com", "b23.tv"]):
        return "bilibili"
    # 纯 11 字符 YouTube ID
    if re.match(r"^[\w-]{11}$", url):
        return "youtube"
    # 纯 B站 BV/AV 号
    if re.match(r"^(BV[\w]{10}|av\d+)$", url, re.IGNORECASE):
        return "bilibili"
    return "unknown"


def extract_youtube_id(url: str) -> Optional[str]:
    """从 YouTube URL 中提取 video_id"""
    patterns = [
        r"youtube\.com/watch\?v=([\w-]+)",
        r"youtu\.be/([\w-]+)",
        r"youtube\.com/embed/([\w-]+)",
        r"youtube\.com/shorts/([\w-]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    # 直接传了纯净 ID
    if re.match(r"^[\w-]{11}$", url):
        return url
    return None


def extract_bilibili_id(url: str) -> Optional[str]:
    """从 B站 URL 提取 BV 号或 AV 号"""
    # BV 号: bilibili.com/video/BVxxxxxxxxxx
    m = re.search(r"bilibili\.com/video/(BV[\w]{10})", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # AV 号: bilibili.com/video/av123456
    m = re.search(r"bilibili\.com/video/(av\d+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # b23.tv 短链接
    m = re.search(r"b23\.tv/([\w]+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # 纯 BV/AV 号
    m = re.match(r"^(BV[\w]{10}|av\d+)$", url, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


# ─── 网络重试 ─────────────────────────────────


def _retry(fn, max_retries=3, base_delay=1.0, label=""):
    """简单指数退避重试"""
    last_exc = None
    prefix = f"[{label}] " if label else ""
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"{prefix}失败 (第{attempt}次)，{delay:.0f}秒后重试…", file=sys.stderr)
                time.sleep(delay)
            else:
                print(f"{prefix}重试 {max_retries} 次后仍然失败", file=sys.stderr)
    raise last_exc


# ─── 获取元数据 ───────────────────────────────


def fetch_video_info_youtube(video_id: str) -> dict:
    """通过 oEmbed 获取 YouTube 视频标题和作者"""
    requests = _import_requests()
    info = {"id": video_id, "title": "", "author": "", "duration_min": 0, "platform": "youtube"}
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        resp = _retry(
            lambda: requests.get(url, timeout=10),
            label="oEmbed"
        )
        if resp.ok:
            data = resp.json()
            info["title"] = data.get("title", "")
            info["author"] = data.get("author_name", "")
    except Exception as e:
        print(f"  [警告] 获取视频元数据失败：{e}")
    return info


def fetch_video_info_bilibili(video_id: str) -> dict:
    """通过 B站 API 获取视频标题和作者"""
    requests = _import_requests()
    info = {"id": video_id, "title": "", "author": "", "duration_min": 0, "platform": "bilibili"}

    # 统一转为 BV 号（API 更稳定）
    bvid = video_id
    if video_id.lower().startswith("av"):
        aid = video_id[2:] if video_id.lower().startswith("av") else video_id
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
            resp = _retry(lambda: requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0"
            }), label="B站API")
            if resp.ok:
                data = resp.json()
                if data.get("code") == 0:
                    vd = data["data"]
                    bvid = vd.get("bvid", bvid)
                    info["title"] = vd.get("title", "")
                    info["author"] = vd.get("owner", {}).get("name", "")
                    info["duration_min"] = round(vd.get("duration", 0) / 60, 1)
        except Exception as e:
            print(f"  [警告] B站 API 获取元数据失败：{e}")
    else:
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            resp = _retry(lambda: requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0"
            }), label="B站API")
            if resp.ok:
                data = resp.json()
                if data.get("code") == 0:
                    vd = data["data"]
                    info["title"] = vd.get("title", "")
                    info["author"] = vd.get("owner", {}).get("name", "")
                    info["duration_min"] = round(vd.get("duration", 0) / 60, 1)
        except Exception as e:
            print(f"  [警告] B站 API 获取元数据失败：{e}")

    info["id"] = bvid
    return info


# ─── 字幕获取（YouTube） ─────────────────────


def fetch_transcript_youtube_api(video_id: str, languages: list[str]) -> list[dict] | None:
    """用 youtube-transcript-api 获取字幕"""
    YouTubeTranscriptApi = _import_youtube_transcript_api()
    if YouTubeTranscriptApi is None:
        print("  [提示] youtube-transcript-api 未安装，跳过")
        return None

    api = YouTubeTranscriptApi()
    try:
        transcript = _retry(
            lambda: api.fetch(video_id, languages=languages),
            label="youtube-transcript-api"
        )
        return [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in transcript.snippets
        ]
    except Exception as e:
        print(f"  [X] youtube-transcript-api 获取失败：{e}")
        return None


def fetch_transcript_youtube_ytdlp(video_id: str) -> list[dict] | None:
    """用 yt-dlp 降级获取 YouTube 字幕（自动下载并解析）"""
    try:
        import yt_dlp
    except ImportError:
        print("  [提示] yt-dlp 未安装，无法降级")
        return None

    print("  [降级] 尝试 yt-dlp 获取字幕…")
    tmp_dir = Path(f".ytdlp_tmp_{video_id}")
    tmp_dir.mkdir(exist_ok=True)

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "zh-Hans", "zh", "a.en", "ja", "ko"],
            "skip_download": True,
            "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # 获取可用的字幕列表
            subtitles = info.get("subtitles", {}) or {}
            auto_subs = info.get("automatic_captions", {}) or {}
            all_subs = {**subtitles, **auto_subs}

            if not all_subs:
                print("  [降级] 无可用字幕")
                return None

            # 优先顺序：en -> zh-Hans -> zh -> 第一个可用
            lang_priority = ["en", "en-US", "en-GB", "zh-Hans", "zh", "zh-Hant", "ja", "ko"]
            chosen_lang = None
            for lang in lang_priority:
                if lang in all_subs:
                    chosen_lang = lang
                    break
            if not chosen_lang:
                chosen_lang = list(all_subs.keys())[0]

            # 下载所选语言字幕
            ydl_opts_sub = {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [chosen_lang],
                "subtitlesformat": "vtt",
                "skip_download": True,
                "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl2:
                ydl2.download([url])

            # 查找下载的字幕文件
            vtt_files = list(tmp_dir.glob(f"{video_id}*.vtt"))
            if not vtt_files:
                # 也可能是 .srt
                vtt_files = list(tmp_dir.glob(f"{video_id}*.srt"))
                if not vtt_files:
                    print("  [降级] 字幕文件未找到")
                    return None

            # 解析 VTT/SRT 到统一格式
            segments = _parse_vtt(vtt_files[0])
            if segments:
                print(f"  [降级] yt-dlp 成功 ({chosen_lang}, {len(segments)} 段)")
                return segments

    except Exception as e:
        print(f"  [降级] yt-dlp 失败：{e}")
    finally:
        # 清理临时文件
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return None


def _parse_vtt(path: Path) -> list[dict]:
    """解析 VTT 字幕文件为 [{text, start, duration}, ...]"""
    segments = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return segments

    lines = text.split("\n")
    pattern_time = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})")
    i = 0
    while i < len(lines):
        m = pattern_time.search(lines[i])
        if m:
            # 解析时间
            start_h, start_m, start_s, start_ms = (
                int(m.group(1)), int(m.group(2)),
                int(m.group(3)), int(m.group(4))
            )
            start_sec = start_h * 3600 + start_m * 60 + start_s + start_ms / 1000

            # 查找结束时间
            end_sec = start_sec + 3.0  # 默认 3s
            end_match = pattern_time.search(lines[i], m.end())
            if end_match:
                end_h, end_m, end_s, end_ms = (
                    int(end_match.group(1)), int(end_match.group(2)),
                    int(end_match.group(3)), int(end_match.group(4))
                )
                end_sec = end_h * 3600 + end_m * 60 + end_s + end_ms / 1000

            # 收集字幕文本（可能跨多行）
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not pattern_time.search(lines[i]):
                line = lines[i].strip()
                # 去除 VTT 内联标记
                line = re.sub(r"<[^>]+>", "", line)
                if line and not line.startswith("WEBVTT") and not line.startswith("Kind:") and not line.startswith("Language:"):
                    text_lines.append(line)
                i += 1

            if text_lines:
                combined = " ".join(text_lines)
                segments.append({
                    "text": combined,
                    "start": round(start_sec, 3),
                    "duration": round(end_sec - start_sec, 3),
                })
        else:
            i += 1

    return segments


# ─── 字幕获取（Bilibili） ────────────────────


def fetch_transcript_bilibili(video_id: str) -> list[dict] | None:
    """用 yt-dlp 获取 B站字幕（自动选择最佳可用字幕）"""
    try:
        import yt_dlp
    except ImportError:
        print("  [X] yt-dlp 未安装，无法获取 B站字幕")
        print("   安装：pip install yt-dlp")
        return None

    print("  [B站] 通过 yt-dlp 获取字幕…")
    url = f"https://www.bilibili.com/video/{video_id}"
    tmp_dir = Path(f".bili_tmp_{video_id}")
    tmp_dir.mkdir(exist_ok=True)

    try:
        # 第一步：探测可用字幕语言
        with yt_dlp.YoutubeDL({
            "quiet": True, "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True, "writeautomaticsub": True,
        }) as ydl:
            info = ydl.extract_info(url, download=False)
            available = set()
            for d in [info.get("subtitles", {}), info.get("automatic_captions", {})]:
                available.update(d.keys())

        if not available:
            print("  [B站] 视频无可用字幕（可能无CC字幕）")
            return None

        # 选择最佳语言
        lang = None
        for pref in ["zh-Hans", "zh", "zh-CN", "en", "ja"]:
            if pref in available:
                lang = pref
                break
        if not lang:
            lang = list(available)[0]

        # 第二步：下载所选字幕
        ydl_opts = {
            "quiet": True, "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # 查找字幕文件
        sub_files = list(tmp_dir.glob("*.vtt")) or list(tmp_dir.glob("*.srt")) or list(tmp_dir.glob("*.ass"))
        if not sub_files:
            # yt-dlp 可能内嵌字幕，尝试提取
            print("  [B站] 字幕文件未找到，尝试提取内嵌字幕…")
            return None

        segments = _parse_vtt(sub_files[0])
        if segments:
            print(f"  [B站] 成功 ({lang}, {len(segments)} 段)")
            return segments

    except Exception as e:
        print(f"  [B站] yt-dlp 获取失败：{e}")
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return None


# ─── 保存输出 ─────────────────────────────────


def format_time(seconds: float) -> str:
    """秒 → 可读时间"""
    td = timedelta(seconds=int(seconds))
    parts = str(td).split(":")
    if len(parts) == 3 and parts[0] == "0":
        return f"{int(parts[1])}:{parts[2]}"
    return str(td)


def save_outputs(data: list[dict], info: dict, output_dir: str, video_id: str):
    """保存四种格式的字幕文件"""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    base = out_path / video_id

    # 1. JSON（完整结构）
    json_path = base.with_name(f"{video_id}_transcript.json")
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"  [OK] JSON: {json_path}")

    # 2. 纯文本（每句话空格分隔，适合 AI 阅读）
    txt_path = base.with_name(f"{video_id}_transcript.txt")
    full_text = " ".join(seg["text"] for seg in data)
    txt_path.write_text(full_text, encoding="utf-8")
    print(f"  [OK] TXT: {txt_path}  ({len(full_text)} 字符)")

    # 3. 带时间戳的文本（适合人工查阅）
    ts_path = base.with_name(f"{video_id}_timestamped.txt")
    lines = []
    for seg in data:
        mins = int(seg["start"] // 60)
        secs = int(seg["start"] % 60)
        lines.append(f"[{mins}:{secs:02d}] {seg['text']}")
    ts_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [OK] 时间戳: {ts_path}  ({len(data)} 段)")

    # 4. 视频信息
    info_path = base.with_name(f"{video_id}_info.json")
    info_path.write_text(
        json.dumps(info, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"  [OK] 元数据: {info_path}")

    return str(json_path), str(txt_path)


# ─── 打印摘要 ─────────────────────────────────


def print_summary(data: list[dict], info: dict):
    """打印摘要信息给用户/AI"""
    total_sec = data[-1]["start"] + data[-1]["duration"] if data else 0
    total_min = total_sec / 60
    total_words = sum(len(s["text"].split()) for s in data)
    total_chars = sum(len(s["text"]) for s in data)

    print()
    print("=" * 52)
    print("  📺 字幕获取完成")
    print("=" * 52)
    print(f"  平台：{info.get('platform', 'unknown')}")
    print(f"  标题：{info.get('title', '未知')}")
    print(f"  频道：{info.get('author', '未知')}")
    print(f"  时长：{total_min:.1f} 分钟 ({format_time(total_sec)})")
    print(f"  片段：{len(data)} 段")
    if info.get("platform") == "youtube":
        print(f"  单词：{total_words:,}")
    print(f"  字符：{total_chars:,}")
    print(f"  预估主题数：{max(1, round(total_min / 15))}~{max(1, round(total_min / 10))} 个")
    print("=" * 52)
    print()


# ─── CLI ─────────────────────────────────


def build_parser():
    parser = argparse.ArgumentParser(
        description="YouTube / Bilibili 字幕获取工具（跨平台）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例：
              # YouTube
              python fetch_transcript.py https://www.youtube.com/watch?v=xxxxx
              python fetch_transcript.py https://youtu.be/xxxxx --output ./data
              python fetch_transcript.py xxxxxxxxxxx --lang en zh-Hans

              # Bilibili
              python fetch_transcript.py https://www.bilibili.com/video/BVxxxxxxxxxx
              python fetch_transcript.py BVxxxxxxxxxx

              # 交付到桌面
              python fetch_transcript.py https://youtu.be/xxxxx --to-desktop

              # 指定语言 + 重试
              python fetch_transcript.py <URL> --lang ja ko --retry 5
        """),
    )
    parser.add_argument("url", help="视频链接或 ID（YouTube / Bilibili）")
    parser.add_argument("--lang", nargs="+",
                        default=["en", "a.en", "en-US", "en-GB", "zh-Hans", "zh-Hant"],
                        help="语言优先级（默认：英文优先，中文备选）")
    parser.add_argument("--output", "-o", default=".",
                        help="输出目录（默认：当前目录）")
    parser.add_argument("--to-desktop", action="store_true",
                        help="输出到桌面（自动检测操作系统）")
    parser.add_argument("--retry", type=int, default=3,
                        help="网络请求重试次数（默认：3）")
    parser.add_argument("--ytdlp-first", action="store_true",
                        help="优先使用 yt-dlp 而非 youtube-transcript-api")
    return parser


def main():
    ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()

    # ── 0. 确定目标目录 ──
    output_dir = args.output
    if args.to_desktop:
        desktop = get_desktop_path()
        print(f"\n[桌面] 输出到桌面：{desktop}")
        output_dir = str(desktop)

    # ── 1. 识别平台 ──
    platform_type = identify_platform(args.url)
    if platform_type == "unknown":
        print(f"[X] 无法识别的链接：{args.url}")
        print("  支持的平台：YouTube（youtube.com / youtu.be）、Bilibili（bilibili.com）")
        sys.exit(1)
    print(f"\n[平台] {platform_type}")

    # ── 2. 提取 ID ──
    video_id = None
    if platform_type == "youtube":
        video_id = extract_youtube_id(args.url)
    else:
        video_id = extract_bilibili_id(args.url)

    if not video_id:
        print(f"[X] 无法从 '{args.url}' 提取视频 ID")
        sys.exit(1)
    print(f"[ID]   {video_id}")

    # ── 3. 获取元数据 ──
    print("[Info] 获取视频信息...")
    info = {}
    if platform_type == "youtube":
        info = fetch_video_info_youtube(video_id)
    else:
        info = fetch_video_info_bilibili(video_id)

    # ── 4. 获取字幕 ──
    data = None
    if platform_type == "youtube":
        print("[Sub] 下载字幕（YouTube）...")
        if not args.ytdlp_first:
            # 优先 youtube-transcript-api
            data = fetch_transcript_youtube_api(video_id, args.lang)
            if not data:
                data = fetch_transcript_youtube_ytdlp(video_id)
        else:
            # 优先 yt-dlp
            data = fetch_transcript_youtube_ytdlp(video_id)
            if not data:
                data = fetch_transcript_youtube_api(video_id, args.lang)
    else:
        print("[Sub] 下载字幕（Bilibili）...")
        data = fetch_transcript_bilibili(video_id)

    if not data:
        print("\n[Warn] 字幕获取失败，可能原因：")
        if platform_type == "youtube":
            print("   • 视频没有字幕")
            print("   • 视频受年龄/地区限制")
            print("   • 网络问题")
            print("\n[Hint] 尝试：")
            print("   • 指定其他语言：--lang ja ko")
            print("   • 用 yt-dlp 模式：--ytdlp-first")
            print("   • 安装 yt-dlp：pip install yt-dlp")
        else:
            print("   • 视频没有CC字幕")
            print("   • 视频已下架/锁定")
            print("\n[Hint] 尝试：")
            print("   • 确认链接可用")
            print("   • 安装最新 yt-dlp：pip install -U yt-dlp")
        sys.exit(1)

    # ── 5. 计算时长 ──
    total_sec = data[-1]["start"] + data[-1]["duration"]
    info["duration_min"] = round(total_sec / 60, 1)
    info["segment_count"] = len(data)

    # ── 6. 保存文件 ──
    print("[Save] 保存文件...")
    json_path, txt_path = save_outputs(data, info, output_dir, video_id)

    # ── 7. 打印摘要 ──
    print_summary(data, info)

    # ── 8. 交付路径 ──
    print("[Path] AI 后续处理的文件路径：")
    print(f"   JSON: {json_path}")
    print(f"   TXT:  {txt_path}")
    print()


if __name__ == "__main__":
    main()
