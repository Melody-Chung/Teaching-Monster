import html
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SLIDE_WIDTH = 1280
SLIDE_HEIGHT = 720
BACKGROUND_COLOR = "#F4F1EA"
PANEL_COLOR = "#FFFDF8"
ACCENT_COLOR = "#CC6B2C"
TEXT_COLOR = "#1F2933"
MUTED_TEXT_COLOR = "#52606D"
BORDER_COLOR = "#D9C7B8"


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/georgiab.ttf" if bold else "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    text = "" if text is None else str(text)
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font,
    fill: str,
    max_width: int,
    line_gap: int = 8,
) -> int:
    text = "" if text is None else str(text)
    x, y = xy
    lines = _wrap_text(draw, text, font, max_width)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def _truncate(text: str, max_length: int) -> str:
    text = "" if text is None else str(text)
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _safe_str(value) -> str:
    return "" if value is None else str(value)


def _sanitize_display_text(value) -> str:
    text = unicodedata.normalize("NFKC", _safe_str(value))
    replacements = {
        "**": "",
        "__": "",
        "`": "",
        "∝": " proportional to ",
        "×": " x ",
        "·": " * ",
        "•": "-",
        "→": " -> ",
        "⇒": " => ",
        "≤": " <= ",
        "≥": " >= ",
        "≈": " ~ ",
        "²": "^2",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _compact_bullets(items, limit: int = 3, max_length: int = 38) -> list[str]:
    results: list[str] = []
    for item in items or []:
        if not item:
            continue
        results.append(_truncate(_sanitize_display_text(item), max_length))
        if len(results) >= limit:
            break
    return results


def _explanation_blocks(slide: dict) -> list[str]:
    blocks: list[str] = []

    bridge = _truncate(_sanitize_display_text(slide.get("bridge_from_prior", "")), 90)
    if bridge:
        blocks.append(bridge)

    bullets = _compact_bullets(slide.get("onscreen_text", []), limit=2, max_length=28)
    if bullets:
        blocks.extend([f"- {item}" for item in bullets])

    if len(blocks) < 3:
        example = _truncate(_sanitize_display_text(slide.get("analogy_or_example", "")), 72)
        if example:
            blocks.append(f"Example: {example}")

    if len(blocks) < 3:
        focus = _truncate(_sanitize_display_text(slide.get("visual_plan", "")), 68)
        if focus:
            blocks.append(f"Focus: {focus}")

    return blocks[:3]


def prettify_formula(formula: str | None) -> str:
    if not formula:
        return ""

    text = _sanitize_display_text(formula)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1) / (\2)", text)

    replacements = [
        (r"\times", " x "),
        (r"\cdot", " * "),
        (r"\over", " / "),
        (r"\frac", ""),
        (r"\text{net}", "net"),
        (r"\text{", ""),
        ("}", ""),
        ("{", ""),
        ("_", " "),
        ("^2", " squared"),
        ("\\", ""),
    ]
    for source, target in replacements:
        text = text.replace(source, target)

    text = re.sub(r"([A-Za-z0-9]+)_\{([^{}]+)\}", r"\1_\2", text)
    text = re.sub(r"([A-Za-z0-9]+)\^\{([^{}]+)\}", r"\1^\2", text)
    text = re.sub(r"([A-Za-z0-9]+)_([A-Za-z0-9]+)", r"\1 \2", text)
    text = re.sub(r"([A-Za-z0-9]+)\^([A-Za-z0-9]+)", r"\1 \2", text)
    text = text.replace("left", "").replace("right", "")
    return " ".join(text.split())


def _draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], fill: str, width: int = 8):
    draw.line([start, end], fill=fill, width=width)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    arrow_size = 18
    p1 = (end[0] - ux * arrow_size + px * 10, end[1] - uy * arrow_size + py * 10)
    p2 = (end[0] - ux * arrow_size - px * 10, end[1] - uy * arrow_size - py * 10)
    draw.polygon([end, p1, p2], fill=fill)


