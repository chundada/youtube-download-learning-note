#!/usr/bin/env python3
"""
compose_chunked.py — compose_video.py 的分块编码包装器
========================================================

长视频（如 57 分钟）一次编码容易超出单次调用时限，
本脚本把成片切成 N 块分别编码（每块 < 单块时限），
再用 concat demuxer 无损拼接为最终 mp4。

用法:
  python compose_chunked.py --video source.mp4 --audio dub.wav \
      --chapters chapters.json --cards-dir cards/ --ass bilingual.ass \
      --out final.mp4 --chunk 140 --work-dir _run_xxx/chunks

关键点:
  - 输入用 -ss A -to B 快速定位，-copyts 保留绝对时间戳，
    因此卡片 overlay 的 between(t,start,end) 与 subtitles 的
    绝对时间轴在每一块内仍然正确。
  - 每块已存在且大小 >1MB 即跳过（断点续传）。
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compose_video import (  # noqa: E402
    build_filter_complex, find_ffmpeg, has_subtitles_filter,
    print_subtitles_fallback,
)


def probe_duration(ffmpeg: str, path: Path) -> float:
    import re
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out.stderr)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def main():
    ap = argparse.ArgumentParser(description="分块编码合成（compose_video 的长视频包装器）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--chapters", required=True)
    ap.add_argument("--cards-dir", required=True)
    ap.add_argument("--ass", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--crf", type=int, default=23)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--chunk", type=float, default=140.0, help="每块秒数（默认 140）")
    ap.add_argument("--work-dir", required=True, help="分块中间产物目录")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    audio = Path(args.audio).resolve()
    work = Path(args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    ass_work = work / "bilingual_work.ass"
    shutil.copy2(args.ass, ass_work)

    chapters = json.loads(Path(args.chapters).read_text(encoding="utf-8"))
    chapters = sorted(chapters, key=lambda c: float(c.get("start", 0)))
    cards = sorted(Path(args.cards_dir).glob("card_*.png"))[: len(chapters)]
    W, H = (int(x) for x in args.size.lower().split("x"))

    ffmpeg = find_ffmpeg()
    if not ffmpeg or not has_subtitles_filter(ffmpeg):
        print_subtitles_fallback()
        sys.exit(1)
    print(f"[ffmpeg] {ffmpeg}")

    total = min(probe_duration(ffmpeg, video), probe_duration(ffmpeg, audio))
    print(f"[分块] 总时长 {total:.1f}s，每块 {args.chunk:.0f}s")

    bounds = []
    t = 0.0
    while t < total - 0.5:
        bounds.append((t, min(t + args.chunk, total)))
        t += args.chunk
    print(f"[分块] 共 {len(bounds)} 块")

    fc = build_filter_complex(chapters, len(cards), (W, H), ass_work.name)
    chunk_files = []
    for ci, (a, b) in enumerate(bounds):
        cf = work / f"chunk_{ci:03d}.mp4"
        chunk_files.append(cf)
        if cf.exists() and cf.stat().st_size > 1_000_000:
            print(f"  [跳过] chunk_{ci:03d} 已完成")
            continue
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-copyts", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(video),
               "-copyts", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(audio)]
        for card in cards:
            cmd += ["-i", str(card.resolve())]
        cmd += ["-filter_complex", fc,
                "-map", "[vout]", "-map", "1:a",
                "-c:v", "libx264", "-crf", str(args.crf), "-preset", "medium",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                str(cf)]
        r = subprocess.run(cmd, cwd=str(work), capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[X] chunk_{ci:03d} 编码失败:\n{r.stderr[-3000:]}")
            sys.exit(1)
        print(f"  [完成] chunk_{ci:03d}  [{a:.0f}s - {b:.0f}s]", flush=True)

    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{cf.name}'\n" for cf in chunk_files), encoding="utf-8")
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", lst.name,
           "-c", "copy", "-movflags", "+faststart", str(out_path)]
    r = subprocess.run(cmd, cwd=str(work), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[X] 拼接失败:\n{r.stderr[-2000:]}")
        sys.exit(1)
    dur = probe_duration(ffmpeg, out_path)
    mb = out_path.stat().st_size / 1024 / 1024
    print(f"[完成] {out_path}  时长 {dur:.1f}s  {mb:.1f} MB")


if __name__ == "__main__":
    main()
