#!/usr/bin/env python3
"""
AI 配音核心处理脚本 (ai_dub_core.py)
将视频/音频转录为文本，用 Edge TTS 生成中文语音，合并到视频。

跨平台支持：Windows / macOS / Linux

支持两种模式：
1. 直接模式：提供已翻译的中文文本文件
2. 转录模式：从视频提取音频 → Whisper 转录 → 保存文本（需手动翻译后重跑）

完整工作流程：
  视频文件 → 提取音频 → faster-whisper 转录 → 保存英文文本
  → 用户翻译为中文 → 重新运行本脚本（--text translated.txt）
  → Edge TTS 分段合成 → ffmpeg 合并 → _zh_dubbed.mp4

依赖：
  pip install faster-whisper edge-tts
  ffmpeg 必须已安装
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ─── 工具函数 ──────────────────────────────────────


def run_cmd(cmd, cwd=None, check=True):
    """运行命令，返回 subprocess.CompletedProcess 或 None"""
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and r.returncode != 0:
        print(f"  [X] 命令失败: {' '.join(cmd[:6])}...")
        if r.stderr:
            print(f"      {r.stderr[:300]}")
        return None
    return r


def check_cmd(name):
    """检查命令是否可用（跨平台：Windows 用 where，其他用 which）"""
    cmd = ["where", name] if os.name == "nt" else ["which", name]
    return run_cmd(cmd, check=False) is not None


def extract_audio(video_path, output_wav):
    """提取音频为 16kHz mono wav"""
    r = run_cmd([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(output_wav)
    ])
    return r is not None and Path(output_wav).exists()


def transcribe_with_whisper(audio_path, model_size="base", language="en"):
    """使用 faster-whisper 转录音频"""
    try:
        from faster_whisper import WhisperModel
        print("  加载 Whisper 模型...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), language=language, beam_size=5)
        results = []
        for seg in segments:
            results.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        print(f"  检测到语言: {info.language}, 概率: {info.language_probability:.2f}, 共 {len(results)} 段")
        return results
    except ImportError:
        print("  [X] faster-whisper 未安装。运行: pip install faster-whisper")
        return None
    except Exception as e:
        print(f"  [X] Whisper 转录失败: {e}")
        return None


def find_transcript_file(video_path):
    """查找视频同级目录中可能的中文翻译字幕/文本"""
    parent = Path(video_path).parent
    stem = Path(video_path).stem

    patterns = [
        f"{stem}_transcript_zh.txt",
        f"{stem}_zh.txt",
        f"{stem}_chinese.txt",
        "*transcript*zh*.txt",
        "*chinese*.txt",
    ]
    for pattern in patterns:
        files = list(parent.glob(pattern))
        if files:
            return files[0]

    for pattern in [f"{stem}_transcript.json", "*transcript*.json"]:
        files = list(parent.glob(pattern))
        if files:
            return files[0]

    return None


def read_text_file(file_path):
    """读取文本文件，支持 .txt 和 .json（字幕格式）"""
    path = Path(file_path)
    if not path.exists():
        return None

    if path.suffix == ".json":
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                texts = [item.get("text", "") for item in data if isinstance(item, dict)]
                return " ".join(texts)
            elif isinstance(data, dict):
                return data.get("text", "") or data.get("content", "")
        except Exception:
            pass

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def split_text_into_chunks(text, max_chars=400):
    """将文本按句子分段，每段不超过 max_chars"""
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    chunks = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(current) + len(sent) <= max_chars:
            current += sent + " "
        else:
            if current.strip():
                chunks.append(current.strip())
            current = sent + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


def generate_tts(text_chunks, output_dir, voice="zh-CN-XiaoxiaoNeural"):
    """使用 edge-tts 为每段文本生成语音"""
    audio_files = []
    total = len(text_chunks)
    for i, text in enumerate(text_chunks):
        text = text.strip()
        if not text:
            continue
        output_file = Path(output_dir) / f"tts_{i:04d}.mp3"
        display = text[:50] + "..." if len(text) > 50 else text
        print(f"  TTS [{i+1}/{total}] {display}")
        r = run_cmd([
            "edge-tts", "--voice", voice,
            "--text", text,
            "--write-media", str(output_file)
        ])
        if r and output_file.exists():
            audio_files.append(str(output_file))
        else:
            print(f"    [X] 第 {i+1} 段 TTS 失败，跳过")
    return audio_files


def merge_audio_segments(audio_files, output_file):
    """使用 ffmpeg concat 合并多个音频文件"""
    if not audio_files:
        return False

    tmpdir = Path(output_file).parent
    list_file = tmpdir / "concat_list.txt"

    files_to_copy = []
    with open(list_file, "w", encoding="utf-8") as f:
        for af in audio_files:
            src = Path(af)
            if src.parent != tmpdir:
                dst = tmpdir / src.name
                if not dst.exists():
                    files_to_copy.append((src, dst))
                f.write(f"file '{dst.name}'\n")
            else:
                f.write(f"file '{src.name}'\n")

    for src, dst in files_to_copy:
        shutil.copy2(src, dst)

    r = run_cmd([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-acodec", "libmp3lame", "-ar", "44100", "-b:a", "128k",
        str(output_file)
    ], cwd=str(tmpdir))

    list_file.unlink(missing_ok=True)
    for _, dst in files_to_copy:
        dst.unlink(missing_ok=True)

    return r is not None and Path(output_file).exists()


def merge_with_video(video_path, audio_path, output_path):
    """将配音音频与原视频合并（替换原音轨）"""
    r = run_cmd([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(output_path)
    ])
    return r is not None and Path(output_path).exists()


def merge_with_video_keep_bgm(video_path, audio_path, output_path):
    """将配音音频与原视频混合（保留原音轨作为背景，降低音量）"""
    r = run_cmd([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex",
        "[0:a]volume=0.15[bg];[1:a]volume=1.0[fg];[bg][fg]amix=inputs=2:duration=shortest[aout]",
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        str(output_path)
    ])
    return r is not None and Path(output_path).exists()


# ─── 主流程 ────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="AI 配音核心处理：视频 → 中文语音 → 合并视频（跨平台）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 转录视频并生成中文配音（需先提供中文文本）
  python ai_dub_core.py video.mp4

  # 使用指定的中文文本文件（跳过转录）
  python ai_dub_core.py video.mp4 --text chinese_text.txt

  # 转录英文视频，保存文本供翻译后重跑
  python ai_dub_core.py video.mp4
  # → 生成 video_transcript.txt，翻译后保存为 video_transcript_zh.txt
  # → 重新运行: python ai_dub_core.py video.mp4 --text video_transcript_zh.txt

  # macOS / Linux
  python3 ai_dub_core.py video.mp4 --voice zh-CN-YunyangNeural --keep-bgm
"""
    )
    parser.add_argument("input", help="输入视频文件路径")
    parser.add_argument("-o", "--output", help="输出视频路径（默认: 输入文件名_zh_dubbed.mp4）")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural", help="Edge TTS 语音名称")
    parser.add_argument("--text", help="直接提供中文文本文件路径（跳过转录）")
    parser.add_argument("--keep-bgm", action="store_true", help="保留原视频背景音（降低音量后混合）")
    parser.add_argument("--whisper-model", default="base", help="Whisper 模型大小 (tiny/base/small)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[X] 文件不存在: {input_path}")
        sys.exit(1)

    # 检查依赖
    missing = []
    if not check_cmd("ffmpeg"):
        missing.append("ffmpeg (Windows: winget install ffmpeg | macOS: brew install ffmpeg | Linux: apt install ffmpeg)")
    if not check_cmd("edge-tts"):
        missing.append("edge-tts (pip install edge-tts)")
    if missing:
        print("[X] 缺少依赖:")
        for m in missing:
            print(f"    - {m}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_zh_dubbed.mp4")

    print("=" * 50)
    print("  AI 中文配音 — 核心处理")
    print("=" * 50)
    print(f"  输入: {input_path}")
    print(f"  输出: {output_path}")
    print(f"  语音: {args.voice}")
    print("")

    # ── 获取文本 ───────────────────────────
    text = ""

    if args.text:
        text_path = Path(args.text)
        if not text_path.exists():
            print(f"[X] 文本文件不存在: {text_path}")
            sys.exit(1)
        text = read_text_file(text_path) or ""
        print(f"[OK] 读取中文文本: {len(text)} 字符 (来自 {text_path.name})")

    else:
        found = find_transcript_file(input_path)
        if found:
            text = read_text_file(found) or ""
            if text and len(text) > 50:
                zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
                if zh_chars > len(text) * 0.1:
                    print(f"[OK] 找到中文文本: {len(text)} 字符 (来自 {found.name})")

        if not text:
            print("[Info] 未找到中文文本，进入转录模式...")
            print("")

            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)
                wav_path = tmpdir / "audio.wav"

                print("Step 1/4: 提取音频...")
                if not extract_audio(input_path, wav_path):
                    print("[X] 音频提取失败")
                    sys.exit(1)
                print("  [OK] 音频已提取")

                print("Step 2/4: 语音转录...")
                segments = transcribe_with_whisper(wav_path, args.whisper_model, "en")
                if not segments:
                    print("[X] 转录失败，请确认 faster-whisper 已正确安装")
                    print("    安装命令: pip install faster-whisper")
                    sys.exit(1)

                raw_text = " ".join(s["text"] for s in segments)
                trans_file = input_path.parent / f"{input_path.stem}_transcript.txt"
                with open(trans_file, "w", encoding="utf-8") as f:
                    f.write(f"# 原始英文转录文本 ({len(segments)} 段)\n")
                    f.write(f"# 请将此文件内容翻译为中文后，\n")
                    f.write(f"# 保存到同一目录下，文件名为: {input_path.stem}_transcript_zh.txt\n")
                    f.write(f"# 然后重新运行:\n")
                    f.write(f"#   python ai_dub_core.py \"{input_path}\" --text {input_path.stem}_transcript_zh.txt\n")
                    f.write("#" + "=" * 50 + "\n\n")
                    for s in segments:
                        f.write(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}\n")

                print(f"[OK] 转录已保存: {trans_file}")
                print("")
                print("[!] 检测到英文内容，需要翻译后重新运行")
                print(f"    操作步骤:")
                print(f"    1. 打开文件: {trans_file.name}")
                print(f"    2. 将其内容翻译为中文")
                print(f"    3. 保存为: {input_path.stem}_transcript_zh.txt (在同一目录)")
                print(f"    4. 重新运行: python ai_dub_core.py \"{input_path}\"")
                print("")
                sys.exit(0)

    if not text or not text.strip():
        print("[X] 可用文本为空，无法生成配音")
        sys.exit(1)

    # ── 处理文本 + TTS ─────────────────────
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        print("Step 3/4: 文本分段与 TTS 生成...")
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        chunks = split_text_into_chunks(text, max_chars=400)
        print(f"  文本已分为 {len(chunks)} 段")

        audio_files = generate_tts(chunks, tmpdir, args.voice)
        if not audio_files:
            print("[X] TTS 生成失败，无可用音频片段")
            sys.exit(1)

        print(f"  [OK] 成功生成 {len(audio_files)} 个音频片段")
        print("")

        print("Step 4/4: 合并音频与视频...")
        merged_audio = tmpdir / "merged.mp3"
        if not merge_audio_segments(audio_files, merged_audio):
            print("[X] 音频合并失败")
            sys.exit(1)
        print("  [OK] 音频已合并")

        if args.keep_bgm:
            if merge_with_video_keep_bgm(input_path, merged_audio, output_path):
                print(f"[OK] 配音完成（保留背景音）: {output_path}")
            else:
                print("[X] 视频合并失败")
                sys.exit(1)
        else:
            if merge_with_video(input_path, merged_audio, output_path):
                print(f"[OK] 配音完成: {output_path}")
            else:
                print("[X] 视频合并失败")
                sys.exit(1)

    print("")
    print("=" * 50)
    print("  ✅ 全部完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