def _draw_car(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0, body_color: str = "#4C78A8"):
    w = int(150 * scale)
    h = int(48 * scale)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=int(12 * scale), fill=body_color, outline=TEXT_COLOR, width=2)
    roof = [(x + int(28 * scale), y), (x + int(55 * scale), y - int(28 * scale)), (x + int(108 * scale), y - int(28 * scale)), (x + int(126 * scale), y)]
    draw.polygon(roof, fill=body_color, outline=TEXT_COLOR)
    for cx in [x + int(35 * scale), x + int(112 * scale)]:
        draw.ellipse((cx - int(16 * scale), y + h - int(5 * scale), cx + int(16 * scale), y + h + int(27 * scale)), fill="#303030")
        draw.ellipse((cx - int(7 * scale), y + h + int(4 * scale), cx + int(7 * scale), y + h + int(18 * scale)), fill="#C9D1D9")


def _draw_cart(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0, full: bool = False):
    w = int(150 * scale)
    h = int(90 * scale)
    draw.polygon([(x, y), (x + w, y), (x + w - int(16 * scale), y + h), (x + int(24 * scale), y + h)], outline=TEXT_COLOR, fill="#DCE7F5", width=3)
    draw.line((x + w, y, x + w + int(28 * scale), y - int(24 * scale)), fill=TEXT_COLOR, width=3)
    for cx in [x + int(30 * scale), x + int(108 * scale)]:
        draw.ellipse((cx - int(12 * scale), y + h + int(8 * scale), cx + int(12 * scale), y + h + int(32 * scale)), fill="#303030")
    if full:
        draw.rectangle((x + 22, y + 18, x + 62, y + 50), fill="#F29E38", outline=TEXT_COLOR)
        draw.rectangle((x + 70, y + 10, x + 102, y + 44), fill="#7BAE7F", outline=TEXT_COLOR)
        draw.ellipse((x + 106, y + 26, x + 136, y + 56), fill="#D14E36", outline=TEXT_COLOR)


def _draw_ball(draw: ImageDraw.ImageDraw, x: int, y: int, radius: int = 38):
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="#FFFFFF", outline=TEXT_COLOR, width=3)
    draw.arc((x - radius + 12, y - radius + 12, x + radius - 12, y + radius - 12), 20, 160, fill=TEXT_COLOR, width=2)
    draw.arc((x - radius + 8, y - 10, x + radius - 8, y + radius - 2), 200, 340, fill=TEXT_COLOR, width=2)


def _draw_rocket(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0):
    body = (x, y, x + int(70 * scale), y + int(190 * scale))
    draw.rounded_rectangle(body, radius=int(24 * scale), fill="#E9EEF6", outline=TEXT_COLOR, width=3)
    nose = [(x + int(35 * scale), y - int(55 * scale)), (x + int(70 * scale), y + int(20 * scale)), (x, y + int(20 * scale))]
    draw.polygon(nose, fill="#D14E36", outline=TEXT_COLOR)
    draw.polygon([(x, y + int(130 * scale)), (x - int(26 * scale), y + int(178 * scale)), (x, y + int(168 * scale))], fill="#8898AA", outline=TEXT_COLOR)
    draw.polygon([(x + int(70 * scale), y + int(130 * scale)), (x + int(96 * scale), y + int(178 * scale)), (x + int(70 * scale), y + int(168 * scale))], fill="#8898AA", outline=TEXT_COLOR)
    draw.ellipse((x + int(20 * scale), y + int(55 * scale), x + int(50 * scale), y + int(85 * scale)), fill="#8FD3FF", outline=TEXT_COLOR, width=2)
    draw.polygon([(x + int(18 * scale), y + int(190 * scale)), (x + int(52 * scale), y + int(190 * scale)), (x + int(35 * scale), y + int(235 * scale))], fill="#F29E38", outline="#C8711E")


def _draw_scale(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float = 1.0):
    draw.line((x, y + int(120 * scale), x + int(160 * scale), y + int(120 * scale)), fill=TEXT_COLOR, width=5)
    draw.line((x + int(80 * scale), y, x + int(80 * scale), y + int(120 * scale)), fill=TEXT_COLOR, width=5)
    draw.line((x + int(18 * scale), y + int(42 * scale), x + int(142 * scale), y + int(42 * scale)), fill=TEXT_COLOR, width=4)
    for px in [x + int(26 * scale), x + int(134 * scale)]:
        draw.line((px, y + int(42 * scale), px, y + int(80 * scale)), fill=TEXT_COLOR, width=3)
        draw.ellipse((px - int(22 * scale), y + int(80 * scale), px + int(22 * scale), y + int(104 * scale)), outline=TEXT_COLOR, width=3, fill="#F7EBDD")


