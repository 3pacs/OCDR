#!/usr/bin/env python3
"""Generate OCDR app icon (static/ocdr.ico) using Pillow."""

import os
import sys

def generate():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed, skipping icon generation.")
        return

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'ocdr.ico')
    if os.path.exists(out_path):
        return  # Already generated

    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Dark blue rounded-square background
        pad = max(1, size // 16)
        r = max(2, size // 6)
        draw.rounded_rectangle([pad, pad, size - pad - 1, size - pad - 1],
                               radius=r, fill='#1a1d23', outline='#4f8cff',
                               width=max(1, size // 32))

        # Draw "OC" text centered
        font_size = max(6, size * 5 // 12)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        text = "OC"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (size - tw) // 2
        y = (size - th) // 2 - bbox[1]
        draw.text((x, y), text, fill='#4f8cff', font=font)

        images.append(img)

    # Save as .ico with all sizes
    images[-1].save(out_path, format='ICO', sizes=[(s, s) for s in sizes],
                    append_images=images[:-1])
    print(f"Icon saved: {out_path}")


if __name__ == '__main__':
    generate()
