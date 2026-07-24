<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6&height=200&section=header&text=YouTube%20All%20in%20One&fontSize=48&fontColor=fff&animation=fadeIn">
  <img alt="header" src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6&height=200&section=header&text=YouTube%20All%20in%20One&fontSize=48&fontColor=fff&animation=fadeIn">
</picture>

<div align="center">

# 🎬 YouTube All in One

### 一站搞定：下载 + 中文配音 + 结构化学习笔记

[![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python&logoColor=white)]()
[![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-green?style=flat-square&logo=youtube)]()
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)]()
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)]()

</div>

---

## ✨ 功能一览

| 阶段 | 功能 | 说明 |
|:----:|------|------|
| 🎯 | **自动下载** | 最佳画质，自动检测中文配音音轨 |
| 🎙️ | **AI 中文配音** | 英文视频自动配中文语音（需 `edge-tts`） |
| 🎞️ | **AI 加工合成** | 压暗背景 + 章节总结卡片 + 双语烧录字幕 |
| 📝 | **字幕获取** | YouTube/B站 字幕，4级降级策略永不空手 |
| 📄 | **学习笔记** | 过程还原式 HTML 学习文档，含思维导图、概念速查表 |
| 📂 | **统一交付** | 视频 + 笔记 + 字幕 → 同一个文件夹 |

---

## 🚀 快速开始

### 安装

```bash
pip install -r requirements.txt
pip install yt-dlp edge-tts   # 推荐安装 AI 配音
```

> 还需安装 **ffmpeg**（视频处理必需）：`winget install ffmpeg`（Windows）或 `brew install ffmpeg`（macOS）

### 使用

只需要给 AI 一条指令，剩下的全自动：

| 你想做的事 | 对 AI 说的话 |
|-----------|-------------|
| 下载+笔记 | "帮我下载并整理这个视频 [链接]" |
| 仅做笔记 | "帮我整理这个视频的内容 [链接]" |
| 仅下载视频 | "帮我下载这个视频 [链接]" |
| 英文视频 | 自动检测 → 自动 AI 中文配音 ✅ |

---

## 📂 项目结构

```
YouTube-Download-Learning-Note/
├── .trae/skills/youtube-all-in-one/
│   └── SKILL.md                     ← AI 工作流指令（核心）
├── scripts/
│   ├── yt-dl-zh.ps1                 ← 主下载脚本 (Windows)
│   ├── yt-dl-zh.sh                  ← 主下载脚本 (macOS/Linux)
│   ├── fetch_transcript.py          ← 字幕获取 (YouTube/B站)
│   ├── get_yt_title.py              ← 中文标题获取
│   ├── ai-dub.ps1                   ← AI 配音 (Windows)
│   ├── ai-dub.sh                    ← AI 配音 (macOS/Linux)
│   ├── render_cards.py              ← 章节总结卡片渲染 (Phase 2.6)
│   ├── build_bilingual_ass.py       ← 双语 ASS 字幕生成 (Phase 2.7)
│   ├── compose_video.py             ← 最终合成 (Phase 2.8)
│   ├── yt-monitor.ps1               ← 频道监控
│   └── youtuber_list.md             ← 监控频道列表
├── config.yaml                      ← 全局配置
├── requirements.txt                 ← Python 依赖
└── README.md
```

---

## 🔄 工作流程