def _draw_formula_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], formula: str, font):
    draw.rounded_rectangle(box, radius=18, fill="#FFF7EE", outline=ACCENT_COLOR, width=2)
    _draw_wrapped_text(draw, prettify_formula(formula), (box[0] + 18, box[1] + 18), font, TEXT_COLOR, box[2] - box[0] - 36, line_gap=4)


def _draw_scene_force_intro(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], small_font):
    x0, y0, x1, y1 = box
    _draw_car(draw, x0 + 70, y0 + 180, scale=1.15)
    _draw_arrow(draw, (x0 + 290, y0 + 220), (x0 + 470, y0 + 220), ACCENT_COLOR, width=10)
    _draw_arrow(draw, (x0 + 292, y0 + 276), (x0 + 410, y0 + 276), "#2F9E44", width=8)
    draw.text((x0 + 80, y0 + 100), "push", font=small_font, fill=MUTED_TEXT_COLOR)
    draw.text((x0 + 332, y0 + 188), "force", font=small_font, fill=ACCENT_COLOR)
    draw.text((x0 + 322, y0 + 290), "change", font=small_font, fill="#2F9E44")


def _draw_scene_acceleration(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], small_font):
    x0, y0, x1, y1 = box
    panel_w = (x1 - x0 - 60) // 3
    labels = [("speed up", ACCENT_COLOR), ("slow down", "#C94C4C"), ("turn", "#2F9E44")]
    for idx, (label, color) in enumerate(labels):
        px = x0 + 20 + idx * (panel_w + 10)
        py = y0 + 74
        draw.rounded_rectangle((px, py, px + panel_w, py + 210), radius=18, fill="#FFF9F2", outline=BORDER_COLOR, width=2)
        if idx < 2:
            _draw_car(draw, px + 30, py + 104, scale=0.78, body_color="#5B84B1")
            arrow_end = (px + panel_w - 34, py + 128) if idx == 0 else (px + 140, py + 128)
            _draw_arrow(draw, (px + 170, py + 128), arrow_end, color, width=8)
        else:
            _draw_car(draw, px + 26, py + 118, scale=0.72, body_color="#5B84B1")
            draw.arc((px + 126, py + 80, px + 238, py + 196), 190, 310, fill=color, width=8)
        draw.text((px + 18, py + 18), label, font=small_font, fill=color)


def _draw_scene_mass(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], small_font):
    x0, y0, x1, y1 = box
    _draw_cart(draw, x0 + 70, y0 + 130, scale=1.0, full=False)
    _draw_arrow(draw, (x0 + 250, y0 + 190), (x0 + 410, y0 + 190), ACCENT_COLOR, width=9)
    draw.text((x0 + 72, y0 + 92), "light cart", font=small_font, fill=MUTED_TEXT_COLOR)
    _draw_cart(draw, x0 + 70, y0 + 280, scale=1.0, full=True)
    _draw_arrow(draw, (x0 + 250, y0 + 340), (x0 + 355, y0 + 340), ACCENT_COLOR, width=9)
    draw.text((x0 + 72, y0 + 242), "heavy cart", font=small_font, fill=MUTED_TEXT_COLOR)
    draw.text((x0 + 430, y0 + 178), "same push", font=small_font, fill=ACCENT_COLOR)
    draw.text((x0 + 372, y0 + 328), "smaller acceleration", font=small_font, fill="#2F9E44")


def _draw_scene_formula(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], formula: str, small_font, body_font):
    x0, y0, x1, y1 = box
    formula_box = (x0 + 110, y0 + 64, x1 - 110, y0 + 152)
    _draw_formula_card(draw, formula_box, formula, body_font)
    _draw_car(draw, x0 + 100, y0 + 220, scale=0.9)
    _draw_arrow(draw, (x0 + 250, y0 + 254), (x0 + 438, y0 + 254), ACCENT_COLOR, width=10)
    _draw_arrow(draw, (x0 + 250, y0 + 304), (x0 + 385, y0 + 304), "#2F9E44", width=8)
    draw.text((x0 + 100, y0 + 180), "net force", font=small_font, fill=ACCENT_COLOR)
    draw.text((x0 + 100, y0 + 338), "acceleration follows force", font=small_font, fill="#2F9E44")


