#!/usr/bin/env python3
import colorsys
import os
from itertools import permutations

from PIL import Image, ImageDraw

from palette import (
    ANGLES_DEGREES,
    CLEAR_EMBLEM_NAME,
    PALETTE,
    PALETTE_SIZE,
    VALID_ABAC_TRIPLES,
    VALID_PAIRS,
    VALID_QUADS,
    VALID_TRIPLES,
    five_slice_pie_pattern,
)

EMBLEM_SIZE_PX = 32
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

    for index in range(PALETTE_SIZE):
        # A single-band "strip" with only one color fills the whole circle - reusing
        # _render_bands() instead of a one-off solid-fill function keeps the same
        # outline/anti-aliasing treatment as every other emblem. The angle is
        # irrelevant (rotating a single full-height band changes nothing visible), so
        # there's just one PNG per color, not one per angle.
        name = f'hashcolor-1-{index}'
        _render_bands((index,), 0).save(os.path.join(OUTPUT_DIR, f'{name}.png'))
        generated_names.add(name)

    for pair in VALID_PAIRS:
        for order in permutations(pair):
            for angle in ANGLES_DEGREES:
                name = f'hashcolor-2-{order[0]}-{order[1]}-{angle}'
                _render_bands(order, angle).save(os.path.join(OUTPUT_DIR, f'{name}.png'))
                generated_names.add(name)

                aba_name = f'hashcolor-3ba-{order[0]}-{order[1]}-{angle}'
                aba_indices = (order[0], order[1], order[0])
                _render_bands(aba_indices, angle).save(os.path.join(OUTPUT_DIR, f'{aba_name}.png'))
                generated_names.add(aba_name)

            # 4- and 6-slice pies alternating the pair - even slice counts alternate
            # cleanly between exactly 2 colors with no two same-colored slices ever
            # touching (unlike an odd count, see the 5p pattern below).
            four_name = f'hashcolor-4p-{order[0]}-{order[1]}'
            _render_pie(order * 2).save(os.path.join(OUTPUT_DIR, f'{four_name}.png'))
            generated_names.add(four_name)

            six_name = f'hashcolor-6p-{order[0]}-{order[1]}'
            _render_pie(order * 3).save(os.path.join(OUTPUT_DIR, f'{six_name}.png'))
            generated_names.add(six_name)

    for triple in VALID_TRIPLES:
        for order in permutations(triple):
            for angle in ANGLES_DEGREES:
                name = f'hashcolor-3b-{order[0]}-{order[1]}-{order[2]}-{angle}'
                _render_bands(order, angle).save(os.path.join(OUTPUT_DIR, f'{name}.png'))
                generated_names.add(name)
            pie_name = f'hashcolor-3p-{order[0]}-{order[1]}-{order[2]}'
            _render_pie(order).save(os.path.join(OUTPUT_DIR, f'{pie_name}.png'))
            generated_names.add(pie_name)

            five_name = f'hashcolor-5p-{order[0]}-{order[1]}-{order[2]}'
            _render_pie(five_slice_pie_pattern(order)).save(os.path.join(OUTPUT_DIR, f'{five_name}.png'))
            generated_names.add(five_name)

    for anchor, b, c in VALID_ABAC_TRIPLES:
        for b_order, c_order in permutations((b, c)):
            name = f'hashcolor-4p3-{anchor}-{b_order}-{c_order}'
            _render_pie((anchor, b_order, anchor, c_order)).save(os.path.join(OUTPUT_DIR, f'{name}.png'))
            generated_names.add(name)

    for cycle in VALID_QUADS:
        name = f'hashcolor-4p4-{cycle[0]}-{cycle[1]}-{cycle[2]}-{cycle[3]}'
        _render_pie(cycle).save(os.path.join(OUTPUT_DIR, f'{name}.png'))
        generated_names.add(name)

    clear_image = Image.new('RGBA', (EMBLEM_SIZE_PX, EMBLEM_SIZE_PX), (0, 0, 0, 0))
    clear_image.save(os.path.join(OUTPUT_DIR, f'{CLEAR_EMBLEM_NAME}.png'))
    generated_names.add(CLEAR_EMBLEM_NAME)

    # Remove stale files from a previous emblem design (e.g. the old 24-solid-color
    # palette) so the directory doesn't accumulate unused images. Only ever touches
    # our own "hashcolor-*" naming - anything else (e.g. hand-made reference images)
    # is left alone.
    for filename in os.listdir(OUTPUT_DIR):
        if not filename.startswith('hashcolor-') or not filename.endswith('.png'):
            continue
        if filename[: -len('.png')] not in generated_names:
            os.remove(os.path.join(OUTPUT_DIR, filename))

    print(f'generated {len(generated_names)} emblems')


if __name__ == '__main__':
    generate_emblems()
