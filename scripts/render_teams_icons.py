#!/usr/bin/env python3
"""Render the existing AI Lab node mark at Teams-required PNG sizes."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def line(draw, points, fill, width):
    draw.line(points, fill=fill, width=width, joint="curve")


def circle(draw, center, radius, fill):
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def render_color():
    scale = 4
    image = Image.new("RGBA", (192 * scale, 192 * scale), (245, 245, 247, 255))
    draw = ImageDraw.Draw(image)
    line(draw, [(60 * scale, 96 * scale), (74 * scale, 96 * scale)], "#0071E3", 12 * scale)
    line(draw, [(114 * scale, 86 * scale), (136 * scale, 56 * scale)], "#0071E3", 12 * scale)
    line(draw, [(114 * scale, 106 * scale), (136 * scale, 136 * scale)], "#0071E3", 12 * scale)
    circle(draw, (42 * scale, 96 * scale), 18 * scale, "#2997FF")
    circle(draw, (150 * scale, 42 * scale), 18 * scale, "#2997FF")
    circle(draw, (150 * scale, 150 * scale), 18 * scale, "#2997FF")
    circle(draw, (96 * scale, 96 * scale), 22 * scale, "#0071E3")
    image.resize((192, 192), Image.Resampling.LANCZOS).save(ROOT / "teams-app" / "color.png")


def render_outline():
    scale = 8
    image = Image.new("RGBA", (32 * scale, 32 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    line(draw, [(9.5 * scale, 16 * scale), (12 * scale, 16 * scale)], "white", round(2.2 * scale))
    line(draw, [(19 * scale, 14 * scale), (23.2 * scale, 8.4 * scale)], "white", round(2.2 * scale))
    line(draw, [(19 * scale, 18 * scale), (23.2 * scale, 23.6 * scale)], "white", round(2.2 * scale))
    circle(draw, (6 * scale, 16 * scale), 3.5 * scale, "white")
    circle(draw, (26 * scale, 6 * scale), 3.5 * scale, "white")
    circle(draw, (26 * scale, 26 * scale), 3.5 * scale, "white")
    circle(draw, (16 * scale, 16 * scale), 4 * scale, "white")
    image.resize((32, 32), Image.Resampling.LANCZOS).save(ROOT / "teams-app" / "outline.png")


if __name__ == "__main__":
    render_color()
    render_outline()
