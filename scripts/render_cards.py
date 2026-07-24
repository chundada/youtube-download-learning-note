#!/usr/bin/env python3
"""
章节总结卡片渲染器 — 把 chapters.json 渲染成透明背景 PNG 卡片
================================================================

用法:
  python render_cards.py chapters.json --out-dir cards/
  python render_cards.py chapters.json --out-dir cards/ --size 1920x1080

输入（chapters.json，由 AI 在 Phase 2.5 生成，契约固定）:
  [
    {
      "index": 1,
      "start": 0.0,
      "end": 200.0,
      "title": "科学世界观的奠基",
      "points": ["要点一", "要点二", "要点三"]
    },
    ...
  ]

输出（--out-dir 目录）:
  cards/card_001.png   ← 第 1 章（按 start 排序后的顺序）
  cards/card_002.png   ← 第 2 章
  ...

视觉效果:
  - 整幅 1920x1080 透明背景（直接 overlay 到压暗模糊的原画面上）
  - 卡片居中偏右，约占画面宽 60%
  - 深藏青半透明圆角卡片 RGBA(15,23,42,220)
  - 金色标题 #E8C766 + 金色下划线
  - 白色要点列表，每条前加「•」，自动换行，最多 4 条

中文字体回退链:
  C:\\Windows\\Fonts\\msyh.ttc (微软雅黑) → simhei.ttf → simsun.ttc → Pillow 默认字体

依赖:
  pip install pillow
"""

import argparse
import json
import platform
import sys
from pathlib import Path

# ─── 视觉常量 ─────────────────────────────────

CARD_BG = (15, 23, 42, 220)        # 深藏青半透明卡片
CARD_BORDER = (232, 199, 102, 90)  # 金色细边
GOLD = (232, 199, 102, 255)        # #E8C766 标题金
WHITE = (255, 255, 255, 242)       # 要点白
CARD_RADIUS = 28                   # 圆角半径
MAX_POINTS = 4                     # 每张卡片最多要点数

# 中文字体回退链（Windows 优先，兼顾 macOS / Linux）
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",        # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",      # 黑体
    r"C:\Windows\Fonts\simsun.ttc",      # 宋体
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def ensure_utf8_stdio():
    """确保 stdout 输出 UTF-8（只在 Windows + 非重定向时包装）"""
    if platform.system() == "Windows" and hasattr(sys.stdout, "buffer"):
        sys.stdout = open(
            sys.stdout.buffer.fileno(),
            mode="w", encoding="utf-8", errors="replace",
            buffering=1, closefd=False,
        )


def _import_pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ImportError:
        print("[X] 缺少依赖：pillow")
        print("   安装：pip install pillow")
        sys.exit(1)


# ─── 字体加载 ─────────────────────────────────


def find_font_path() -> str | None:
    """按回退链找第一个存在的中文字体"""
    for p in FONT_CANDIDATES:
        if Path(p).is_file():
            return p
    return None


def load_font(ImageFont, size: int):
    """加载字体；找不到中文字体时回退 Pillow 默认并警告"""
    font_path = find_font_path()
    if font_path:
        try:
            return ImageFont.truetype(font_path, size), font_path
        except Exception as e:
            print(f"  [警告] 字体加载失败 {font_path}: {e}，尝试下一个")
    try:
        return ImageFont.load_default(size=size), None
    except TypeError:
        # 老版本 Pillow 的 load_default 不支持 size
        return ImageFont.load_default(), None


# ─── 文本换行 ─────────────────────────────────


def wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """逐字符贪心换行（兼容中文无空格与英文单词）"""
    lines: list[str] = []
    for para in str(text).split("\n"):
        para = para.strip()
        if not para:
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines or [""]


# ─── 单张卡片渲染 ─────────────────────────────


