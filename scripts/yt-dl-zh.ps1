<#
.SYNOPSIS
    下载 YouTube 视频并自动处理中文内容
.DESCRIPTION
    优先级链: 中文配音音轨 → 中文字幕 → AI 配音
.PARAMETER Url
    YouTube 视频 URL
.PARAMETER OutDir
    输出目录（默认 ~/youtube-downloads）
.PARAMETER SubsOnly
    无中文音轨时下载中文字幕（不调用 AI 配音）
.PARAMETER AIDub
    无中文音轨时使用 AI 配音（需要 pyvideotrans）
.PARAMETER AudioOnly
    仅下载音频
.PARAMETER NoProxy
    不使用代理
.PARAMETER Config
    配置文件路径
.EXAMPLE
    .\scripts\yt-dl-zh.ps1 "https://youtu.be/XXX"
    .\scripts\yt-dl-zh.ps1 "https://youtu.be/XXX" -OutDir "D:\Downloads" -AIDub
#>

param(
    [Parameter(Mandatory, Position=0)]
    [string]$Url,

    [Parameter()]
    [string]$OutDir = "",

    [Parameter()]
    [switch]$SubsOnly,

    [Parameter()]
    [switch]$AIDub,

    [Parameter()]
    [switch]$AudioOnly,

    [Parameter()]
    [switch]$NoProxy,

    [Parameter()]
    [string]$Config = ""
)

# ─── 错误处理 ──────────────────────────────────────────────
$ErrorActionPreference = "Stop"

# ─── 配置加载 ──────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillDir  = Split-Path -Parent $ScriptDir

# 默认值
$Proxy = if ($env:HTTP_PROXY) { $env:HTTP_PROXY } else { "http://127.0.0.1:2080" }
$DownloadDir = if ($OutDir) { $OutDir } elseif ($env:YT_DL_DIR) { $env:YT_DL_DIR } else { "$HOME\youtube-downloads" }
$FormatBest = "bv[ext=mp4]+140-16/bv[ext=mp4]+ba*"
$FormatSubs = "bv[ext=mp4]+ba[ext=m4a]"
$FormatAudio = "140-16/ba*"

# 尝试加载 config.yaml
if (-not $Config) { $Config = "$SkillDir\config.yaml" }
if (Test-Path $Config) {
    try {
        $yaml = Get-Content $Config -Raw
        # 简单解析 proxy
        if ($yaml -match "proxy:\s*'([^']+)'") { if (-not $NoProxy -and -not $env:HTTP_PROXY) { $Proxy = $Matches[1] } }
        if ($yaml -match "download_dir:\s*'([^']+)'") { $DownloadDir = $Matches[1].Replace("~", $HOME) }
    } catch { Write-Warning "配置文件解析失败: $_" }
}

# ─── 工具检查 ──────────────────────────────────────────────
function Test-Command($cmd) {
    try { Get-Command $cmd -ErrorAction Stop > $null; return $true }
    catch { return $false }
}

if (-not (Test-Command "yt-dlp")) { Write-Error "❌ yt-dlp 未安装。运行: pip install yt-dlp 或 winget install yt-dlp"; exit 1 }
if (-not (Test-Command "ffmpeg")) { Write-Error "❌ ffmpeg 未安装。运行: winget install ffmpeg"; exit 1 }

# ─── 辅助函数 ─────────────────────────────────────────────
function Sanitize-Filename($name) {
    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    $sanitized = ($name -replace "[$([regex]::Escape(-join $invalid))]", "_").Trim()
    if ($sanitized.Length -gt 200) { $sanitized = $sanitized.Substring(0, 200) }
    if ([string]::IsNullOrWhiteSpace($sanitized)) { $sanitized = "youtube_video" }
    return $sanitized
}

function Get-ChineseTitle($url) {
    Write-Host "📡 获取中文标题..." -ForegroundColor Cyan
    $titleScript = "$ScriptDir\get_yt_title.py"
    if (Test-Path $titleScript) {
        try {
            $result = python3 $titleScript $url 2>$null
            if ($result -match "\t(.+)$") { return $Matches[1] }
            elseif ($result -match "^[^\t]+$" -and $result -notmatch "获取失败") { return $result }
        } catch { }
    }
    # 回退: yt-dlp 获取标题
    try {
        $proxyArg = if (-not $NoProxy) { "--proxy", $Proxy } else { @() }
        $title = & yt-dlp @proxyArg --print "%(title)s" --no-download $url 2>$null | Select-Object -First 1
        if ($title) { return $title }
    } catch { }
    return ""
}

function Download-Video($url, $outDir, $format, $filename) {
    $safeName = Sanitize-Filename $filename
    $output = "$outDir\$safeName.%(ext)s"
    
    $proxyArg = if (-not $NoProxy) { @("--proxy", $Proxy) } else { @() }
    
    Write-Host "📥 下载中..." -ForegroundColor Cyan
    Write-Host "   格式: $format" -ForegroundColor Gray
    Write-Host "   输出: $output" -ForegroundColor Gray
    
    & yt-dlp @proxyArg `
        --extractor-args "youtube:player_client=web_embedded" `
        --js-runtimes "node" `
        -f $format `
        --merge-output-format mp4 `
        -o $output `
        $url
    
    if ($LASTEXITCODE -ne 0) { throw "yt-dlp 下载失败 (exit $LASTEXITCODE)" }
    
    # 查找实际输出文件
    $actualFile = Get-ChildItem "$outDir\$safeName.*" | Where-Object { $_.Extension -in ".mp4",".mkv",".webm" } | Select-Object -First 1
    return $actualFile
}