def _draw_scene_problem(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], formula: str | None, small_font, body_font):
    x0, y0, x1, y1 = box
    _draw_ball(draw, x0 + 150, y0 + 190, radius=42)
    draw.polygon([(x0 + 52, y0 + 196), (x0 + 122, y0 + 164), (x0 + 148, y0 + 210), (x0 + 96, y0 + 240)], fill="#9C6644", outline=TEXT_COLOR)
    _draw_arrow(draw, (x0 + 220, y0 + 188), (x0 + 430, y0 + 188), ACCENT_COLOR, width=10)
    _draw_arrow(draw, (x0 + 220, y0 + 242), (x0 + 378, y0 + 242), "#2F9E44", width=8)
    if formula:
        _draw_formula_card(draw, (x0 + 80, y0 + 292, x1 - 80, y0 + 382), formula, body_font)
    draw.text((x0 + 88, y0 + 120), "known values -> compute force", font=small_font, fill=MUTED_TEXT_COLOR)


def _draw_scene_recap(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], small_font, body_font):
    x0, y0, x1, y1 = box
    _draw_scale(draw, x0 + 86, y0 + 112, scale=0.9)
    _draw_rocket(draw, x0 + 302, y0 + 120, scale=0.72)
    _draw_formula_card(draw, (x0 + 468, y0 + 126, x1 - 48, y0 + 214), "F net = m x a", body_font)
    draw.text((x0 + 74, y0 + 274), "mass resists change", font=small_font, fill=MUTED_TEXT_COLOR)
    draw.text((x0 + 318, y0 + 274), "force drives motion", font=small_font, fill=ACCENT_COLOR)


def _draw_text_explanation_panel(draw: ImageDraw.ImageDraw, slide: dict, box: tuple[int, int, int, int], small_font, body_font):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill="#FAF6EF", outline=BORDER_COLOR, width=2)
    draw.text((x0 + 18, y0 + 16), "Explanation", font=small_font, fill=ACCENT_COLOR)

    text_x = x0 + 28
    text_width = x1 - x0 - 56
    current_y = y0 + 54

    blocks = _explanation_blocks(slide)
    if blocks:
        current_y = _draw_wrapped_text(draw, blocks[0], (text_x, current_y), small_font, MUTED_TEXT_COLOR, text_width, line_gap=5) + 12
        for line in blocks[1:]:
            current_y = _draw_wrapped_text(draw, line, (text_x, current_y), body_font, TEXT_COLOR, text_width, line_gap=6) + 10

    formula = prettify_formula(slide.get("formula"))
    if formula:
        formula_box_top = min(current_y + 6, y1 - 104)
        _draw_formula_card(draw, (text_x, formula_box_top, x1 - 28, formula_box_top + 58), formula, small_font)


def _draw_visual_scene(draw: ImageDraw.ImageDraw, slide: dict, box: tuple[int, int, int, int], small_font, body_font):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill="#FAF6EF", outline=BORDER_COLOR, width=2)
    draw.text((x0 + 18, y0 + 16), "Visual", font=small_font, fill=ACCENT_COLOR)

    blob = f"{slide.get('title', '')} {slide.get('teaching_purpose', '')} {slide.get('visual_plan', '')} {slide.get('analogy_or_example', '')}".lower()

    if any(token in blob for token in ["formula", "newton", "f=ma", "net force"]):
        _draw_scene_formula(draw, box, slide.get("formula") or "F net = m x a", small_font, body_font)
    elif any(token in blob for token in ["problem", "solve", "calculate", "example", "soccer"]):
        _draw_scene_problem(draw, box, slide.get("formula"), small_font, body_font)
    elif any(token in blob for token in ["mass", "inertia", "shopping", "cart"]):
        _draw_scene_mass(draw, box, small_font)
    elif any(token in blob for token in ["acceleration", "speed up", "slow down", "turn", "velocity"]):
        _draw_scene_acceleration(draw, box, small_font)
    elif any(token in blob for token in ["recap", "summary", "everywhere", "real world", "rocket"]):
        _draw_scene_recap(draw, box, small_font, body_font)
    else:
        _draw_scene_force_intro(draw, box, small_font)

    caption = _truncate(slide.get("visual_plan", ""), 56)
    if caption:
        _draw_wrapped_text(draw, caption, (x0 + 24, y1 - 50), small_font, MUTED_TEXT_COLOR, x1 - x0 - 48, line_gap=4)