```
用户输入 YouTube/B站 链接
         │
         ▼
  ┌─ Phase 0 ─────────────────────────────────────┐
  │  获取中文标题 → get_yt_title.py                │
  └────────────────────┬──────────────────────────┘
                       ▼
  ┌─ Phase 1 ─────────────────────────────────────┐
  │  下载视频（最佳画质）                          │
  │      │                                        │
  │      ├─ 有中文配音音轨(140-16)?                │
  │      │   └─ ✅ 直接合并                       │
  │      │                                        │
  │      └─ 无 → 判断是否英文视频                  │
  │          ├─ 是 → AI 中文配音 → ✅             │
  │          └─ 否 → 保留原音轨 → ✅             │
  └────────────────────┬──────────────────────────┘
                       ▼
  ┌─ Phase 2 ─────────────────────────────────────┐
  │  获取字幕 → fetch_transcript.py               │
  │  4级降级: API → yt-dlp → 第三方 → 框架性笔记  │
  └────────────────────┬──────────────────────────┘
                       ▼
  ┌─ Phase 2.5~2.8 ───────────────────────────────┐
  │  AI 加工合成                                  │
  │  · AI 翻译 + 章节总结（text_zh/chapters.json）│
  │  · render_cards.py → 总结卡片 PNG            │
  │  · build_bilingual_ass.py → 双语字幕 ASS     │
  │  · compose_video.py → 压暗背景+卡片+双语字幕 │
  └────────────────────┬──────────────────────────┘
                       ▼
  ┌─ Phase 3~8 ───────────────────────────────────┐
  │  生成结构化 HTML 学习文档                     │
  │  · 过程还原式叙述（先过程后结论）              │
  │  · Mermaid 思维导图 + 对比表格                │
  │  · 核心概念速查表 + 行动指南                  │
  │  · 延伸阅读 + 金句卡片                        │
  └────────────────────┬──────────────────────────┘
                       ▼
  ┌─ Phase 9 ─────────────────────────────────────┐
  │  统一交付 → 桌面/学习笔记产出/{标题}_学习笔记/ │
  │  ├── 📹 视频.mp4                             │
  │  ├── 📄 HTML 学习文档                         │
  │  └── 📝 字幕文件                              │
  └───────────────────────────────────────────────┘
```

---

## 🔧 脚本速查

| 操作 | Windows | macOS/Linux |
|------|---------|-------------|
| 下载视频 | `scripts\yt-dl-zh.ps1 -Url "URL"` | `bash scripts/yt-dl-zh.sh "URL"` |
| 仅字幕 | `... -SubsOnly` | `... --subs-only` |
| AI 配音 | `... -AIDub` | `... --ai-dub` |
| 频道监控 | `scripts\yt-monitor.ps1` | `bash scripts/yt-monitor.sh` |
| 获取字幕 | `python scripts/fetch_transcript.py "URL"` | `python3 scripts/fetch_transcript.py "URL"` |
| 渲染总结卡片 | `python scripts/render_cards.py chapters.json --out-dir cards/` | 同左 |
| 双语字幕 | `python scripts/build_bilingual_ass.py transcript.json --out bilingual.ass` | 同左 |
| 合成视频 | `python scripts/compose_video.py --video in.mp4 --audio dub.mp3 --chapters chapters.json --cards-dir cards/ --ass bilingual.ass --out final.mp4` | 同左 |

---

## ⚙️ 配置

编辑 `config.yaml` 或在环境变量中设置：

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `HTTP_PROXY` | HTTP 代理 | `http://127.0.0.1:2080` |
| `YT_DL_DIR` | 下载目录 | `~/youtube-downloads` |

---

## 📦 输出示例

```
桌面/学习笔记产出/
└── 老王来了精选_婚外情的根源_学习笔记/
    ├── 老王来了精选_婚外情的根源_学习笔记.html   ← 学习文档
    ├── 老王来了精选_婚外情的根源.mp4              ← 视频文件
    ├── transcript.json                            ← 字幕文件
    ├── transcript.txt
    └── timestamped.txt
```

---

## 📋 依赖清单

| 工具 | 必需 | 用途 |
|------|:----:|------|
| Python 3.8+ | ✅ | 脚本运行环境 |
| yt-dlp | ✅ | YouTube/B站 下载核心 |
| ffmpeg | ✅ | 音视频处理 |
| youtube-transcript-api | ✅ | 字幕获取 |
| requests | ✅ | 视频元数据 |
| Node.js | ✅ | yt-dlp JS runtime |
| edge-tts | ⭐ | **AI 配音（强烈推荐）** |
| faster-whisper | ❌ | 本地语音识别 |
| pyvideotrans | ❌ | 全自动翻译配音 |

---

## 🌐 跨平台

| 项目 | Windows | macOS/Linux |
|------|---------|-------------|
| Python | `python` | `python3` |
| 下载脚本 | `yt-dl-zh.ps1` | `yt-dl-zh.sh` |
| 配音脚本 | `ai-dub.ps1` | `ai-dub.sh` |
| 桌面路径 | `C:\Users\{用户名}\Desktop\` | `~/Desktop/` |

---

## 📜 许可证

MIT License

---

<div align="center">
  <sub>Made with ❤️ for learners worldwide</sub>
</div>
