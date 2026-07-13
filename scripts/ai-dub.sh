#!/bin/bash
# ai-dub.sh — AI 视频中文配音 (Linux/macOS)
# 用法: ./scripts/ai-dub.sh -i video.mp4 [-s en] [-t zh-cn]

set -euo pipefail

INPUT=""
SOURCE_LANG="en"
TARGET_LANG="zh-cn"
VOICE="zh-CN-XiaoxiaoNeural"
KEEP_BGM=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--input) INPUT="$2"; shift 2 ;;
        -s|--source) SOURCE_LANG="$2"; shift 2 ;;
        -t|--target) TARGET_LANG="$2"; shift 2 ;;
        -v|--voice) VOICE="$2"; shift 2 ;;
        --no-bgm) KEEP_BGM=false; shift ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

[[ -n "$INPUT" ]] || { echo "用法: $0 -i <video.mp4>"; exit 1; }
[[ -f "$INPUT" ]] || { echo "文件不存在: $INPUT"; exit 1; }

echo "============================================"
echo "  yt-dl-zh — AI 中文配音"
echo "============================================"
echo ""

# macOS/Linux: 先尝试 pyvideotrans
if command -v python3 &>/dev/null; then
    # 检查几个常见 pyvideotrans 路径
    for pvpath in "$HOME/pyvideotrans" "$HOME/Documents/pyvideotrans" "/opt/pyvideotrans"; do
        if [[ -d "$pvpath" && -f "$pvpath/cli.py" ]]; then
            echo "🎙️ 使用 pyvideotrans (from $pvpath)..."
            python3 "$pvpath/cli.py" \
                --source "$INPUT" \
                --source_language "$SOURCE_LANG" \
                --target_language "$TARGET_LANG" \
                --voice_type "EdgeTTS" \
                --voice "$VOICE"
            echo "✅ 完成！"
            exit 0
        fi
    done
fi

echo "⚠️ pyvideotrans 未找到。安装方法:"
echo "   git clone https://github.com/jianchang512/pyvideotrans.git"
echo "   cd pyvideotrans && pip install -r requirements.txt"
echo ""
echo "或使用 edge-tts + ffmpeg 手动配音（macOS/Linux）:"
echo "   pip install edge-tts"
echo "   edge-tts --text "中文文本" --voice $VOICE --write-media audio.mp3"
echo "   ffmpeg -i \"$INPUT\" -i audio.mp3 -c:v copy -c:a aac output.mp4"