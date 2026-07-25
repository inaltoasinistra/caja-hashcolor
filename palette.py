#!/usr/bin/env python3
from itertools import combinations, permutations

# Full saturation and mid lightness for a vivid, clearly-distinguishable look. A
# pastel version (lower saturation, higher lightness) was tried first but made
# same-family hues too close to reliably tell apart even after the contrast
# filtering below - vivid colors read better at a glance, including at small
# real emblem size.
SATURATION = 0.9
LIGHTNESS = 0.5

# Explicit hues, not an evenly-spaced wheel: an earlier 8-hue evenly-spaced (45 deg
# apart) version put chartreuse (90 deg) and green (135 deg) next to cyan (180 deg) -
# human color vision compresses hue differences in that green/cyan region, so 90 deg
# of raw hue distance wasn't enough to actually tell those three apart (confirmed by
# rendering and inspecting them - two separate emblems differing only in that one
# slot looked identical). Fixed by dropping to 7 hues and widening the gap around
# that specific region instead of relying on uniform spacing everywhere.
PALETTE_HUES_DEGREES = [0, 45, 105, 185, 230, 275, 320]
PALETTE_SIZE = len(PALETTE_HUES_DEGREES)

HSLColor = tuple[float, float, float]

PALETTE: list[HSLColor] = [(hue, SATURATION, LIGHTNESS) for hue in PALETTE_HUES_DEGREES]

# Colors closer than this in hue looked too similar side by side in the same emblem
# (confirmed by rendering every pair and inspecting them) - excluded from ever being
# combined, even though it shrinks the total number of representable combinations.
MIN_HUE_DISTANCE_DEGREES = 90.0

# The circle is split by parallel lines at one of these angles for the "band" styles
# (2-color: one line; 3-color band: two lines) - matches the reference examples
# (horizontal, vertical, and 45-degree splits).
ANGLES_DEGREES = [0, 45, 90, 135]

# Fully transparent emblem, added when a directory is disabled: Caja's extension API
# has no way to remove a previously-shown emblem, only add one, but we've confirmed
# that adding *something* makes Caja replace whatever was shown before - so adding
# an invisible emblem is how a disabled directory's stale color actually clears.
CLEAR_EMBLEM_NAME = 'hashcolor-clear'


def _hue_distance(hue_a: float, hue_b: float) -> float:
    diff = abs(hue_a - hue_b) % 360
    return min(diff, 360 - diff)


def _all_pairs_far_enough(indices: tuple[int, ...]) -> bool:
    return all(
        _hue_distance(PALETTE[a][0], PALETTE[b][0]) >= MIN_HUE_DISTANCE_DEGREES for a, b in combinations(indices, 2)
    )


VALID_PAIRS: list[tuple[int, int]] = [c for c in combinations(range(PALETTE_SIZE), 2) if _all_pairs_far_enough(c)]
VALID_TRIPLES: list[tuple[int, int, int]] = [
    c for c in combinations(range(PALETTE_SIZE), 3) if _all_pairs_far_enough(c)
]


def _adjacent_pairs_far_enough(cycle: tuple[int, ...]) -> bool:
    return all(
        _hue_distance(PALETTE[cycle[i]][0], PALETTE[cycle[(i + 1) % len(cycle)]][0]) >= MIN_HUE_DISTANCE_DEGREES
        for i in range(len(cycle))
    )


def _neighbors_of(anchor: int) -> list[int]:
    return [
        other
        for other in range(PALETTE_SIZE)
        if other != anchor and _hue_distance(PALETTE[anchor][0], PALETTE[other][0]) >= MIN_HUE_DISTANCE_DEGREES
    ]


# 4-slice pie, 3 colors as (anchor, b, anchor, c): the anchor sits at opposite corners
# (positions 0 and 2 of a 4-cycle), which never touch each other, and b/c sit at the
# other two opposite corners - so only anchor-b and anchor-c need to clear the
# contrast rule; b and c are diagonal to each other too, so they never need to differ.
# No VALID_TRIPLES-style "all 3 mutually >=90 apart" requirement here at all.
VALID_ABAC_TRIPLES: list[tuple[int, int, int]] = [
    (anchor, b, c) for anchor in range(PALETTE_SIZE) for b, c in combinations(_neighbors_of(anchor), 2)
]

# 4-slice pie, 4 distinct colors in a cycle: unlike VALID_TRIPLES, this doesn't
# require all 6 possible pairs to clear the contrast rule - only the 4 pairs that are
# actually adjacent in the circle (the 2 diagonal pairs never touch). Requiring all 6
# pairs (like VALID_TRIPLES does) turns out to admit zero quadruples on this 7-hue
# palette; relaxing to adjacency-only is what makes a 4-distinct-color pie possible.
# The full arrangement (not just the unordered set of colors) is stored, since only
# some orderings of a given 4 colors satisfy the adjacency rule - hash_to_emblem_name
# must use one of these exact arrangements as-is, not re-sort it by digest.
VALID_QUADS: list[tuple[int, int, int, int]] = [
    order for quad in combinations(range(PALETTE_SIZE), 4) for order in permutations(quad) if _adjacent_pairs_far_enough(order)
]


