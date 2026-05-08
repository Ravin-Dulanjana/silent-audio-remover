#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT_DIR / "build" / "assets"
ICONSET_DIR = BUILD_DIR / "SilenceRemover.iconset"
PNG_1024 = BUILD_DIR / "silence_remover_1024.png"
ICNS_PATH = BUILD_DIR / "silence_remover.icns"
ICO_PATH = BUILD_DIR / "silence_remover.ico"


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        ratio = y / max(1, size - 1)
        color = tuple(
            int(top[idx] * (1.0 - ratio) + bottom[idx] * ratio) for idx in range(3)
        )
        draw.line((0, y, size, y), fill=color)
    return image


def build_icon_base(size: int = 1024) -> Image.Image:
    image = _vertical_gradient(size, (16, 58, 94), (9, 23, 39)).convert("RGBA")
    draw = ImageDraw.Draw(image)

    margin = int(size * 0.11)
    panel_radius = int(size * 0.16)
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_box = (margin, margin + int(size * 0.03), size - margin, size - margin + int(size * 0.03))
    shadow_draw.rounded_rectangle(shadow_box, radius=panel_radius, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=int(size * 0.035)))
    image.alpha_composite(shadow)

    panel_box = (margin, margin, size - margin, size - margin)
    draw.rounded_rectangle(panel_box, radius=panel_radius, fill=(248, 251, 255, 255))

    inner = int(size * 0.16)
    waveform_left = margin + inner
    waveform_right = size - margin - inner
    center_y = int(size * 0.57)
    base_h = int(size * 0.06)
    amp_h = int(size * 0.20)
    line_w = max(1, int(size * 0.014))

    draw.line(
        (waveform_left, center_y, waveform_right, center_y),
        fill=(110, 164, 199, 255),
        width=max(1, int(size * 0.01)),
    )

    bars = [
        0.18,
        0.40,
        0.62,
        0.74,
        0.56,
        0.28,
        0.12,
        0.36,
        0.68,
        0.80,
        0.52,
        0.22,
    ]
    span = waveform_right - waveform_left
    gap = span / (len(bars) - 1)
    for idx, value in enumerate(bars):
        x = waveform_left + idx * gap
        half_h = base_h + int(amp_h * value)
        draw.line((x, center_y - half_h, x, center_y + half_h), fill=(18, 112, 176, 255), width=line_w)

    ring_center = (int(size * 0.50), int(size * 0.32))
    ring_r = int(size * 0.12)
    draw.ellipse(
        (
            ring_center[0] - ring_r,
            ring_center[1] - ring_r,
            ring_center[0] + ring_r,
            ring_center[1] + ring_r,
        ),
        fill=(9, 132, 227, 255),
    )
    draw.ellipse(
        (
            ring_center[0] - int(ring_r * 0.55),
            ring_center[1] - int(ring_r * 0.55),
            ring_center[0] + int(ring_r * 0.55),
            ring_center[1] + int(ring_r * 0.55),
        ),
        fill=(248, 251, 255, 255),
    )

    bolt = [
        (ring_center[0] - int(size * 0.018), ring_center[1] - int(size * 0.055)),
        (ring_center[0] + int(size * 0.015), ring_center[1] - int(size * 0.055)),
        (ring_center[0] - int(size * 0.005), ring_center[1] - int(size * 0.005)),
        (ring_center[0] + int(size * 0.032), ring_center[1] - int(size * 0.005)),
        (ring_center[0] - int(size * 0.020), ring_center[1] + int(size * 0.070)),
        (ring_center[0] - int(size * 0.001), ring_center[1] + int(size * 0.015)),
        (ring_center[0] - int(size * 0.028), ring_center[1] + int(size * 0.015)),
    ]
    draw.polygon(bolt, fill=(255, 180, 41, 255))
    return image


def write_outputs() -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    base = build_icon_base()
    base.save(PNG_1024)

    icon_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, size in icon_sizes.items():
        base.resize((size, size), Image.Resampling.LANCZOS).save(ICONSET_DIR / name)

    base.save(ICO_PATH, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    base.save(
        ICNS_PATH,
        format="ICNS",
        sizes=[(1024, 1024), (512, 512), (256, 256), (128, 128), (64, 64), (32, 32), (16, 16)],
    )

    print(PNG_1024)
    print(ICONSET_DIR)
    print(ICNS_PATH)
    print(ICO_PATH)


if __name__ == "__main__":
    write_outputs()
