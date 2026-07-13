#!/bin/bash
# YouTube 频道监控 — 完整版 (macOS/Linux 包装器)
# 调用 yt_monitor.py 完成频道扫描
# 用法: ./scripts/yt-monitor.sh [--dry-run] [--channel CHANNEL] [--list]

set -euo pipefail

DRY_RUN=false
CHANNEL=""
LIST=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --channel) CHANNEL="$2"; shift 2 ;;
        --list) LIST=true; shift ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_SCRIPT="$SCRIPT_DIR/yt_monitor.py"

echo "============================================"
echo "  YouTube 频道监控"
echo "============================================"
echo ""

# 检查 Python (macOS/Linux 优先 python3)
PYTHON_CMD="python3"
command -v python3 &>/dev/null || PYTHON_CMD="python"
command -v "$PYTHON_CMD" &>/dev/null || { echo "[X] Python 未安装"; exit 1; }

[[ -f "$CORE_SCRIPT" ]] || { echo "[X] 核心脚本未找到: $CORE_SCRIPT"; exit 1; }

ARGS=("$CORE_SCRIPT")
[[ "$DRY_RUN" == true ]] && ARGS+=("--dry-run")
[[ -n "$CHANNEL" ]] && ARGS+=("--channel" "$CHANNEL")
[[ "$LIST" == true ]] && ARGS+=("--list")

"$PYTHON_CMD" "${ARGS[@]}"
