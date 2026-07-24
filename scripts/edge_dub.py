#!/usr/bin/env python3
"""
edge_dub.py — 基于 edge-tts 的中文配音生成器
================================================

用法:
  python scripts/edge_dub.py bilingual_transcript.json --out dub.wav
  python scripts/edge_dub.py bilingual_transcript.json --out dub.wav \
      --voice zh-CN-YunxiNeural --concurrency 8 --total-duration 3436

流程:
  1. 逐段调用 edge-tts 合成 mp3（异步并发，默认 8 路），
     中间结果缓存到 <out 同级>/tts_cache/seg_XXXXX.mp3 —— 已存在即跳过（断点续传）。
  2. 探测每段 TTS 时长；若 TTS 时长 > 原字幕段时长 × 1.35，
     用 ffmpeg atempo 加速（上限 1.35x），其余按原样转为 44.1kHz 单声道 wav。
  3. 按原 start 时间戳把各段放到静音底轨上（adelay + amix，分块混合），
     输出完整配音音轨（默认 44.1kHz 单声道 wav）。

依赖:
  pip install edge-tts imageio-ffmpeg
  （ffmpeg 二进制来自 PATH 或 imageio-ffmpeg）
"""

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CHUNK = 120          # amix 每块最大段数
DEFAULT_VOICE = "zh-CN-YunxiNeural"
MAX_TEMPO = 1.35


# ─── ffmpeg 发现 ──────────────────────────────

def find_ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        print("[X] 找不到 ffmpeg（PATH 与 imageio-ffmpeg 都没有）")
        sys.exit(1)


def probe_duration(ffmpeg: str, path: Path) -> float:
    """解析 ffmpeg -i 输出里的 Duration，返回秒"""
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out.stderr)
    if not m:
        return 0.0
    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + s


# ─── Step 1: TTS 合成（异步并发 + 断点续传）────

async def synth_all(segments: list[dict], cache: Path, voice: str,
                    concurrency: int, rate: str):
    import edge_tts
    sem = asyncio.Semaphore(concurrency)
    done = 0
    lock = asyncio.Lock()

    async def one(i: int, text: str):
        nonlocal done
        out = cache / f"seg_{i:05d}.mp3"
        if out.exists() and out.stat().st_size > 500:
            async with lock:
                done += 1
            return
        async with sem:
            for attempt in range(4):
                try:
                    comm = edge_tts.Communicate(text, voice, rate=rate)
                    await comm.save(str(out))
                    break
                except Exception as e:
                    if attempt == 3:
                        print(f"\n[警告] 段 {i} 合成失败（跳过）: {e}")
                    await asyncio.sleep(2 * (attempt + 1))
        async with lock:
            done += 1
            if done % 50 == 0:
                print(f"  [TTS] {done}/{len(segments)}", flush=True)

    await asyncio.gather(*(one(i, s["text_zh"]) for i, s in enumerate(segments)))


# ─── Step 2: 转 wav（按需 atempo 加速）──────────

def convert_one(ffmpeg: str, cache: Path, i: int, orig_dur: float,
                total: int) -> Path | None:
    mp3 = cache / f"seg_{i:05d}.mp3"
    wav = cache / f"seg_{i:05d}.wav"
    if wav.exists() and wav.stat().st_size > 100:
        return wav
    if not mp3.exists() or mp3.stat().st_size <= 500:
        return None
    tts_dur = probe_duration(ffmpeg, mp3)
    af = []
    if tts_dur > 0 and orig_dur > 0.2 and tts_dur > orig_dur * MAX_TEMPO:
        tempo = min(tts_dur / orig_dur, MAX_TEMPO)
        af = ["-af", f"atempo={tempo:.3f}"]
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(mp3), *af,
                    "-ar", "44100", "-ac", "1", str(wav)],
                   capture_output=True)
    return wav if wav.exists() else None


# ─── Step 3: 分块混合到静音底轨 ────────────────

