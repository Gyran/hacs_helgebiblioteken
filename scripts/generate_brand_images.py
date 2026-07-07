#!/usr/bin/env python3
"""Download official HelGe-biblioteken brand assets and build Home Assistant brand images.

Source: Axiell CDN (the same files served by helgebiblioteken.se).

Output: custom_components/helgebiblioteken/brand/, following the Home Assistant
brand image spec (https://github.com/home-assistant/brands):

  icon.png / icon@2x.png            256x256 / 512x512, square
  dark_icon.png / dark_icon@2x.png  dark-theme optimised icon
  logo.png / logo@2x.png            landscape, shortest side 256 / 512
  dark_logo.png / dark_logo@2x.png  dark-theme optimised logo (original white mark)

Requires: pip install pillow

Run from repo root:
  python3 -m pip install -r scripts/requirements-brand.txt
  python3 scripts/generate_brand_images.py
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

REPO = Path(__file__).resolve().parent.parent
BRAND = REPO / "custom_components" / "helgebiblioteken" / "brand"

# Square colour app icon (black + red "H" mark) already 512x512 with transparency.
ICON_SRC = "https://cdn-s3.axiell.com/sweden/helge/favicon/web-app-manifest-512x512.png"
# "HelGe" logotype (white on transparent), wide landscape.
LOGO_SRC = "https://cdn-s3.axiell.com/sweden/helge/images/logo-extra.png"

# Off-white used for the dark-theme icon and near-black used for the light logo.
DARK_BG_INK = (237, 237, 237)
LIGHT_BG_INK = (26, 26, 26)


def _download(url: str) -> bytes:
    try:
        return urlopen(url, timeout=30).read()  # noqa: S310
    except URLError as err:
        sys.stderr.write(f"Download failed for {url}: {err}\n")
        sys.exit(1)


def main() -> None:
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        sys.stderr.write("Install Pillow: python3 -m pip install pillow\n")
        sys.exit(1)

    BRAND.mkdir(parents=True, exist_ok=True)
    lanczos = Image.Resampling.LANCZOS

    def trim(im: "Image.Image") -> "Image.Image":
        bbox = im.split()[3].getbbox()
        return im.crop(bbox) if bbox else im

    def recolor(im: "Image.Image", rgb: tuple[int, int, int]) -> "Image.Image":
        """Replace RGB while keeping the original alpha (for solid-colour marks)."""
        solid = Image.new("RGBA", im.size, (*rgb, 0))
        solid.putalpha(im.split()[3])
        return solid

    def swap_near_black(im: "Image.Image", rgb: tuple[int, int, int]) -> "Image.Image":
        out = im.copy()
        px = out.load()
        w, h = out.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a > 0 and r < 70 and g < 70 and b < 70:
                    px[x, y] = (*rgb, a)
        return out

    def save(im: "Image.Image", name: str) -> None:
        path = BRAND / name
        im.save(path, "PNG", optimize=True)
        print(f"Wrote {path.relative_to(REPO)} ({im.size[0]}x{im.size[1]})")

    def by_height(im: "Image.Image", height: int) -> "Image.Image":
        width = round(im.size[0] * height / im.size[1])
        return im.resize((width, height), lanczos)

    # ---- Icon: square colour mark. Keep the balanced 512 source as @2x. ----
    icon = Image.open(BytesIO(_download(ICON_SRC))).convert("RGBA")
    save(icon, "icon@2x.png")
    save(icon.resize((256, 256), lanczos), "icon.png")

    # Dark icon: the black half vanishes on dark UIs, so lift it to off-white.
    dark_icon = swap_near_black(icon, DARK_BG_INK)
    save(dark_icon, "dark_icon@2x.png")
    save(dark_icon.resize((256, 256), lanczos), "dark_icon.png")

    # ---- Logo: "HelGe" logotype (white on transparent). ----
    logo = trim(Image.open(BytesIO(_download(LOGO_SRC))).convert("RGBA"))

    # Dark logo keeps the original white mark for dark backgrounds.
    save(by_height(logo, 512), "dark_logo@2x.png")
    save(by_height(logo, 256), "dark_logo.png")

    # Light logo (default) recolours the white mark to near-black.
    light_logo = recolor(logo, LIGHT_BG_INK)
    save(by_height(light_logo, 512), "logo@2x.png")
    save(by_height(light_logo, 256), "logo.png")


if __name__ == "__main__":
    main()