def build_marp_markdown(outline: dict, storyboard: dict) -> str:
    sections = [
        "---",
        "marp: true",
        "theme: default",
        "paginate: true",
        f'title: "{outline.get("course_title", "Lesson")}"',
        "size: 16:9",
        "---",
        f"# {outline.get('course_title', 'Lesson')}",
        "",
        f"**Audience**: {_safe_str(outline.get('audience_summary', ''))}",
        "",
        "## Learning Goals",
    ]
    for goal in outline.get("teaching_goals", []):
        sections.append(f"- {goal}")

    for slide in storyboard.get("slides", []):
        bullet_items = [str(item) for item in slide.get("onscreen_text", [])[:4] if item]
        sections.extend(
            [
                "---",
                f"# {_safe_str(slide.get('title', 'Slide'))}",
                "",
                f"**Purpose**: {_safe_str(slide.get('teaching_purpose', ''))}",
                "",
                "## Key Points",
                *[f"- {item}" for item in bullet_items],
                "",
                f"**Example**: {_truncate(slide.get('analogy_or_example', ''), 90)}",
                "",
                f"**Recap**: {_truncate(slide.get('mini_recap', ''), 130)}",
            ]
        )
        formula = slide.get("formula")
        if formula:
            sections.extend(["", f"`{prettify_formula(formula)}`"])

    return "\n".join(sections) + "\n"


def build_slides_prompt(storyboard: dict) -> dict:
    slide_prompts = []
    for slide in storyboard.get("slides", []):
        bullet_items = [str(item) for item in slide.get("onscreen_text", [])[:4] if item]
        slide_prompts.append(
            {
                "slide_id": slide.get("slide_id"),
                "title": _safe_str(slide.get("title")),
                "teaching_purpose": _safe_str(slide.get("teaching_purpose")),
                "visual_plan": _safe_str(slide.get("visual_plan")),
                "onscreen_text": bullet_items,
                "formula": _safe_str(slide.get("formula")),
                "cursor_hint": _safe_str(slide.get("cursor_hint")),
                "render_template": "text_explainer_two_column_card",
            }
        )
    return {"render_mode": "html_css_slides", "slides_prompt": slide_prompts}


def build_page_scripts(storyboard: dict) -> dict:
    pages = []
    for slide in storyboard.get("slides", []):
        pages.append(
            {
                "slide_id": slide.get("slide_id"),
                "title": _safe_str(slide.get("title")),
                "narration": _safe_str(slide.get("narration", "")),
                "mini_recap": _safe_str(slide.get("mini_recap", "")),
                "estimated_seconds": int(slide.get("estimated_seconds", 0) or 0),
            }
        )
    return {"page_scripts": pages}


def _focus_point_from_hint(cursor_hint: str | None) -> tuple[int, int]:
    hint = (cursor_hint or "").lower()
    if any(token in hint for token in ["title", "heading", "top"]):
        return (640, 120)
    if any(token in hint for token in ["left", "bullet", "key point", "points", "list"]):
        return (250, 380)
    if any(token in hint for token in ["visual", "diagram", "right"]):
        return (900, 360)
    if any(token in hint for token in ["bridge", "example"]):
        return (880, 470)
    if any(token in hint for token in ["formula", "equation", "math"]):
        return (260, 560)
    if any(token in hint for token in ["recap", "summary", "bottom"]):
        return (640, 630)
    return (900, 360)


def _cursor_offsets_from_hint(cursor_hint: str | None, slide: dict | None = None) -> tuple[tuple[int, int], tuple[int, int]]:
    hint = (cursor_hint or "").lower()
    blob = f"{(slide or {}).get('title', '')} {(slide or {}).get('visual_plan', '')}".lower()

    if any(token in hint for token in ["title", "heading", "top"]):
        return ((-120, 40), (100, 20))
    if any(token in hint for token in ["left", "bullet", "key point", "points", "list"]):
        return ((80, -70), (40, 110))
    if any(token in hint for token in ["formula", "equation", "math"]):
        return ((-90, -40), (110, -10))
    if any(token in hint for token in ["recap", "summary", "bottom"]):
        return ((-130, -30), (120, -20))
    if any(token in hint for token in ["right", "visual", "diagram"]):
        return ((-140, -70), (90, 70))
    if any(token in blob for token in ["acceleration", "turn", "speed"]):
        return ((-150, -20), (140, -10))
    if any(token in blob for token in ["mass", "cart", "inertia"]):
        return ((120, -40), (-100, 70))
    if any(token in blob for token in ["rocket", "launch"]):
        return ((-80, 110), (40, -130))
    return ((-120, -80), (80, 60))