def mix_all(ffmpeg: str, items: list[tuple[int, float]], cache: Path,
            total: float, out_path: Path):
    """items: [(seg_index, start_sec)]，分块 amix 后再整体混合"""
    chunk_wavs: list[Path] = []
    chunks = [items[k:k + CHUNK] for k in range(0, len(items), CHUNK)]
    for ci, chunk in enumerate(chunks):
        cw = cache / f"mix_{ci:03d}.wav"
        if not cw.exists():
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono"]
            for idx, _ in chunk:
                cmd += ["-i", str(cache / f"seg_{idx:05d}.wav")]
            parts = [f"[0:a]atrim=0:{total + 1:.3f}[base]"]
            labels = ["base"]
            for n, (idx, start) in enumerate(chunk, 1):
                ms = int(round(start * 1000))
                parts.append(f"[{n}:a]adelay={ms}|{ms}[d{n}]")
                labels.append(f"d{n}")
            parts.append(
                f"[{']['.join(labels)}]amix=inputs={len(labels)}:normalize=0:dropout_transition=0[a]")
            cmd += ["-filter_complex", ";".join(parts),
                    "-map", "[a]", "-ar", "44100", "-ac", "1", "-t", f"{total + 1:.3f}",
                    str(cw)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"[X] 混合块 {ci} 失败:\n{r.stderr[-2000:]}")
                sys.exit(1)
        chunk_wavs.append(cw)
        print(f"  [混合] 块 {ci + 1}/{len(chunks)} 完成", flush=True)

    if len(chunk_wavs) == 1:
        shutil.copy2(chunk_wavs[0], out_path)
        return
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for cw in chunk_wavs:
        cmd += ["-i", str(cw)]
    labels = "".join(f"[{n}:a]" for n in range(len(chunk_wavs)))
    cmd += ["-filter_complex",
            f"{labels}amix=inputs={len(chunk_wavs)}:normalize=0[a]",
            "-map", "[a]", "-ar", "44100", "-ac", "1", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[X] 最终混合失败:\n{r.stderr[-2000:]}")
        sys.exit(1)


# ─── CLI ──────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="edge-tts 中文配音生成器（断点续传）")
    ap.add_argument("transcript", help="带 text_zh 的 transcript JSON")
    ap.add_argument("--out", "-o", required=True, help="输出音轨路径（建议 .wav）")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"edge-tts 语音（默认 {DEFAULT_VOICE}）")
    ap.add_argument("--rate", default="+0%", help="语速，如 +10%% / -5%%")
    ap.add_argument("--concurrency", type=int, default=8, help="TTS 并发数（默认 8）")
    ap.add_argument("--total-duration", type=float, default=0.0,
                    help="音轨总时长（秒），默认取最后一段结束时间 + 2s")
    ap.add_argument("--cache-dir", default=None, help="TTS 缓存目录（默认 <out 目录>/tts_cache）")
    args = ap.parse_args()

    data = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("segments", data.get("transcript", []))
    segments = []
    for s in data:
        zh = str(s.get("text_zh", "") or "").strip()
        if not zh:
            continue
        start = float(s.get("start", 0))
        dur = float(s.get("duration", 0) or 0)
        if dur <= 0.2:
            dur = 2.0
        segments.append({"start": start, "duration": dur, "text_zh": zh})
    print(f"[配音] {len(segments)} 个中文段落")

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir).resolve() if args.cache_dir else out_path.parent / "tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    print(f"[ffmpeg] {ffmpeg}")

    total = args.total_duration
    if total <= 0:
        total = max(s["start"] + s["duration"] for s in segments) + 2.0

    print(f"[TTS] 语音 {args.voice} 并发 {args.concurrency} → {cache}")
    asyncio.run(synth_all(segments, cache, args.voice, args.concurrency, args.rate))
    ok = sum(1 for i in range(len(segments))
             if (cache / f"seg_{i:05d}.mp3").exists())
    print(f"[TTS] 完成 {ok}/{len(segments)}")

    print("[转换] 转 44.1k 单声道 wav（必要时 atempo ≤1.35x）")
    items: list[tuple[int, float]] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(
            lambda t: convert_one(ffmpeg, cache, t[0], t[1]["duration"], len(segments)),
            enumerate(segments)))
    for i, wav in enumerate(results):
        if wav:
            items.append((i, segments[i]["start"]))
    print(f"[转换] 可用段 {len(items)}/{len(segments)}")

    print(f"[混合] 输出 {out_path}（总长 {total:.1f}s）")
    mix_all(ffmpeg, items, cache, total, out_path)
    dur = probe_duration(ffmpeg, out_path)
    print(f"[完成] {out_path}  时长 {dur:.1f}s")


if __name__ == "__main__":
    main()
