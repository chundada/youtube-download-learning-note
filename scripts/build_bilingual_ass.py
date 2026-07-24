#!/usr/bin/env python3
"""
双语 ASS 字幕生成器 — transcript JSON → 顶部英文 + 底部中文 双语字幕
======================================================================

用法:
  python build_bilingual_ass.py transcript.json --out bilingual.ass

输入（兼容 fetch_transcript.py 产出的 schema）:
  [
    {"text": "English sentence", "start": 0.0, "duration": 3.2, "text_zh": "中文翻译"},
    ...
  ]
  - 也兼容 {"segments": [...]} 包装形式
  - segment 有 "end" 字段时优先用 end，否则用 start + duration
  - "text_zh" 由 AI 在 Phase 2.5 翻译时填入；没有 text_zh 的段落
    默认不生成底部中文字幕行（可用 --zh-fallback en 改为复用英文）

输出:
  bilingual.ass — PlayRes 1920x1080，两条样式：
    EnTop    顶部英文小字（Alignment=8，白色，字号 36）
    ZhBottom 底部中文大字（Alignment=2，白色加粗、黑色描边，字号 64）

依赖: 仅标准库
"""

import argparse
import json
import platform
import sys
from pathlib import Path

# ─── ASS 模板常量 ─────────────────────────────

ASS_HEADER = """[Script Info]
Title: Bilingual Subtitles (En top / Zh bottom)
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: EnTop,Microsoft YaHei,36,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,1.6,0.4,8,40,40,40,1
Style: ZhBottom,Microsoft YaHei,64,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1.2,2,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ensure_utf8_stdio():
    """确保 stdout 输出 UTF-8（只在 Windows + 非重定向时包装）"""
    if platform.system() == "Windows" and hasattr(sys.stdout, "buffer"):
        sys.stdout = open(
            sys.stdout.buffer.fileno(),
            mode="w", encoding="utf-8", errors="replace",
            buffering=1, closefd=False,
        )


# ─── 输入解析 ─────────────────────────────────


def load_segments(path: Path) -> list[dict]:
    """读取 transcript JSON，兼容列表或 {'segments': [...]} 包装"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("segments", "transcript", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list) or not data:
        print("[X] transcript JSON 应为非空片段列表")
        sys.exit(1)
    return data


def seg_start_end(seg: dict) -> tuple[float, float] | None:
    """取片段的 (start, end)；信息不足时返回 None"""
    try:
        start = float(seg.get("start", 0))
    except (TypeError, ValueError):
        return None
    if seg.get("end") is not None:
        end = float(seg["end"])
    else:
        end = start + float(seg.get("duration", 0) or 0)
    if end <= start:
        end = start + 1.5  # 兜底：至少显示 1.5 秒
    return start, end


# ─── ASS 文本处理 ─────────────────────────────


def ass_time(sec: float) -> str:
    """秒 → ASS 时间格式 H:MM:SS.cc（厘秒）"""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs == 100:  # 进位
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    """清理 ASS 正文：换行转空格，花括号转全角避免被当作特效标签"""
    t = " ".join(str(text).split())
    return t.replace("{", "｛").replace("}", "｝").strip()


def dialogue(start: float, end: float, style: str, text: str) -> str:
    return f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{ass_escape(text)}"


# ─── CLI ─────────────────────────────────


def main():
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="双语 ASS 字幕生成器（顶部英文 + 底部中文）",
        epilog="示例：python build_bilingual_ass.py transcript.json --out bilingual.ass",
    )
    parser.add_argument("transcript", help="transcript JSON 路径（可含 text_zh 字段）")
    parser.add_argument("--out", "-o", default="bilingual.ass", help="输出 ASS 路径（默认：bilingual.ass）")
    parser.add_argument("--zh-fallback", choices=["empty", "en"], default="empty",
                        help="无 text_zh 时：empty=不出中文字幕行（默认）；en=底部复用英文")
    args = parser.parse_args()

    src = Path(args.transcript)
    if not src.is_file():
        print(f"[X] 找不到字幕文件：{src}")
        sys.exit(1)

    segments = load_segments(src)
    events: list[str] = []
    zh_missing = 0

    for seg in segments:
        rng = seg_start_end(seg)
        if rng is None:
            continue
        start, end = rng
        en = str(seg.get("text", "") or "").strip()
        zh = str(seg.get("text_zh", "") or "").strip()

        if en:
            events.append(dialogue(start, end, "EnTop", en))
        if zh:
            events.append(dialogue(start, end, "ZhBottom", zh))
        elif args.zh_fallback == "en" and en:
            events.append(dialogue(start, end, "ZhBottom", en))
        else:
            zh_missing += 1

    if not events:
        print("[X] 没有可用的字幕片段")
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ASS 用 UTF-8（无 BOM 也能被 libass 识别，但加 BOM 更保险）
    out_path.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8-sig")

    print(f"[OK] {out_path}  ({len(events)} 行字幕事件，{len(segments)} 个片段)")
    if zh_missing:
        print(f"  [提示] {zh_missing} 个片段没有 text_zh，这些时间段底部无中文字幕")


if __name__ == "__main__":
    main()