def build_mouse_paths(storyboard: dict, slide_durations: list[float]) -> dict:
    slides = storyboard.get("slides", [])
    cursor_tracks = []
    current_time = 0.0

    for index, slide in enumerate(slides):
        duration = slide_durations[index] if index < len(slide_durations) else 6.0
        focus_x, focus_y = _focus_point_from_hint(slide.get("cursor_hint"))
        (entry_dx, entry_dy), (exit_dx, exit_dy) = _cursor_offsets_from_hint(slide.get("cursor_hint"), slide)
        entry_x = min(max(90, focus_x + entry_dx), SLIDE_WIDTH - 90)
        entry_y = min(max(110, focus_y + entry_dy), SLIDE_HEIGHT - 90)
        exit_x = min(max(90, focus_x + exit_dx), SLIDE_WIDTH - 90)
        exit_y = min(max(110, focus_y + exit_dy), SLIDE_HEIGHT - 90)

        cursor_tracks.append(
            {
                "slide_id": slide.get("slide_id"),
                "cursor_hint": slide.get("cursor_hint", ""),
                "start_seconds": round(current_time, 3),
                "end_seconds": round(current_time + duration, 3),
                "points": [
                    {"t": 0.0, "x": entry_x, "y": entry_y},
                    {"t": round(duration * 0.35, 3), "x": focus_x, "y": focus_y},
                    {"t": round(duration * 0.75, 3), "x": exit_x, "y": exit_y},
                ],
            }
        )
        current_time += duration

    return {"mouse_path": cursor_tracks}