def five_slice_pie_pattern(order: tuple[int, int, int]) -> tuple[int, ...]:
    # An odd slice count can't alternate just 2 colors without one touching itself at
    # the wrap-around seam, so this repeats all 3 as (a, b, c, a, b) instead. Since
    # a/b/c are always pairwise distinct (VALID_TRIPLES entries are 3-element
    # combinations), this ordering is guaranteed to never place two same-colored
    # slices next to each other, including the wrap-around - shared by
    # generate_emblems.py's rendering and test_palette.py's verification of that
    # guarantee, so the two can't silently drift apart.
    return order + order[:2]


def hash_to_emblem_name(digest: bytes) -> str:
    # Top-level choice of which color-pool/shape family to draw from. Every choice
    # below is a plain index into a small, deterministic list, so the same digest
    # always maps to the same emblem name and generate_emblems.py can enumerate every
    # reachable name up front.
    family = digest[0] % 5
    angle = ANGLES_DEGREES[digest[6] % len(ANGLES_DEGREES)]

    if family == 4:
        # Plain solid color, no split at all - given equal footing with the other
        # four multi-color families (all reachable via the same digest[0] % 5 choice)
        # even though it only has PALETTE_SIZE distinguishable outcomes instead of
        # dozens: two unrelated files landing on the same solid hue will look
        # identical, a real loss of distinguishability, but a plain color is also the
        # simplest, calmest-looking emblem, and worth having in the mix rather than
        # only ever showing busier multi-color combos.
        return f'hashcolor-1-{digest[1] % PALETTE_SIZE}'

    if family == 0:
        # 2-color combos pick among four layouts, all reusing the same
        # contrast-filtered pair pool (far larger than VALID_TRIPLES - see comment on
        # PALETTE_HUES_DEGREES): a plain split, a 3-band (a, b, a), and 4- and
        # 6-slice pies alternating the pair (even slice counts alternate cleanly with
        # only 2 colors, unlike 5 - see the 5p style below).
        combo = VALID_PAIRS[digest[1] % len(VALID_PAIRS)]
        order = sorted(combo, key=lambda index: digest[2 + index])
        style = digest[7] % 4
        if style == 0:
            return f'hashcolor-2-{order[0]}-{order[1]}-{angle}'
        if style == 1:
            return f'hashcolor-3ba-{order[0]}-{order[1]}-{angle}'
        if style == 2:
            return f'hashcolor-4p-{order[0]}-{order[1]}'
        return f'hashcolor-6p-{order[0]}-{order[1]}'

    if family == 1:
        # 3-color combos, all mutually >=90 apart (every pair here can end up
        # adjacent depending on the layout, so all 3 pairs need contrast): 3p/3b
        # place each color once; 5p repeats the pattern as a 5-slice pie
        # (a, b, c, a, b) - verified to never put two same-colored slices next to
        # each other (including the wrap-around seam), so it never looks like a
        # lower slice count than it actually has.
        combo = VALID_TRIPLES[digest[1] % len(VALID_TRIPLES)]
        order = sorted(combo, key=lambda index: digest[2 + index])
        style = digest[5] % 3
        if style == 0:
            return f'hashcolor-3p-{order[0]}-{order[1]}-{order[2]}'
        if style == 1:
            return f'hashcolor-3b-{order[0]}-{order[1]}-{order[2]}-{angle}'
        return f'hashcolor-5p-{order[0]}-{order[1]}-{order[2]}'

    if family == 2:
        # 4-slice pie, 3 colors as (anchor, b, anchor, c) - see VALID_ABAC_TRIPLES.
        # b and c are diagonal to each other (never touch), so they can be freely
        # reordered by digest same as any other pair.
        anchor, b, c = VALID_ABAC_TRIPLES[digest[1] % len(VALID_ABAC_TRIPLES)]
        b, c = sorted((b, c), key=lambda index: digest[2 + index])
        return f'hashcolor-4p3-{anchor}-{b}-{c}'

    # family == 3: 4-slice pie, 4 distinct colors - see VALID_QUADS. Only some
    # orderings of a given 4 colors satisfy the adjacency-only contrast rule, so the
    # stored arrangement is used exactly as-is, not re-sorted by digest.
    cycle = VALID_QUADS[digest[1] % len(VALID_QUADS)]
    return f'hashcolor-4p4-{cycle[0]}-{cycle[1]}-{cycle[2]}-{cycle[3]}'
