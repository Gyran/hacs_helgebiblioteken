# Brand images (icons & logos)

Home Assistant **2026.3+** loads these directly from `custom_components/helgebiblioteken/brand/` (no submission to the [brands repo](https://github.com/home-assistant/brands) needed). See [Brand images](https://developers.home-assistant.io/docs/core/integration/brand_images) and the [Brands Proxy API announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).

They are served in the UI via `/api/brands/integration/helgebiblioteken/…`.

## Source (official)

The PNGs are resized/recoloured copies of assets served by **Axiell** for HelGe-biblioteken:

| Role | Upstream URL |
|------|----------------|
| Square icon (512×512 source, black + red "H") | `https://cdn-s3.axiell.com/sweden/helge/favicon/web-app-manifest-512x512.png` |
| "HelGe" logotype (white on transparent) | `https://cdn-s3.axiell.com/sweden/helge/images/logo-extra.png` |

## Bundled files

Following the Home Assistant brand image spec: icons are square (256 / 512),
logos are landscape with a shortest side of 256 / 512. `dark_*` files are
optimised for dark backgrounds; the plain files are optimised for light ones.

| File | Size | Notes |
|------|------|-------|
| `icon.png` / `icon@2x.png` | 256×256 / 512×512 | Colour mark |
| `dark_icon.png` / `dark_icon@2x.png` | 256×256 / 512×512 | Black half lifted to off-white |
| `logo.png` / `logo@2x.png` | 1004×256 / 2008×512 | Logotype recoloured near-black |
| `dark_logo.png` / `dark_logo@2x.png` | 1004×256 / 2008×512 | Original white logotype |

## Refresh from CDN

From the repository root (requires [Pillow](https://python-pillow.org/)):

```bash
python3 -m pip install -r scripts/requirements-brand.txt
python3 scripts/generate_brand_images.py
```

Then commit the updated PNGs if they changed.

## Trademark

Logos belong to **HelGe-biblioteken** / their providers. This integration uses
them only to identify the service in Home Assistant and does not use Home
Assistant branded images. If upstream changes or removes the CDN files, run the
script again or replace the PNGs manually.
