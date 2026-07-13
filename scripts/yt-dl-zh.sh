#!/bin/bash
# yt-dl-zh.sh - YouTube 中文下载脚本 (Linux/macOS)
# 基于 https://github.com/shange2018/yt-dl-zh
#
# 用法:
#   ./scripts/yt-dl-zh.sh <URL>
#   ./scripts/yt-dl-zh.sh <URL> -o ~/Downloads
#   ./scripts/yt-dl-zh.sh <URL> --ai-dub
#   ./scripts/yt-dl-zh.sh <URL> --subs-only

set -euo pipefail

# --- 配置 ------------------------------------------------
URL="${1:?用法: $0 <URL> [-o OUTDIR] [--ai-dub] [--subs-only]}"
OUTDIR="${HOME}/youtube-downloads"
AIDUB=false
SUBSONLY=false
PROXY="${HTTP_PROXY:-${HTTPS_PROXY:-http://127.0.0.1:2080}}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 解析参数
shift 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--outdir) OUTDIR="$2"; shift 2 ;;
        --ai-dub) AIDUB=true; shift ;;
        --subs-only) SUBSONLY=true; shift ;;
        *) shift ;;
    esac
done

# --- 工具检查 --------------------------------------------
check_cmd() { command -v "$1" >/dev/null 2>&1; }
check_cmd yt-dlp || { echo "❌ yt-dlp 未安装。安装: pip install yt-dlp 或 brew install yt-dlp"; exit 1; }
check_cmd ffmpeg || { echo "❌ ffmpeg 未安装。安装: brew install ffmpeg 或 apt install ffmpeg"; exit 1; }

# --- 辅助: 检测中文 (跨平台, 兼容 macOS BSD grep) ---------
has_chinese() {
    if check_cmd python3; then
        python3 -c "import sys; sys.exit(0 if any('\u4e00'<=c<='\u9fff' for c in sys.argv[1]) else 1)" "$1" 2>/dev/null
        return $?
    fi
    if check_cmd perl; then
        echo "$1" | perl -CS -ne "exit 1 unless /[\x{4e00}-\x{9fff}]/"
        return $?
    fi
    return 1
}

# --- 获取中文标题 ----------------------------------------
get_title() {
    local url="$1"
    local title=""

    if check_cmd python3 && [[ -f "${SCRIPT_DIR}/get_yt_title.py" ]]; then
        title=$(python3 "${SCRIPT_DIR}/get_yt_title.py" "$url" 2>/dev/null | awk -F'\t' '{print $2}' | head -1)
    fi

    if [[ -z "$title" ]]; then
        echo " ⚠️ Python 获取失败，使用 yt-dlp 回退..." >&2
        title=$(yt-dlp ${PROXY:+--proxy "$PROXY"} --print "%(title)s" --no-download "$url" 2>/dev/null | head -1)
    fi

    if [[ -z "$title" ]]; then
        title=$(echo "$url" | sed -n 's/.*[?&]v=\([^&]*\).*/\1/p')
        [[ -z "$title" ]] && title=$(echo "$url" | sed -n 's|.*youtu\.be/\([^?]*\).*|\1|p')
        [[ -z "$title" ]] && title=$(echo "$url" | sed -n 's|.*/shorts/\([^?]*\).*|\1|p')
        [[ -z "$title" ]] && title="youtube_video"
    fi

    echo "$title"
}

# --- 清理文件名 ------------------------------------------
sanitize() {
    echo "$1" | tr -d '/\:*?"<>|' | tr -s ' ' | head -c 200
}

# --- 检测中文音轨 ----------------------------------------
has_zh_audio() {
    local url="$1"
    yt-dlp ${PROXY:+--proxy "$PROXY"} -F "$url" 2>/dev/null | grep -q "140-16"
}

# --- 下载视频 --------------------------------------------
download_video() {
    local url="$1" outdir="$2" format="$3" filename="$4"
    local safe_name; safe_name=$(sanitize "$filename")
    mkdir -p "$outdir"

    echo "📥 下载中..."
    echo "   格式: $format"

    yt-dlp ${PROXY:+--proxy "$PROXY"} \
        --extractor-args "youtube:player_client=web_embedded" \
        ${NODE_PATH:+--js-runtimes "$NODE_PATH"} \
        -f "$format" \
        --merge-output-format mp4 \
        -o "${outdir}/${safe_name}.%(ext)s" \
        "$url"
}

# --- 下载字幕 --------------------------------------------
download_subs() {
    local url="$1" outdir="$2" filename="$3"
    local safe_name; safe_name=$(sanitize "$filename")
    mkdir -p "$outdir"

    echo "📝 下载视频 + 中文字幕..."

    local sub_langs="zh-Hans,zh-CN,zh"
    if yt-dlp ${PROXY:+--proxy "$PROXY"} --list-subs "$url" 2>&1 | grep -q "zh"; then
        echo "   检测到中文字幕"
    else
        sub_langs="en"
        echo "   无中文字幕，下载英文字幕"
    fi

    yt-dlp ${PROXY:+--proxy "$PROXY"} \
        --write-subs --sub-langs "$sub_langs" --embed-subs \
        -f "bv[ext=mp4]+ba[ext=m4a]" \
        --merge-output-format mp4 \
        -o "${outdir}/${safe_name}.%(ext)s" \
        "$url"
}

# --- AI 配音 ----------------------------------------------
ai_dub() {
    local video="$1"
    if [[ -f "${SCRIPT_DIR}/ai-dub.sh" ]]; then
        bash "${SCRIPT_DIR}/ai-dub.sh" -i "$video"
    else
        echo "⚠️ AI 配音脚本未找到。推荐使用 pyvideotrans:"
        echo "   https://github.com/jianchang512/pyvideotrans"
    fi
}

# --- 主流程 ------------------------------------------------
echo "============================================"
echo "  yt-dl-zh - YouTube 中文下载"
echo "============================================"
echo ""

mkdir -p "$OUTDIR"
echo "📁 输出目录: $OUTDIR"

echo "📡 Step 1: 获取视频标题..."
TITLE=$(get_title "$URL")
echo " 📝 标题: $TITLE"

if has_chinese "$TITLE"; then
    echo " ✅ 中文标题"
else
    echo " ℹ️ 非中文标题"
fi

# Step 2: 检测/下载
if has_zh_audio "$URL"; then
    echo "🎵 检测到中文配音音轨 (140-16)"
    download_video "$URL" "$OUTDIR" "bv[ext=mp4]+140-16/bv[ext=mp4]+ba*" "$TITLE"
elif $SUBSONLY || ! $AIDUB; then
    download_subs "$URL" "$OUTDIR" "$TITLE"
elif $AIDUB; then
    echo "🎙️ AI 配音模式..."
    download_video "$URL" "$OUTDIR" "bv[ext=mp4]+ba[ext=m4a]" "$TITLE"
    ai_dub "${OUTDIR}/"$(sanitize "$TITLE")".mp4"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 完成！"
ls -lh "${OUTDIR}/"$(sanitize "$TITLE")"*" 2>/dev/null || true
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"