function Download-Subs($url, $outDir, $filename) {
    $safeName = Sanitize-Filename $filename
    $output = "$outDir\$safeName.%(ext)s"
    $proxyArg = if (-not $NoProxy) { @("--proxy", $Proxy) } else { @() }
    
    Write-Host "📝 下载视频 + 中文字幕..." -ForegroundColor Yellow
    Write-Host "   尝试下载中文/翻译字幕" -ForegroundColor Gray
    
    # 先获取可用字幕列表
    $subLangs = & yt-dlp @proxyArg --list-subs $url 2>&1
    $zhSubAvailable = $subLangs -match "zh"
    
    $subArgs = if ($zhSubAvailable) {
        @("--write-subs", "--sub-langs", "zh-Hans,zh-CN,zh,en", "--embed-subs")
    } else {
        # 无中文字幕时下载英文字幕（后续可翻译）
        @("--write-subs", "--sub-langs", "en", "--embed-subs")
    }
    
    & yt-dlp @proxyArg `
        @subArgs `
        -f "bv[ext=mp4]+ba[ext=m4a]" `
        --merge-output-format mp4 `
        -o $output `
        $url
    
    if ($LASTEXITCODE -ne 0) { throw "yt-dlp 下载失败 (exit $LASTEXITCODE)" }
    
    # 如果只有英文字幕，提示用户
    if (-not $zhSubAvailable) {
        Write-Host "⚠️ 该视频没有自带中文字幕。" -ForegroundColor Yellow
        Write-Host "   已下载英文字幕。如需中文翻译，请运行 AI 配音脚本:" -ForegroundColor Yellow
        Write-Host "   .\scripts\ai-dub.ps1 -Input `"$outDir\$safeName.mp4`" -SourceLang en -TargetLang zh-cn" -ForegroundColor Yellow
    }
    
    return Get-ChildItem "$outDir\$safeName.*" | Where-Object { $_.Extension -in ".mp4",".mkv",".webm" } | Select-Object -First 1
}

function Invoke-AIDub($videoPath, $sourceLang, $targetLang) {
    Write-Host "🎙️ AI 配音中..." -ForegroundColor Magenta
    
    $dubScript = "$ScriptDir\ai-dub.ps1"
    if (Test-Path $dubScript) {
        & $dubScript -Input $videoPath -SourceLang $sourceLang -TargetLang $targetLang -NoProxy:$NoProxy
    } else {
        Write-Host "⚠️ AI 配音脚本未找到。手动操作:" -ForegroundColor Yellow
        Write-Host "   推荐使用 pyvideotrans: https://github.com/jianchang512/pyvideotrans" -ForegroundColor Yellow
    }
}

# ─── 检测中文音轨 ──────────────────────────────────────────
function Test-ChineseAudioTrack($url) {
    $proxyArg = if (-not $NoProxy) { @("--proxy", $Proxy) } else { @() }
    try {
        $formats = & yt-dlp @proxyArg -F $url 2>&1
        return $formats -match "140-16"
    } catch { return $false }
}

# ─── 主流程 ────────────────────────────────────────────────
function Main {
    Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║   yt-dl-zh — YouTube 中文下载           ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    
    # 创建输出目录
    $outDir = $DownloadDir
    if (-not [System.IO.Path]::IsPathRooted($outDir)) {
        $outDir = [System.IO.Path]::Combine($HOME, $outDir)
    }
    New-Item -ItemType Directory -Path $outDir -Force > $null
    Write-Host "📁 输出目录: $outDir" -ForegroundColor Gray
    
    # Step 1: 获取中文标题
    $title = Get-ChineseTitle $url
    if ([string]::IsNullOrWhiteSpace($title)) {
        Write-Host "⚠️ 无法获取标题，使用视频 ID 作为文件名" -ForegroundColor Yellow
        if ($url -match "(?:v=|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})") {
            $title = $Matches[1]
        } else { $title = "youtube_video" }
    }
    Write-Host "📝 标题: $title" -ForegroundColor Green
    
    # 检测标题是否含中文
    $hasChinese = $title -match "[\x{4e00}-\x{9fff}]"
    if ($hasChinese) {
        Write-Host "✅ 中文标题" -ForegroundColor Green
    } else {
        Write-Host "ℹ️ 非中文标题（保持原语言）" -ForegroundColor Gray
    }
    
    # Step 2: 检测音轨/下载
    if ($AudioOnly) {
        # 仅音频模式
        Download-Video $url $outDir $FormatAudio $title
    }
    elseif ($SubsOnly) {
        # 字幕模式
        Download-Subs $url $outDir $title
    }
    else {
        # 默认模式: 检测中文音轨
        $hasZhAudio = Test-ChineseAudioTrack $url
        
        if ($hasZhAudio) {
            Write-Host "🎵 检测到中文配音音轨 (140-16)" -ForegroundColor Green
            Download-Video $url $outDir $FormatBest $title
        }
        else {
            Write-Host "ℹ️ 未检测到中文配音音轨" -ForegroundColor Yellow
            
            if ($AIDub) {
                # AI 配音模式
                $videoFile = Download-Video $url $outDir $FormatSubs $title
                if ($videoFile) {
                    Invoke-AIDub $videoFile.FullName "en" "zh-cn"
                }
            }
            else {
                # 默认: 下载字幕
                Download-Subs $url $outDir $title
            }
        }
    }
    
    # Step 3: 显示完成信息
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "✅ 完成！" -ForegroundColor Green
    Write-Host "📁 输出目录: $outDir" -ForegroundColor Gray
    Get-ChildItem "$outDir\$title*" | ForEach-Object { Write-Host "   📄 $($_.Name)" -ForegroundColor Gray }
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

# ─── 执行 ──────────────────────────────────────────────────
try {
    Main
} catch {
    Write-Host "❌ 错误: $_" -ForegroundColor Red
    exit 1
}
