"""Deterministic, evidence-bound comparison charts for Word reports."""

from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CHART_RENDERER_VERSION = 5


def _wrapped(text: str, font, width: int) -> list[str]:
    lines, line = [], ""
    for character in text:
        if line and font.getlength(line + character) > width:
            lines.append(line)
            line = ""
        line += character
    return [*lines, line] if line else lines


def draw_comparison(path: Path, title: str, series: list[dict], unit: str, subtitle: str, sources: str,
                    annotations: list[dict]) -> None:
    width = 1400
    font_path = next((name for name in ("/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
                                       "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/Library/Fonts/Arial Unicode.ttf") if Path(name).is_file()), None)
    if font_path is None:
        raise ValueError("Chinese chart font is unavailable")
    title_font = ImageFont.truetype(font_path, 34)
    font = ImageFont.truetype(font_path, 25)
    note_font = ImageFont.truetype(font_path, 20)
    title_lines = _wrapped(title, title_font, width - 88)
    label_lines = [_wrapped(item["label"], font, 280) for item in series]
    row_height = max(94, 32 * max(map(len, label_lines)) + 16)
    extra = (len(title_lines) - 1) * 44
    chart_top = (270 if annotations else 166) + extra
    height = chart_top + row_height * len(series) + 64
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(title_lines):
        draw.text((42, 27 + index * 44), line, fill="#172535", font=title_font)
    draw.text((44, 84 + extra), f"{subtitle}    单位：{unit}", fill="#5e6b79", font=note_font)
    draw.line((44, 126 + extra, width - 44, 126 + extra), fill="#dce3e9", width=2)
    for index, item in enumerate(annotations):
        x = 44 + index * 330
        draw.rounded_rectangle((x, 145 + extra, x + 308, 237 + extra), radius=9, fill="#f1f5f8")
        draw.text((x + 15, 157 + extra), item["label"], fill="#566676", font=note_font)
        value = Decimal(item["value"])
        shown = ("+" if value > 0 and "差额" in item["label"] else "") + f"{value:,.2f} {item['unit']}"
        draw.text((x + 15, 188 + extra), shown, fill="#126f76" if value >= 0 else "#bc594f", font=font)
    values = [Decimal(item["value"]) for item in series]
    low, high = min(Decimal(0), *values), max(Decimal(0), *values)
    if low == high:
        high = Decimal(1)
    left, chart_width = 345, 765
    zero = left + int((Decimal(0) - low) / (high - low) * chart_width)
    draw.line((zero, chart_top - 11, zero, height - 77), fill="#9aa7b2", width=2)
    for index, item in enumerate(series):
        y = chart_top + index * row_height
        end = left + int((Decimal(item["value"]) - low) / (high - low) * chart_width)
        for number, line in enumerate(label_lines[index]):
            draw.text((44, y + 7 + number * 32), line, fill="#172535", font=font)
        color = "#bc594f" if Decimal(item["value"]) < 0 else "#126f76" if index == 0 else "#6f8da7"
        draw.rectangle((min(zero, end), y, max(zero + 2, end), y + 48), fill=color)
        draw.text((1138, y + 7), f"{Decimal(item['value']):,.2f}", fill="#172535", font=font)
        draw.line((44, y + row_height - 17, width - 44, y + row_height - 17), fill="#edf1f4", width=1)
    source = "来源：" + sources
    while draw.textbbox((0, 0), source, font=note_font)[2] > width - 88:
        source = source[:-2] + "…"
    draw.text((44, height - 53), source, fill="#667483", font=note_font)
    canvas.save(path, format="PNG")