def render_card(chapter: dict, size: tuple[int, int], out_path: Path):
    """渲染一章的总结卡片为透明背景 PNG"""
    Image, ImageDraw, ImageFont = _import_pil()
    W, H = size
    scale = H / 1080.0  # 所有尺寸按 1080p 基准缩放

    title_font, _ = load_font(ImageFont, int(54 * scale))
    point_font, _ = load_font(ImageFont, int(36 * scale))

    # 整幅透明画布
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── 卡片几何：宽约 60%，水平中心偏右（画面 55% 处）──
    card_w = int(W * 0.60)
    pad = int(56 * scale)
    inner_w = card_w - pad * 2

    title = str(chapter.get("title", "")).strip()
    points = [str(p).strip() for p in (chapter.get("points") or []) if str(p).strip()]
    points = points[:MAX_POINTS]

    # ── 预先排版，计算卡片高度 ──
    title_lines = wrap_text(draw, title, title_font, inner_w)[:2]
    title_lh = int(54 * scale * 1.35)
    underline_gap = int(22 * scale)   # 标题到下划线的距离
    underline_h = max(3, int(4 * scale))
    after_underline_gap = int(30 * scale)

    point_lh = int(36 * scale * 1.55)
    point_gap = int(16 * scale)       # 要点之间的额外间距

    wrapped_points: list[list[str]] = []
    for p in points:
        wrapped_points.append(wrap_text(draw, "• " + p, point_font, inner_w))

    content_h = (
        len(title_lines) * title_lh
        + underline_gap + underline_h + after_underline_gap
        + sum(len(ls) * point_lh for ls in wrapped_points)
        + max(0, len(wrapped_points) - 1) * point_gap
    )
    card_h = content_h + pad * 2

    cx = int(W * 0.55)                # 卡片水平中心（偏右）
    x0 = cx - card_w // 2
    y0 = (H - card_h) // 2            # 垂直居中
    x1, y1 = x0 + card_w, y0 + card_h

    # ── 卡片底 ──
    draw.rounded_rectangle([x0, y0, x1, y1], radius=CARD_RADIUS, fill=CARD_BG)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=CARD_RADIUS,
                           outline=CARD_BORDER, width=max(1, int(2 * scale)))

    # ── 标题（金色）──
    ty = y0 + pad
    for line in title_lines:
        lw = draw.textlength(line, font=title_font)
        draw.text((cx - lw / 2, ty), line, font=title_font, fill=GOLD)
        ty += title_lh

    # ── 金色下划线 ──
    uy = ty + underline_gap - title_lh // 4
    ul_w = min(int(inner_w * 0.4), int(W * 0.18))
    draw.rectangle([cx - ul_w // 2, uy, cx + ul_w // 2, uy + underline_h], fill=GOLD)

    # ── 要点（白色，「• 」前缀，续行缩进）──
    py = uy + underline_h + after_underline_gap
    for lines in wrapped_points:
        for i, line in enumerate(lines):
            draw.text((x0 + pad, py), line, font=point_font, fill=WHITE)
            py += point_lh
        py += point_gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


# ─── 工具 ─────────────────────────────────


def fmt_time(sec: float) -> str:
    """秒 → 分:秒"""
    sec = max(0.0, float(sec))
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def parse_size(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except Exception:
        print(f"[X] 无法解析尺寸：{s}（应为 1920x1080 格式）")
        sys.exit(1)


# ─── CLI ─────────────────────────────────


def main():
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="章节总结卡片渲染器（chapters.json → 透明背景 PNG 卡片）",
        epilog="示例：python render_cards.py chapters.json --out-dir cards/",
    )
    parser.add_argument("chapters", help="chapters.json 路径")
    parser.add_argument("--out-dir", "-o", default="cards", help="输出目录（默认：cards/）")
    parser.add_argument("--size", default="1920x1080", help="画布尺寸（默认：1920x1080）")
    args = parser.parse_args()

    chapters_path = Path(args.chapters)
    if not chapters_path.is_file():
        print(f"[X] 找不到章节文件：{chapters_path}")
        sys.exit(1)

    chapters = json.loads(chapters_path.read_text(encoding="utf-8"))
    if not isinstance(chapters, list) or not chapters:
        print("[X] chapters.json 应为非空列表")
        sys.exit(1)
    chapters = sorted(chapters, key=lambda c: float(c.get("start", 0)))

    size = parse_size(args.size)
    out_dir = Path(args.out_dir)

    font_path = find_font_path()
    print(f"[字体] {font_path or 'Pillow 默认字体（中文可能无法显示！）'}")

    print(f"[渲染] {len(chapters)} 张卡片 → {out_dir}/ ({size[0]}x{size[1]})")
    for i, ch in enumerate(chapters, 1):
        out_path = out_dir / f"card_{i:03d}.png"
        render_card(ch, size, out_path)
        print(f"  [OK] {out_path}  [{fmt_time(ch.get('start', 0))} - {fmt_time(ch.get('end', 0))}]  {ch.get('title', '')}")

    print("\n[完成] 卡片渲染完毕，可在 compose_video.py 中按时间段叠加。")


if __name__ == "__main__":
    main()
