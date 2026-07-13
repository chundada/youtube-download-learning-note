#!/bin/bash
# AI 视频中文配音 — 完整版 (macOS/Linux 包装器)
# 调用 ai_dub_core.py 完成配音流程
# 用法: ./scripts/ai-dub.sh -i video.mp4 [-t text.txt] [-v voice] [--keep-bgm]

set -euo pipefail

INPUT=""
TEXT=""
VOICE="zh-CN-XiaoxiaoNeural"
KEEP_BGM=false
WHISPER_MODEL="base"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--input) INPUT="$2"; shift 2 ;;
        -t|--text) TEXT="$2"; shift 2 ;;
        -v|--voice) VOICE="$2"; shift 2 ;;
        --keep-bgm) KEEP_BGM=true; shift ;;
        --whisper-model) WHISPER_MODEL="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

[[ -n "$INPUT" ]] || { echo "用法: $0 -i <video.mp4> [-t text.txt] [-v voice]"; exit 1; }
[[ -f "$INPUT" ]] || { echo "文件不存在: $INPUT"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_SCRIPT="$SCRIPT_DIR/ai_dub_core.py"

echo "============================================"
echo "  AI 中文配音 — 完整版"
echo "============================================"
echo ""

# 检查 Python (macOS/Linux 优先 python3)
PYTHON_CMD="python3"
command -v python3 &>/dev/null || PYTHON_CMD="python"
command -v "$PYTHON_CMD" &>/dev/null || { echo "[X] Python 未安装"; exit 1; }

[[ -f "$CORE_SCRIPT" ]] || { echo "[X] 核心脚本未找到: $CORE_SCRIPT"; exit 1; }

# 运行核心脚本
ARGS=("$CORE_SCRIPT" "$INPUT" "--voice" "$VOICE" "--whisper-model" "$WHISPER_MODEL")
[[ -n "$TEXT" ]] && ARGS+=("--text" "$TEXT")
[[ "$KEEP_BGM" == true ]] && ARGS+=("--keep-bgm")

"$PYTHON_CMD" "${ARGS[@]}"
