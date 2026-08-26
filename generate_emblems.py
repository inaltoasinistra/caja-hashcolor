#!/usr/bin/env python3
import colorsys
import os

from PIL import Image, ImageDraw

from caja_hashcolor.palette import ALL_EMBLEMS, CLEAR_EMBLEM_NAME, EMBLEM_SIZE_PX, PALETTE

SUPERSAMPLE = 8  # render larger then downscale, for anti-aliased edges at 32px
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emblems')


def hsl_to_rgb(hue: float, saturation: float, lightness: float) -> tuple[int, int, int]:
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, lightness, saturation)
    return round(red * 255), round(green * 255), round(blue * 255)


def _render_bands(color_indices: tuple[int, ...], angle_degrees: float) -> Image.Image:
    big = EMBLEM_SIZE_PX * SUPERSAMPLE
    band_count = len(color_indices)
    band_image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(band_image)
    band_height = big // band_count + 2
    for i, index in enumerate(color_indices):
        y0 = i * big // band_count - 1
        color = hsl_to_rgb(*PALETTE[index]) + (255,)
        draw.rectangle((0, y0, big, y0 + band_height), fill=color)
    # Rotate the full band strip, then clip to a circle - simpler and more accurate
    # than computing per-angle polygon intersections directly.
    band_image = band_image.rotate(angle_degrees, resample=Image.BICUBIC, center=(big / 2, big / 2))

    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    margin = big // 16
    box = (margin, margin, big - margin, big - margin)
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    image.paste(band_image, (0, 0), mask)
    ImageDraw.Draw(image).ellipse(box, outline=(60, 60, 60, 200), width=SUPERSAMPLE)
    return image.resize((EMBLEM_SIZE_PX, EMBLEM_SIZE_PX), Image.LANCZOS)


def _render_pie(color_indices: tuple[int, ...]) -> Image.Image:
    big = EMBLEM_SIZE_PX * SUPERSAMPLE
    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = big // 16
    box = (margin, margin, big - margin, big - margin)
    span = 360.0 / len(color_indices)
    for i, index in enumerate(color_indices):
        color = hsl_to_rgb(*PALETTE[index]) + (255,)
        draw.pieslice(box, i * span, (i + 1) * span, fill=color)
    draw.ellipse(box, outline=(60, 60, 60, 200), width=SUPERSAMPLE)
    return image.resize((EMBLEM_SIZE_PX, EMBLEM_SIZE_PX), Image.LANCZOS)


def generate_emblems() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generated_names = set()

    # ALL_EMBLEMS is the same list hash_to_emblem_name() indexes into - rendering
    # straight off it (instead of re-deriving the reachable set with a parallel set of
    # loops) guarantees this can never fall out of sync with what's actually
    # selectable.
    for name, kind, indices, angle in ALL_EMBLEMS:
        image = _render_bands(indices, angle) if kind == 'band' else _render_pie(indices)
        image.save(os.path.join(OUTPUT_DIR, f'{name}.png'))
        generated_names.add(name)

    clear_image = Image.new('RGBA', (EMBLEM_SIZE_PX, EMBLEM_SIZE_PX), (0, 0, 0, 0))
    clear_image.save(os.path.join(OUTPUT_DIR, f'{CLEAR_EMBLEM_NAME}.png'))
    generated_names.add(CLEAR_EMBLEM_NAME)

    # Remove stale files from a previous emblem design (e.g. the old 24-solid-color
    # palette) so the directory doesn't accumulate unused images. Only ever touches
    # our own "hashcolor-*" naming - anything else a user has dropped in there
    # is left alone.
    for filename in os.listdir(OUTPUT_DIR):
        if not filename.startswith('hashcolor-') or not filename.endswith('.png'):
            continue
        if filename[: -len('.png')] not in generated_names:
            os.remove(os.path.join(OUTPUT_DIR, filename))

    print(f'generated {len(generated_names)} emblems')


if __name__ == '__main__':
    generate_emblems()