def build_slide_html(outline: dict, storyboard: dict) -> str:
    cards = []
    for slide in storyboard.get("slides", []):
        bullet_items = _compact_bullets(slide.get("onscreen_text", []), limit=3, max_length=24)
        bullets = "".join(f"<li>{html.escape(item)}</li>" for item in bullet_items)
        formula = slide.get("formula")
        formula_html = f"<div class='formula'>{html.escape(prettify_formula(formula))}</div>" if formula else ""
        explanation_items = _explanation_blocks(slide)
        explanation_html = "".join(
            f"<p>{html.escape(item)}</p>" for item in explanation_items
        )
        cards.append(
            f"""
            <section class="slide">
              <div class="eyebrow">{html.escape(_safe_str(slide.get("teaching_purpose", "")))}</div>
              <h2>{html.escape(_safe_str(slide.get("title", "Slide")))}</h2>
              <div class="columns">
                <div class="left">
                  <p class="hook">{html.escape(_truncate(_sanitize_display_text(slide.get("narrative_hook", "")), 72))}</p>
                  <ul>{bullets}</ul>
                  {formula_html}
                  <p class="recap">{html.escape(_truncate(_sanitize_display_text(slide.get("mini_recap", "")), 72))}</p>
                </div>
                <div class="right visual-panel text-panel">
                  <div class="visual-title">Explanation</div>
                  {explanation_html}
                </div>
              </div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(_safe_str(outline.get("course_title", "Lesson")))}</title>
  <style>
    :root {{
      --bg: {BACKGROUND_COLOR};
      --panel: {PANEL_COLOR};
      --accent: {ACCENT_COLOR};
      --text: {TEXT_COLOR};
      --muted: {MUTED_TEXT_COLOR};
      --border: {BORDER_COLOR};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(135deg, #f7f1e8, #f1e7dc);
      color: var(--text);
      font-family: Georgia, "Segoe UI", serif;
      padding: 32px;
    }}
    .deck {{
      display: grid;
      gap: 28px;
    }}
    .slide {{
      width: 1280px;
      min-height: 720px;
      margin: 0 auto;
      background: var(--panel);
      border: 2px solid var(--border);
      border-radius: 28px;
      padding: 42px 48px;
      box-shadow: 0 18px 60px rgba(82, 69, 55, 0.12);
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 18px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 14px;
    }}
    h1, h2 {{ margin: 0 0 18px 0; }}
    h2 {{ font-size: 40px; }}
    .columns {{
      display: grid;
      grid-template-columns: 0.8fr 1.2fr;
      gap: 24px;
    }}
    ul {{ padding-left: 22px; line-height: 1.45; font-size: 24px; }}
    p {{ line-height: 1.5; font-size: 22px; }}
    .hook {{ font-size: 24px; color: var(--muted); }}
    .formula {{
      margin: 16px 0;
      padding: 16px 18px;
      border-left: 6px solid var(--accent);
      background: #fff7ee;
      font-family: "Courier New", monospace;
      font-size: 22px;
    }}
    .recap {{
      margin-top: 18px;
      padding: 18px 20px;
      border-radius: 18px;
      background: #fcf4ea;
    }}
    .visual-panel {{
      min-height: 430px;
      border: 2px solid var(--border);
      border-radius: 24px;
      background: linear-gradient(180deg, #fbf7f0, #f5ede1);
      padding: 20px 24px;
    }}
    .text-panel p {{
      font-size: 21px;
      margin: 0 0 14px 0;
    }}
    .visual-title {{
      color: var(--accent);
      font-size: 18px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 12px;
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <main class="deck">
    {''.join(cards)}
  </main>
</body>
</html>
"""


def render_storyboard_to_images(storyboard: dict, output_dir: str) -> list[str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    title_font = _load_font(38, bold=True)
    eyebrow_font = _load_font(18, bold=True)
    body_font = _load_font(24)
    small_font = _load_font(20)
    recap_font = _load_font(22)

    image_paths: list[str] = []

    for index, slide in enumerate(storyboard.get("slides", []), start=1):
        image = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), BACKGROUND_COLOR)
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((36, 30, SLIDE_WIDTH - 36, SLIDE_HEIGHT - 30), radius=28, fill=PANEL_COLOR, outline=BORDER_COLOR, width=3)
        draw.rounded_rectangle((52, 48, SLIDE_WIDTH - 52, 108), radius=18, fill="#FFF5EA")
        draw.text((74, 66), _truncate(_sanitize_display_text(slide.get("teaching_purpose", "")).upper(), 74), font=eyebrow_font, fill=ACCENT_COLOR)
        draw.text((72, 120), _truncate(_sanitize_display_text(slide.get("title", f"Slide {index}")), 34), font=title_font, fill=TEXT_COLOR)

        left_x = 78
        left_width = 320
        right_x = 470
        top_y = 205
        visual_box = (right_x, 182, 1206, 500)

        hook_box = (left_x, top_y, left_x + left_width, top_y + 88)
        draw.rounded_rectangle(hook_box, radius=18, fill="#F7EBDD")
        _draw_wrapped_text(draw, _truncate(_sanitize_display_text(slide.get("narrative_hook", "")), 72), (left_x + 18, top_y + 16), small_font, MUTED_TEXT_COLOR, left_width - 36, line_gap=5)

        bullet_y = top_y + 122
        for item in _compact_bullets(slide.get("onscreen_text", []), limit=3, max_length=24):
            draw.ellipse((left_x, bullet_y + 12, left_x + 10, bullet_y + 22), fill=ACCENT_COLOR)
            bullet_y = _draw_wrapped_text(draw, item, (left_x + 24, bullet_y), body_font, TEXT_COLOR, left_width - 24, line_gap=6) + 8

        formula = slide.get("formula")
        if formula:
            formula_top = min(max(bullet_y + 8, 448), 478)
            formula_box = (left_x, formula_top, left_x + left_width, formula_top + 64)
            _draw_formula_card(draw, formula_box, formula, small_font)

        _draw_text_explanation_panel(draw, slide, visual_box, eyebrow_font, body_font)

        recap_top = 568
        recap_bottom = SLIDE_HEIGHT - 82
        recap_box = (64, recap_top, SLIDE_WIDTH - 64, recap_bottom)
        draw.rounded_rectangle(recap_box, radius=22, fill="#FCF4EA")
        draw.text((84, recap_top + 16), "Mini Recap", font=eyebrow_font, fill=ACCENT_COLOR)
        _draw_wrapped_text(draw, _truncate(_sanitize_display_text(slide.get("mini_recap", "")), 72), (84, recap_top + 46), recap_font, TEXT_COLOR, SLIDE_WIDTH - 168, line_gap=6)

        image_path = output_path / f"slide_{index:02}.png"
        image.save(image_path)
        image_paths.append(str(image_path))

    return image_paths
