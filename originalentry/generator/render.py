"""Render a document image (T5: one PNG per document per variant).

Deliberately plain: a company header bar, the document's reference and date, its fields, and its
line items — drawn straight from the pack's ``text_alternative`` so the picture and the text a
screen reader gets can never drift apart (S2.8). Needs Pillow (a laptop-only dependency).

This is an MVP renderer. It uses Pillow's built-in font so it needs no font file and produces the
same bytes on any machine; a nicer typeface is a later refinement, not a correctness concern (the
text alternative is the source of truth either way).
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

WIDTH = 760
PAD = 24
LINE_H = 20
HEADER_H = 56
INK = (26, 26, 26)
MUTED = (86, 86, 86)
RULE = (217, 217, 217)
PAPER = (255, 255, 255)
WHITE = (255, 255, 255)


def _accent_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#1f5f8b").lstrip("#")
    if len(h) != 6:
        h = "1f5f8b"
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _font() -> ImageFont.ImageFont:
    return ImageFont.load_default()


def render_document_png(document: dict, variant_code: str, company: dict) -> bytes:
    variant = (document.get("variants") or {}).get(variant_code, {})
    text_alt = variant.get("text_alternative") or {}
    fields = text_alt.get("fields") or []
    lines = text_alt.get("lines") or []

    # Height: header + title block + fields + line items + padding.
    body_rows = 2 + len(fields) + (1 + len(lines) if lines else 0)
    height = HEADER_H + PAD + body_rows * LINE_H + PAD
    image = Image.new("RGB", (WIDTH, max(height, HEADER_H + 80)), PAPER)
    draw = ImageDraw.Draw(image)
    font = _font()

    accent = _accent_rgb(company.get("accent_hex", "#1f5f8b"))
    draw.rectangle([0, 0, WIDTH, HEADER_H], fill=accent)
    monogram = (company.get("monogram") or "").strip()
    if monogram:
        draw.rectangle([PAD, 14, PAD + 28, 42], outline=WHITE, width=2)
        draw.text((PAD + 8, 20), monogram[:3], fill=WHITE, font=font)
    draw.text((PAD + 44, 16), company.get("name", ""), fill=WHITE, font=font)
    draw.text((PAD + 44, 32), f"Variant {variant_code}", fill=WHITE, font=font)

    y = HEADER_H + PAD
    draw.text((PAD, y), document.get("display_ref", document.get("ref", "")), fill=INK, font=font)
    y += LINE_H
    meta = f"{document.get('type', '').replace('_', ' ')} · {document.get('date', '')}"
    draw.text((PAD, y), meta, fill=MUTED, font=font)
    y += LINE_H + 6

    for label, value in fields:
        draw.text((PAD, y), f"{label}:", fill=MUTED, font=font)
        draw.text((PAD + 180, y), str(value), fill=INK, font=font)
        y += LINE_H

    if lines:
        y += 6
        draw.line([(PAD, y), (WIDTH - PAD, y)], fill=RULE, width=1)
        y += 6
        col_w = (WIDTH - 2 * PAD) // max(len(lines[0]), 1)
        for row in lines:
            x = PAD
            for cell in row:
                draw.text((x, y), str(cell), fill=INK, font=font)
                x += col_w
            y += LINE_H

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
