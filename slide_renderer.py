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
    max_lines: int | None = None,
) -> int:
    text = "" if text is None else str(text)
    x, y = xy
    lines = _wrap_text(draw, text, font, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
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


def _truncate_clean(text: str, max_length: int) -> str:
    text = "" if text is None else str(text)
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    trimmed = text[:max_length].rstrip(" ,.;:-")
    return trimmed


def _safe_str(value) -> str:
    return "" if value is None else str(value)


def _font_size_for_length(text: str, default: int, medium_threshold: int, small_threshold: int, medium_size: int, small_size: int) -> int:
    length = len((text or "").strip())
    if length >= small_threshold:
        return small_size
    if length >= medium_threshold:
        return medium_size
    return default


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


def _sanitize_display_text(value) -> str:
    text = unicodedata.normalize("NFKC", _safe_str(value))
    replacements = {
        "**": "",
        "__": "",
        "`": "",
        "∝": " proportional to ",
        "□": " proportional to ",
        "×": " x ",
        "·": " * ",
        "•": "- ",
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
        "…": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\.{3,}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sanitize_display_text(value) -> str:
    text = unicodedata.normalize("NFKC", _safe_str(value))
    replacements = {
        "**": "",
        "__": "",
        "`": "",
        "∝": " proportional to ",
        "□": " proportional to ",
        "×": " x ",
        "·": " * ",
        "•": "- ",
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
        "…": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\.{3,}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fit_text_block(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> str:
    clean = _sanitize_display_text(text)
    lines = _wrap_text(draw, clean, font, max_width)
    return "\n".join(lines[:max_lines]).strip()


def _compact_bullets(items, limit: int = 3, max_length: int = 38) -> list[str]:
    results: list[str] = []
    for item in items or []:
        if not item:
            continue
        results.append(_truncate_clean(_sanitize_display_text(item), max_length))
        if len(results) >= limit:
            break
    return results


def _explanation_blocks(slide: dict) -> list[str]:
    blocks: list[str] = []

    bullets = _compact_bullets(slide.get("onscreen_text", []), limit=2, max_length=22)
    if bullets:
        blocks.extend([f"- {item}" for item in bullets])

    if len(blocks) < 2:
        example = _truncate_clean(_sanitize_display_text(slide.get("analogy_or_example", "")), 52)
        if example:
            blocks.append(f"Example: {example}")

    return blocks[:2]


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


def _is_geometry_slide(slide: dict) -> bool:
    blob = _sanitize_display_text(
        f"{slide.get('title', '')} {slide.get('teaching_purpose', '')} {slide.get('visual_plan', '')} {slide.get('analogy_or_example', '')}"
    ).lower()
    geometry_tokens = [
        "triangle",
        "incenter",
        "circumcenter",
        "centroid",
        "orthocenter",
        "angle bisector",
        "perpendicular bisector",
        "incircle",
        "circumcircle",
        "vertex",
        "vertices",
    ]
    return any(token in blob for token in geometry_tokens)


def _draw_geometry_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], slide: dict, small_font, body_font):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill="#FAF6EF", outline=BORDER_COLOR, width=2)
    draw.text((x0 + 18, y0 + 16), "Geometry Focus", font=small_font, fill=ACCENT_COLOR)

    ax, ay = x0 + 120, y0 + 260
    bx, by = x0 + 310, y0 + 95
    cx, cy = x0 + 505, y0 + 270
    draw.polygon([(ax, ay), (bx, by), (cx, cy)], outline="#4C78A8", width=5, fill="#F7FBFF")

    incenter = (x0 + 315, y0 + 205)
    circumcenter = (x0 + 315, y0 + 165)
    centroid = (x0 + 317, y0 + 210)

    blob = _sanitize_display_text(
        f"{slide.get('title', '')} {slide.get('visual_plan', '')} {slide.get('onscreen_text', '')}"
    ).lower()
    show_incenter = "incenter" in blob or "incircle" in blob
    show_circumcenter = "circumcenter" in blob or "circumcircle" in blob

    if show_incenter:
        draw.line([incenter, (ax + bx) // 2, (ay + by) // 2], fill="#2F9E44", width=3)
        draw.line([incenter, (bx + cx) // 2, (by + cy) // 2], fill="#2F9E44", width=3)
        draw.line([incenter, (ax + cx) // 2, (ay + cy) // 2], fill="#2F9E44", width=3)
        r = 48
        draw.ellipse((incenter[0] - r, incenter[1] - r, incenter[0] + r, incenter[1] + r), outline="#2F9E44", width=3)
        draw.ellipse((incenter[0] - 7, incenter[1] - 7, incenter[0] + 7, incenter[1] + 7), fill="#2F9E44")
        draw.text((incenter[0] + 14, incenter[1] + 2), "Incenter", font=small_font, fill="#2F9E44")

    if show_circumcenter:
        radius = 102
        draw.ellipse((circumcenter[0] - radius, circumcenter[1] - radius, circumcenter[0] + radius, circumcenter[1] + radius), outline="#C94C4C", width=3)
        draw.line((circumcenter[0], circumcenter[1], (ax + bx) // 2, (ay + by) // 2), fill="#C94C4C", width=2)
        draw.line((circumcenter[0], circumcenter[1], (bx + cx) // 2, (by + cy) // 2), fill="#C94C4C", width=2)
        draw.line((circumcenter[0], circumcenter[1], (ax + cx) // 2, (ay + cy) // 2), fill="#C94C4C", width=2)
        draw.ellipse((circumcenter[0] - 7, circumcenter[1] - 7, circumcenter[0] + 7, circumcenter[1] + 7), fill="#C94C4C")
        draw.text((circumcenter[0] + 14, circumcenter[1] - 22), "Circumcenter", font=small_font, fill="#C94C4C")

    if not show_incenter and not show_circumcenter:
        draw.ellipse((centroid[0] - 7, centroid[1] - 7, centroid[0] + 7, centroid[1] + 7), fill=ACCENT_COLOR)
        draw.text((centroid[0] + 14, centroid[1] - 10), "Center", font=small_font, fill=ACCENT_COLOR)

    for label, (px, py) in {"A": (ax, ay), "B": (bx, by), "C": (cx, cy)}.items():
        draw.text((px - 18, py + 10), label, font=small_font, fill=TEXT_COLOR)

    explanation = _explanation_blocks(slide)
    text_y = y0 + 286
    for line in explanation[:2]:
        text_y = _draw_wrapped_text(draw, line, (x0 + 34, text_y), body_font, TEXT_COLOR, x1 - x0 - 68, line_gap=6, max_lines=2) + 8


def _layout_variant(slide: dict) -> int:
    key = _safe_str(slide.get("slide_id") or slide.get("title") or "slide")
    return sum(ord(ch) for ch in key) % 3


def _draw_summary_panel(draw: ImageDraw.ImageDraw, slide: dict, box: tuple[int, int, int, int], small_font, body_font):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=22, fill="#FFF8EF", outline=BORDER_COLOR, width=2)
    draw.text((x0 + 16, y0 + 14), "Takeaway", font=small_font, fill=ACCENT_COLOR)
    current_y = y0 + 48
    for line in _explanation_blocks(slide)[:2]:
        current_y = _draw_wrapped_text(draw, line, (x0 + 18, current_y), body_font, TEXT_COLOR, x1 - x0 - 36, line_gap=5, max_lines=2) + 8


def _draw_primary_panel(draw: ImageDraw.ImageDraw, slide: dict, box: tuple[int, int, int, int], small_font, body_font):
    if _is_geometry_slide(slide):
        _draw_geometry_panel(draw, box, slide, small_font, body_font)
    else:
        _draw_visual_scene(draw, slide, box, small_font, body_font)


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
    draw.text((x0 + 18, y0 + 16), "Key Idea", font=small_font, fill=ACCENT_COLOR)

    text_x = x0 + 28
    text_width = x1 - x0 - 56
    current_y = y0 + 54

    blocks = _explanation_blocks(slide)
    if blocks:
        current_y = _draw_wrapped_text(draw, blocks[0], (text_x, current_y), small_font, MUTED_TEXT_COLOR, text_width, line_gap=5, max_lines=2) + 12
        for line in blocks[1:]:
            current_y = _draw_wrapped_text(draw, line, (text_x, current_y), body_font, TEXT_COLOR, text_width, line_gap=6, max_lines=2) + 10

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

    caption = _truncate_clean(_sanitize_display_text(slide.get("visual_plan", "")), 40)
    if caption:
        _draw_wrapped_text(draw, caption, (x0 + 24, y1 - 50), small_font, MUTED_TEXT_COLOR, x1 - x0 - 48, line_gap=4, max_lines=1)


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
                f"**Example**: {_truncate_clean(slide.get('analogy_or_example', ''), 90)}",
                "",
                f"**Recap**: {_truncate_clean(slide.get('mini_recap', ''), 130)}",
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


def _clamp_cursor_point(x: float, y: float) -> tuple[int, int]:
    return (
        int(min(max(round(x), 90), SLIDE_WIDTH - 90)),
        int(min(max(round(y), 110), SLIDE_HEIGHT - 90)),
    )


def _prioritize_anchor_names(slide: dict, available_names: list[str]) -> list[str]:
    narration = _sanitize_display_text(slide.get("narration", "")).lower()
    hint = _safe_str(slide.get("cursor_hint", "")).lower()
    ordered: list[str] = []

    def add(name: str):
        if name in available_names and name not in ordered:
            ordered.append(name)

    if "title" in hint or "heading" in hint:
        add("title")

    if any(token in narration for token in ["question", "wonder", "why", "hook"]):
        add("hook")

    if any(token in narration for token in ["first", "start", "begin"]):
        add("hook")
        add("bullet1")

    if any(token in narration for token in ["second", "next", "then"]):
        add("bullet2")

    if any(token in narration for token in ["third", "finally", "last"]):
        add("bullet3")

    if any(token in narration for token in ["formula", "equation", "f = ma", "f=ma", "calculate"]):
        add("formula")

    if any(token in narration for token in ["example", "imagine", "look at", "diagram", "triangle", "visual"]):
        add("visual1")
        add("visual2")

    if any(token in narration for token in ["incenter", "incircle"]):
        add("visual1")
    if any(token in narration for token in ["circumcenter", "circumcircle"]):
        add("visual2")
    if any(token in narration for token in ["summary", "recap", "remember"]):
        add("recap")

    for fallback in available_names:
        add(fallback)
    return ordered


def _ordered_cursor_anchors(slide: dict) -> list[tuple[int, int]]:
    variant = _layout_variant(slide)
    geometry = _is_geometry_slide(slide)
    named_anchors: dict[str, tuple[int, int]] = {}

    named_anchors["title"] = (260, 145)
    named_anchors["hook"] = (220, 255)
    bullet_count = len(_compact_bullets(slide.get("onscreen_text", []), limit=3, max_length=24))
    for idx in range(max(bullet_count, 1)):
        named_anchors[f"bullet{idx + 1}"] = (220, 350 + idx * 64)
    named_anchors["formula"] = (230, 520)
    named_anchors["recap"] = (250, 625)

    if geometry:
        named_anchors["visual1"] = (790, 230)
        named_anchors["visual2"] = (935, 240)
        named_anchors["visual3"] = (880, 360)
    elif variant == 0:
        named_anchors["visual1"] = (820, 255)
        named_anchors["visual2"] = (960, 320)
    elif variant == 1:
        named_anchors["visual1"] = (845, 250)
        named_anchors["visual2"] = (850, 485)
    else:
        named_anchors["visual1"] = (640, 310)
        named_anchors["visual2"] = (1010, 310)

    hint = _safe_str(slide.get("cursor_hint", "")).lower()
    anchor_names: list[str] = []
    if any(token in hint for token in ["visual", "diagram", "figure", "triangle"]):
        anchor_names.extend(["hook", "visual1", "visual2", "bullet1", "bullet2"])
    elif any(token in hint for token in ["formula", "equation", "math"]):
        anchor_names.extend(["hook", "bullet1", "formula", "visual1"])
    else:
        anchor_names.extend(["hook", "bullet1", "bullet2", "visual1", "visual2"])
        if slide.get("formula"):
            anchor_names.append("formula")
    if "recap" in hint or "summary" in hint:
        anchor_names.append("recap")

    prioritized_names = _prioritize_anchor_names(slide, anchor_names + list(named_anchors.keys()))

    deduped: list[tuple[int, int]] = []
    seen = set()
    for name in prioritized_names:
        if name not in named_anchors:
            continue
        x, y = named_anchors[name]
        point = _clamp_cursor_point(x, y)
        if point not in seen:
            deduped.append(point)
            seen.add(point)
    return deduped[:6]


def build_mouse_paths(storyboard: dict, slide_durations: list[float]) -> dict:
    slides = storyboard.get("slides", [])
    cursor_tracks = []
    current_time = 0.0

    for index, slide in enumerate(slides):
        duration = slide_durations[index] if index < len(slide_durations) else 6.0
        anchors = _ordered_cursor_anchors(slide)
        focus_x, focus_y = anchors[0] if anchors else _focus_point_from_hint(slide.get("cursor_hint"))
        (entry_dx, entry_dy), (exit_dx, exit_dy) = _cursor_offsets_from_hint(slide.get("cursor_hint"), slide)
        entry_x, entry_y = _clamp_cursor_point(focus_x + entry_dx, focus_y + entry_dy)
        last_anchor_x, last_anchor_y = anchors[-1] if anchors else (focus_x, focus_y)
        exit_x, exit_y = _clamp_cursor_point(last_anchor_x + exit_dx, last_anchor_y + exit_dy)
        interior_points = anchors or [_clamp_cursor_point(focus_x, focus_y)]
        if len(interior_points) == 1:
            anchor_times = [round(duration * 0.5, 3)]
        else:
            anchor_times = [
                round(duration * (0.18 + 0.64 * (idx / (len(interior_points) - 1))), 3)
                for idx in range(len(interior_points))
            ]

        points = [{"t": 0.0, "x": entry_x, "y": entry_y}]
        for t, (x, y) in zip(anchor_times, interior_points):
            points.append({"t": t, "x": x, "y": y})
        points.append({"t": round(duration * 0.92, 3), "x": exit_x, "y": exit_y})

        cursor_tracks.append(
            {
                "slide_id": slide.get("slide_id"),
                "cursor_hint": slide.get("cursor_hint", ""),
                "start_seconds": round(current_time, 3),
                "end_seconds": round(current_time + duration, 3),
                "points": points,
            }
        )
        current_time += duration

    return {"mouse_path": cursor_tracks}


def build_slide_html(outline: dict, storyboard: dict) -> str:
    cards = []
    for slide in storyboard.get("slides", []):
        variant = _layout_variant(slide)
        bullet_items = _compact_bullets(slide.get("onscreen_text", []), limit=3, max_length=40)
        bullets = "".join(f"<li>{html.escape(item)}</li>" for item in bullet_items)
        formula = slide.get("formula")
        formula_html = f"<div class='formula'>{html.escape(prettify_formula(formula))}</div>" if formula else ""
        explanation_items = _explanation_blocks(slide)
        explanation_html = "".join(
            f"<p>{html.escape(item)}</p>" for item in explanation_items
        )
        slide_class = f"variant-{variant}"
        cards.append(
            f"""
            <section class="slide {slide_class}">
              <div class="eyebrow">{html.escape(_safe_str(slide.get("teaching_purpose", "")))}</div>
              <h2>{html.escape(_safe_str(slide.get("title", "Slide")))}</h2>
              <div class="columns">
                <div class="left">
                  <p class="hook">{html.escape(_sanitize_display_text(slide.get("narrative_hook", "")))}</p>
                  <ul>{bullets}</ul>
                  {formula_html}
                  <p class="recap">{html.escape(_sanitize_display_text(slide.get("mini_recap", "")))}</p>
                </div>
                <div class="right visual-panel text-panel">
                  <div class="visual-title">Key Idea</div>
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
      font-size: 20px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 14px;
      white-space: nowrap;
      overflow: hidden;
    }}
    h1, h2 {{ margin: 0 0 18px 0; }}
    h2 {{
      font-size: 46px;
      line-height: 1.15;
      max-height: 2.3em;
      overflow: hidden;
    }}
    .columns {{
      display: grid;
      grid-template-columns: 0.8fr 1.2fr;
      gap: 24px;
      align-items: start;
    }}
    ul {{ padding-left: 24px; line-height: 1.45; font-size: 28px; }}
    li {{
      margin-bottom: 10px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    p {{ line-height: 1.5; font-size: 25px; }}
    .hook {{
      font-size: 27px;
      color: var(--muted);
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .formula {{
      margin: 16px 0;
      padding: 16px 18px;
      border-left: 6px solid var(--accent);
      background: #fff7ee;
      font-family: "Courier New", monospace;
      font-size: 26px;
    }}
    .recap {{
      margin-top: 18px;
      padding: 18px 20px;
      border-radius: 18px;
      background: #fcf4ea;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .visual-panel {{
      min-height: 430px;
      border: 2px solid var(--border);
      border-radius: 24px;
      background: linear-gradient(180deg, #fbf7f0, #f5ede1);
      padding: 20px 24px;
    }}
    .text-panel p {{
      font-size: 24px;
      margin: 0 0 14px 0;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .visual-title {{
      color: var(--accent);
      font-size: 20px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 12px;
      font-weight: 700;
    }}
    .variant-1 .columns {{
      grid-template-columns: 0.72fr 1.28fr;
    }}
    .variant-2 .columns {{
      grid-template-columns: 0.9fr 1.1fr;
    }}
    .variant-2 .visual-panel {{
      background: linear-gradient(180deg, #fffaf2, #f6efe3);
      border-style: dashed;
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

    base_body_font = _load_font(28)
    base_small_font = _load_font(23)
    base_recap_font = _load_font(25)

    image_paths: list[str] = []

    for index, slide in enumerate(storyboard.get("slides", []), start=1):
        image = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), BACKGROUND_COLOR)
        draw = ImageDraw.Draw(image)
        variant = _layout_variant(slide)
        title_text = _sanitize_display_text(slide.get("title", f"Slide {index}"))
        purpose_text = _sanitize_display_text(slide.get("teaching_purpose", "")).upper()
        hook_text = _sanitize_display_text(slide.get("narrative_hook", ""))
        recap_text = _sanitize_display_text(slide.get("mini_recap", ""))

        title_font = _load_font(_font_size_for_length(title_text, 44, 28, 40, 40, 36), bold=True)
        eyebrow_font = _load_font(_font_size_for_length(purpose_text, 20, 52, 68, 18, 16), bold=True)
        body_font = base_body_font
        small_font = base_small_font
        recap_font = _load_font(_font_size_for_length(recap_text, 25, 70, 95, 23, 21))

        draw.rounded_rectangle((36, 30, SLIDE_WIDTH - 36, SLIDE_HEIGHT - 30), radius=28, fill=PANEL_COLOR, outline=BORDER_COLOR, width=3)
        draw.rounded_rectangle((52, 48, SLIDE_WIDTH - 52, 108), radius=18, fill="#FFF5EA")
        purpose_display = _fit_text_block(draw, purpose_text, eyebrow_font, SLIDE_WIDTH - 148, 1)
        title_display = _fit_text_block(draw, title_text, title_font, 820, 2)
        draw.text((74, 66), purpose_display, font=eyebrow_font, fill=ACCENT_COLOR)
        _draw_wrapped_text(draw, title_display, (72, 120), title_font, TEXT_COLOR, 820, line_gap=6, max_lines=2)

        left_x = 78
        left_width = 320
        right_x = 450 if variant == 1 else 470
        top_y = 205
        visual_box = (right_x, 182, 1206, 500)

        hook_box = (left_x, top_y, left_x + left_width, top_y + 88)
        draw.rounded_rectangle(hook_box, radius=18, fill="#F7EBDD")
        hook_display = _fit_text_block(draw, hook_text, small_font, left_width - 36, 2)
        _draw_wrapped_text(draw, hook_display, (left_x + 18, top_y + 16), small_font, MUTED_TEXT_COLOR, left_width - 36, line_gap=5, max_lines=2)

        bullet_y = top_y + 122
        for item in _compact_bullets(slide.get("onscreen_text", []), limit=3, max_length=40):
            draw.ellipse((left_x, bullet_y + 12, left_x + 10, bullet_y + 22), fill=ACCENT_COLOR)
            bullet_display = _fit_text_block(draw, item, body_font, left_width - 24, 2)
            bullet_y = _draw_wrapped_text(draw, bullet_display, (left_x + 24, bullet_y), body_font, TEXT_COLOR, left_width - 24, line_gap=6, max_lines=2) + 8

        formula = slide.get("formula")
        if formula:
            formula_top = min(max(bullet_y + 8, 448), 478)
            formula_box = (left_x, formula_top, left_x + left_width, formula_top + 64)
            _draw_formula_card(draw, formula_box, formula, small_font)

        if variant == 0:
            _draw_primary_panel(draw, slide, visual_box, eyebrow_font, body_font)
        elif variant == 1:
            primary_box = (right_x, 182, 1206, 410)
            notes_box = (right_x, 430, 1206, 558)
            _draw_primary_panel(draw, slide, primary_box, eyebrow_font, body_font)
            _draw_summary_panel(draw, slide, notes_box, eyebrow_font, small_font)
        else:
            narrow_left = (right_x, 182, 780, 500)
            wide_right = (805, 182, 1206, 500)
            _draw_text_explanation_panel(draw, slide, narrow_left, eyebrow_font, small_font)
            _draw_primary_panel(draw, slide, wide_right, eyebrow_font, body_font)

        recap_top = 568
        recap_bottom = SLIDE_HEIGHT - 82
        recap_box = (64, recap_top, SLIDE_WIDTH - 64, recap_bottom)
        draw.rounded_rectangle(recap_box, radius=22, fill="#FCF4EA")
        draw.text((84, recap_top + 16), "Mini Recap", font=eyebrow_font, fill=ACCENT_COLOR)
        recap_display = _fit_text_block(draw, recap_text, recap_font, SLIDE_WIDTH - 168, 2)
        _draw_wrapped_text(draw, recap_display, (84, recap_top + 46), recap_font, TEXT_COLOR, SLIDE_WIDTH - 168, line_gap=6, max_lines=2)

        image_path = output_path / f"slide_{index:02}.png"
        image.save(image_path)
        image_paths.append(str(image_path))

    return image_paths
