#!/usr/bin/env python3
"""
最终合成器 — 压暗模糊背景 + 章节总结卡片 + 双语烧录字幕 + 配音音轨
====================================================================

用法:
  python compose_video.py --video in.mp4 --audio dub.mp3 \
      --chapters chapters.json --cards-dir cards/ --ass bilingual.ass \
      --out final.mp4 [--crf 23]

处理链:
  画面: 原视频缩放铺满 1920x1080 → boxblur 模糊 + eq 压暗当背景
        → 按 chapters.json 每章时间段 overlay 对应 card_XXX.png
        → subtitles 烧录双语字幕（顶部英文 + 底部中文）
  音频: 用配音音轨替换原音（-map 配音输入，-shortest 截齐）

ffmpeg 发现顺序:
  PATH 中的 ffmpeg → imageio-ffmpeg 自带二进制
  （要求编译带 libass；脚本会先探测 subtitles filter 是否可用，
    不可用时给出降级方案说明并以非零码退出）

依赖:
  pip install imageio-ffmpeg   （PATH 无 ffmpeg 时兜底）
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_SIZE = (1920, 1080)


def ensure_utf8_stdio():
    """确保 stdout 输出 UTF-8（只在 Windows + 非重定向时包装）"""
    if platform.system() == "Windows" and hasattr(sys.stdout, "buffer"):
        sys.stdout = open(
            sys.stdout.buffer.fileno(),
            mode="w", encoding="utf-8", errors="replace",
            buffering=1, closefd=False,
        )


# ─── ffmpeg 发现与能力探测 ────────────────────


def find_ffmpeg() -> str | None:
    """ffmpeg 发现顺序：PATH → imageio-ffmpeg 自带二进制"""
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def has_subtitles_filter(ffmpeg: str) -> bool:
    """探测该 ffmpeg 是否编译了 libass（subtitles filter）"""
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        )
        return " subtitles " in (out.stdout + out.stderr)
    except Exception:
        return False


def print_subtitles_fallback():
    """subtitles filter 不可用时的降级方案说明"""
    print("[X] 当前 ffmpeg 不支持 subtitles filter（缺少 libass）")
    print("   降级方案（任选其一）：")
    print("   1. 安装完整版 ffmpeg（gyan.dev full build / brew install ffmpeg），")
    print("      或 pip install imageio-ffmpeg 用其自带二进制（通常带 libass）")
    print("   2. 跳过烧录：输出不带字幕的视频，字幕 ASS 文件随包交付由播放器外挂加载")
    print("   3. 用 drawtext 逐条写字幕（不支持双语排版，不推荐）")
    print("   4. 把字幕渲染成 PNG 序列再 overlay（工作量大，仅作最后手段）")


# ─── 滤镜链构建 ───────────────────────────────


def build_filter_complex(chapters: list[dict], n_cards: int,
                         size: tuple[int, int], ass_name: str) -> str:
    """构建 filter_complex：压暗模糊背景 → 按时间段叠加卡片 → 烧录字幕"""
    W, H = size
    parts = [
        # 背景：缩放铺满 + 裁剪 + 模糊 + 压暗
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},boxblur=8:2,eq=brightness=-0.25[bg]"
    ]
    cur = "bg"
    for i in range(n_cards):
        ch = chapters[i]
        start = float(ch.get("start", 0))
        end = float(ch.get("end", 0))
        nxt = f"v{i}"
        # 卡片 PNG 为整幅透明画布，直接 0:0 叠加，enable 按章节时间段生效
        parts.append(
            f"[{cur}][{i + 2}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[{nxt}]"
        )
        cur = nxt
    # 烧录双语字幕（ass 文件已复制到工作目录，用纯文件名规避 Windows 路径转义问题）
    parts.append(f"[{cur}]subtitles={ass_name}[vout]")
    return ";".join(parts)


# ─── CLI ─────────────────────────────────


def main():
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="最终合成：压暗模糊背景 + 章节总结卡片 + 双语烧录字幕 + 配音音轨",
        epilog="示例：python compose_video.py --video in.mp4 --audio dub.mp3 "
               "--chapters chapters.json --cards-dir cards/ --ass bilingual.ass --out final.mp4",
    )
    parser.add_argument("--video", required=True, help="原始视频路径")
    parser.add_argument("--audio", required=True, help="配音音频路径（mp3/wav/m4a）")
    parser.add_argument("--chapters", required=True, help="chapters.json 路径")
    parser.add_argument("--cards-dir", required=True, help="卡片 PNG 目录（card_001.png …）")
    parser.add_argument("--ass", required=True, help="双语 ASS 字幕路径")
    parser.add_argument("--out", required=True, help="输出视频路径")
    parser.add_argument("--crf", type=int, default=23, help="x264 CRF（默认：23）")
    parser.add_argument("--size", default="1920x1080", help="输出尺寸（默认：1920x1080）")
    args = parser.parse_args()

    # ── 输入检查 ──
    for label, p in [("--video", args.video), ("--audio", args.audio),
                     ("--chapters", args.chapters), ("--ass", args.ass)]:
        if not Path(p).is_file():
            print(f"[X] 找不到文件 {label}: {p}")
            sys.exit(1)
    cards_dir = Path(args.cards_dir)
    if not cards_dir.is_dir():
        print(f"[X] 找不到卡片目录：{cards_dir}")
        sys.exit(1)

    chapters = json.loads(Path(args.chapters).read_text(encoding="utf-8"))
    chapters = sorted(chapters, key=lambda c: float(c.get("start", 0)))

    cards = sorted(cards_dir.glob("card_*.png"))
    if len(cards) < len(chapters):
        print(f"[X] 卡片数量不足：{len(cards)} 张 < {len(chapters)} 章（请先运行 render_cards.py）")
        sys.exit(1)
    cards = cards[: len(chapters)]

    try:
        W, H = (int(x) for x in args.size.lower().split("x"))
    except Exception:
        print(f"[X] 无法解析尺寸：{args.size}")
        sys.exit(1)

    # ── ffmpeg 探测 ──
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("[X] 找不到 ffmpeg：PATH 中没有，imageio-ffmpeg 也未安装")
        print("   安装：pip install imageio-ffmpeg 或 winget install ffmpeg")
        sys.exit(1)
    print(f"[ffmpeg] {ffmpeg}")

    if not has_subtitles_filter(ffmpeg):
        print_subtitles_fallback()
        sys.exit(1)

    # ── 组装命令 ──
    # ass 复制到临时工作目录，ffmpeg 在该目录运行，滤镜里用纯文件名，
    # 彻底规避 Windows 下盘符冒号与反斜杠的转义问题
    with tempfile.TemporaryDirectory(prefix="yt_compose_") as tmp:
        tmp_dir = Path(tmp)
        ass_name = "bilingual_work.ass"
        shutil.copy2(args.ass, tmp_dir / ass_name)

        cmd = [ffmpeg, "-y", "-hide_banner"]
        cmd += ["-i", str(Path(args.video).resolve())]   # 输入 0：原视频
        cmd += ["-i", str(Path(args.audio).resolve())]   # 输入 1：配音音频
        for card in cards:                               # 输入 2..N：卡片 PNG
            # 单帧输入即可：overlay 默认 repeatlast=1 会保持最后一帧，
            # 切勿加 -loop 1（无限帧流会导致 framesync 缓冲膨胀报 ENOMEM）
            cmd += ["-i", str(card.resolve())]

        fc = build_filter_complex(chapters, len(cards), (W, H), ass_name)
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cmd += [
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-crf", str(args.crf), "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]

        print(f"[合成] {len(chapters)} 章卡片 + 双语字幕 + 配音音轨 → {out_path}")
        proc = subprocess.run(cmd, cwd=str(tmp_dir))
        if proc.returncode != 0:
            print(f"[X] ffmpeg 合成失败（退出码 {proc.returncode}）")
            print("   可打印完整命令排查：")
            print("   " + " ".join(cmd))
            sys.exit(proc.returncode)

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"[完成] {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
