<#
.SYNOPSIS
    YouTube 频道监控 — 完整版 (Windows 包装器)
.DESCRIPTION
    调用 yt_monitor.py 完成频道扫描和自动下载。
    跨平台核心脚本 yt_monitor.py 同时支持 macOS / Linux。
.PARAMETER DryRun
    仅扫描不下载
.PARAMETER Channel
    只处理指定频道
.PARAMETER List
    只输出频道列表
.EXAMPLE
    .\scripts\yt-monitor.ps1
    .\scripts\yt-monitor.ps1 -DryRun
    .\scripts\yt-monitor.ps1 -Channel "channel_name"
#>

param(
    [switch]$DryRun,
    [string]$Channel = "",
    [switch]$List
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$coreScript = "$ScriptDir\yt_monitor.py"

if (-not (Test-Path $coreScript)) {
    Write-Error "❌ 核心脚本未找到: $coreScript"
    exit 1
}

$pyCmd = if (Get-Command "python3" -ErrorAction SilentlyContinue) { "python3" } else { "python" }

$args = @($coreScript)
if ($DryRun) { $args += "--dry-run" }
if ($Channel) { $args += @("--channel", $Channel) }
if ($List) { $args += "--list" }

& $pyCmd @args
