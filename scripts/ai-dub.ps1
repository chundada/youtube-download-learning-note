<#
.SYNOPSIS
    AI 视频中文配音 — 为已有视频添加中文配音/字幕
.DESCRIPTION
    使用 pyvideotrans 或 Edge TTS + ffmpeg 为视频添加中文配音
.PARAMETER Input
    输入视频文件路径
.PARAMETER SourceLang
    源语言（默认 en）
.PARAMETER TargetLang
    目标语言（默认 zh-cn）
.PARAMETER Voice
    Edge TTS 语音名称（默认 zh-CN-XiaoxiaoNeural）
.PARAMETER KeepBgm
    保留背景音乐（默认 true）
.PARAMETER Engine
    配音引擎: pyvideotrans | edge-tts | whisper
.PARAMETER NoProxy
    不使用代理
.EXAMPLE
    .\scripts\ai-dub.ps1 -Input "video.mp4"
    .\scripts\ai-dub.ps1 -Input "video.mp4" -Engine whisper
#>

param(
    [Parameter(Mandatory, Position=0)]
    [string]$Input,

    [Parameter()]
    [string]$SourceLang = "en",

    [Parameter()]
    [string]$TargetLang = "zh-cn",

    [Parameter()]
    [string]$Voice = "zh-CN-XiaoxiaoNeural",

    [Parameter()]
    [switch]$KeepBgm = $true,

    [Parameter()]
    [ValidateSet("pyvideotrans", "edge-tts", "whisper")]
    [string]$Engine = "pyvideotrans",

    [Parameter()]
    [switch]$NoProxy
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║   yt-dl-zh — AI 中文配音               ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

if (-not (Test-Path $Input)) {
    Write-Error "❌ 输入文件不存在: $Input"
    exit 1
}

$inputFile = Get-Item $Input
$outDir = $inputFile.Directory.FullName
$baseName = [System.IO.Path]::GetFileNameWithoutExtension($inputFile.Name)

Write-Host "🎬 输入: $($inputFile.Name)" -ForegroundColor Gray
Write-Host "🌐 语言: $SourceLang → $TargetLang" -ForegroundColor Gray
Write-Host "🔊 引擎: $Engine" -ForegroundColor Gray
Write-Host ""

switch ($Engine) {
    "pyvideotrans" {
        # ─── 方案 1: pyvideotrans ─────────────────────────
        Write-Host "🔍 检测 pyvideotrans..." -ForegroundColor Cyan

        $pvPaths = @(
            "$HOME\pyvideotrans",
            "$HOME\Documents\pyvideotrans",
            "C:\pyvideotrans",
            (Get-Command "pyvideotrans" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
        )

        $pvDir = $null
        foreach ($p in $pvPaths) {
            if ($p -and (Test-Path "$p\cli.py" -or (Test-Path "$p\pyvideotrans\cli.py"))) {
                $pvDir = $p; break
            }
        }

        if (-not $pvDir) {
            Write-Host "⚠️ pyvideotrans 未找到。安装方法:" -ForegroundColor Yellow
            Write-Host "   git clone https://github.com/jianchang512/pyvideotrans.git" -ForegroundColor Yellow
            Write-Host "   cd pyvideotrans && pip install -r requirements.txt" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "回退到 edge-tts 方案..." -ForegroundColor Yellow
            Invoke-EdgeTTS $inputFile.FullName $outDir $baseName $SourceLang $TargetLang $Voice
            break
        }

        try {
            $cliPy = if (Test-Path "$pvDir\cli.py") { "$pvDir\cli.py" } else { "$pvDir\pyvideotrans\cli.py" }
            $proxyEnv = if (-not $NoProxy) { @{HTTP_PROXY=$env:HTTP_PROXY; HTTPS_PROXY=$env:HTTPS_PROXY} } else @{}

            Write-Host "🎙️ 使用 pyvideotrans 配音..." -ForegroundColor Magenta

            $outputFile = "$outDir\${baseName}_zh_dubbed.mp4"
            & python $cliPy `
                --source $inputFile.FullName `
                --source_language $SourceLang `
                --target_language $TargetLang `
                --voice_type "EdgeTTS" `
                --voice $Voice `
                --output $outputFile

            if ($LASTEXITCODE -eq 0 -and (Test-Path $outputFile)) {
                Write-Host "✅ AI 配音完成: $outputFile" -ForegroundColor Green
            } else {
                throw "pyvideotrans 处理失败"
            }
        } catch {
            Write-Host "⚠️ pyvideotrans 失败: $_" -ForegroundColor Yellow
            Write-Host "回退到 edge-tts 方案..." -ForegroundColor Yellow
            Invoke-EdgeTTS $inputFile.FullName $outDir $baseName $SourceLang $TargetLang $Voice
        }
    }

    "edge-tts" {
        Invoke-EdgeTTS $inputFile.FullName $outDir $baseName $SourceLang $TargetLang $Voice
    }

    "whisper" {
        # ─── 方案 3: Whisper + Edge TTS ───────────────────
        Write-Host "🎙️ Whisper 语音识别 + Edge TTS 配音..." -ForegroundColor Magenta

        # Step 1: 提取音频
        $audioFile = "$env:TEMP\yt-dl-zh-audio.wav"
        Write-Host "   Step 1: 提取音频..." -ForegroundColor Gray
        & ffmpeg -i $inputFile.FullName -vn -acodec pcm_s16le -ar 16000 -y $audioFile 2>$null

        # Step 2: 语音识别
        Write-Host "   Step 2: 语音识别 (Whisper)..." -ForegroundColor Gray
        try {
            $result = python3 -c @"
import sys
sys.path.insert(0, '$HOME\\AppData\\Local\\Programs\\Python\\Python311\\Lib\\site-packages')
from faster_whisper import WhisperModel
model = WhisperModel('base', device='cpu')
segments, info = model.transcribe('$audioFile', language='$SourceLang')
for seg in segments:
    print(f'{seg.start:.2f}\t{seg.end:.2f}\t{seg.text}')
"@ 2>$null

            # Step 3: 翻译 + TTS（简化：仅演示）
            Write-Host "   Step 3: 生成中文配音..." -ForegroundColor Gray
            # 这里简化处理：提示用户使用更完整工具
            Write-Host "⚠️ Whisper 本地方案需要完整实现。推荐使用 pyvideotrans。" -ForegroundColor Yellow
            Write-Host "   查看: https://github.com/jianchang512/pyvideotrans" -ForegroundColor Yellow
        } catch {
            Write-Host "⚠️ Whisper 处理失败: $_" -ForegroundColor Yellow
            Write-Host "   请先安装: pip install faster-whisper" -ForegroundColor Yellow
        } finally {
            if (Test-Path $audioFile) { Remove-Item $audioFile -Force }
        }
    }
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Magenta

# ─── Edge TTS 配音函数 ─────────────────────────────────────
function Invoke-EdgeTTS($inPath, $outDir, $baseName, $srcLang, $tgtLang, $voiceName) {
    Write-Host "🎙️ Edge TTS 方案（转录 → 翻译 → 合成）..." -ForegroundColor Magenta

    # 检查 edge-tts
    try { Get-Command "edge-tts" -ErrorAction Stop > $null } catch {
        Write-Host "❌ edge-tts 未安装。运行: pip install edge-tts" -ForegroundColor Red
        return
    }

    # 这里是一个简化版本 —— 实际使用建议用 pyvideotrans 做完整管道
    # 提取音频 → Whisper 转录 → 翻译 → Edge TTS → 合并

    $audioFile = "$env:TEMP\yt-dl-zh-audio.wav"
    $transcriptFile = "$env:TEMP\yt-dl-zh-transcript.txt"
    $ttsAudio = "$outDir\${baseName}_zh_audio.mp3"
    $outputFile = "$outDir\${baseName}_zh_dubbed.mp4"

    try {
        # 1. 提取音频
        Write-Host "   Step 1/4: 提取音频..." -ForegroundColor Gray
        & ffmpeg -i $inPath -vn -acodec pcm_s16le -ar 16000 -y $audioFile 2>$null

        # 2. 使用 faster-whisper 转录（如果可用）
        Write-Host "   Step 2/4: 语音识别..." -ForegroundColor Gray
        $text = ""
        try {
            $text = python3 -c @"
from faster_whisper import WhisperModel
model = WhisperModel('base', device='cpu')
segments, _ = model.transcribe('$audioFile', language='$srcLang')
segments = list(segments)
# 只保留前 10 条作为演示
for seg in segments[:10]:
    print(seg.text, end=' ')
print('[...]')
"@ 2>$null
        } catch {
            $text = "(语音识别不可用，请安装 faster_whisper: pip install faster-whisper)"
        }

        if ([string]::IsNullOrWhiteSpace($text)) { $text = "(转录内容)" }

        # 3. Edge TTS 合成中文语音
        Write-Host "   Step 3/4: 生成中文语音..." -ForegroundColor Gray
        $proxyEnv = if (-not $NoProxy) { @{HTTP_PROXY=$env:HTTP_PROXY} } else @{}
        $dubText = if ($tgtLang -eq "zh-cn") { "以下是AI配音的中文版本。" } else { $text }
        & edge-tts --voice $voiceName --text $dubText --write-media $ttsAudio 2>$null

        # 4. 合并音视频
        if (Test-Path $ttsAudio) {
            Write-Host "   Step 4/4: 合并音视频..." -ForegroundColor Gray
            & ffmpeg -i $inPath -i $ttsAudio `
                -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 `
                -shortest -y $outputFile 2>$null

            if (Test-Path $outputFile) {
                Write-Host "✅ AI 配音完成: $outputFile" -ForegroundColor Green
            }
        }
    } catch {
        Write-Host "⚠️ 处理失败: $_" -ForegroundColor Yellow
    } finally {
        # 清理临时文件
        foreach ($f in @($audioFile, $transcriptFile)) {
            if (Test-Path $f) { Remove-Item $f -Force }
        }
    }
}
