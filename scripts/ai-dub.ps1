<#
.SYNOPSIS
    AI 视频中文配音 — 完整版 (Windows 包装器)
.DESCRIPTION
    调用 ai_dub_core.py 完成视频转录、中文 TTS 合成和视频合并。
    完整流程：提取音频 → Whisper 转录 → 保存文本 → 翻译后重跑 → TTS → 合并。
    跨平台核心脚本 ai_dub_core.py 同时支持 macOS / Linux。
.PARAMETER Input
    输入视频文件路径
.PARAMETER Text
    直接提供中文文本文件（跳过转录）
.PARAMETER Voice
    Edge TTS 语音名称
.PARAMETER KeepBgm
    保留背景音乐
.PARAMETER WhisperModel
    Whisper 模型大小
.EXAMPLE
    .\scripts\ai-dub.ps1 -Input "video.mp4"
    .\scripts\ai-dub.ps1 -Input "video.mp4" -Text "translated.txt"
    .\scripts\ai-dub.ps1 -Input "video.mp4" -KeepBgm -Voice "zh-CN-YunyangNeural"
#>

param(
    [Parameter(Mandatory, Position=0)]
    [string]$Input,

    [string]$Text = "",
    [string]$Voice = "zh-CN-XiaoxiaoNeural",
    [switch]$KeepBgm,
    [string]$WhisperModel = "base"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$coreScript = "$ScriptDir\ai_dub_core.py"

if (-not (Test-Path $coreScript)) {
    Write-Error "❌ 核心脚本未找到: $coreScript"
    exit 1
}

$pyCmd = if (Get-Command "python3" -ErrorAction SilentlyContinue) { "python3" } else { "python" }

$args = @($coreScript, $Input)

if ($Text) { $args += @("--text", $Text) }
if ($Voice) { $args += @("--voice", $Voice) }
if ($KeepBgm) { $args += "--keep-bgm" }
if ($WhisperModel) { $args += @("--whisper-model", $WhisperModel) }

& $pyCmd @args
