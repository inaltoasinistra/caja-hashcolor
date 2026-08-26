#!/usr/bin/env python3
import hashlib
import os
import re
import unittest
from itertools import combinations, permutations

from caja_hashcolor.palette import (
    ALL_EMBLEM_NAMES,
    ANGLES_DEGREES,
    MIN_HUE_DISTANCE_DEGREES,
    PALETTE,
    PALETTE_SIZE,
    VALID_ABAC_TRIPLES,
    VALID_PAIRS,
    VALID_QUADS,
    VALID_TRIPLES,
    five_slice_pie_pattern,
    hash_to_emblem_name,
)

NAME_PATTERN = re.compile(
    r'^hashcolor-('
    r'1-(?P<solo>\d)'
    r'|2-(?P<pair>\d-\d)-(?P<angle1>\d+)'
    r'|3ba-(?P<abapair>\d-\d)-(?P<angle3>\d+)'
    r'|3b-(?P<triple>\d-\d-\d)-(?P<angle2>\d+)'
    r'|3p-(?P<pie>\d-\d-\d)'
    r'|4p-(?P<fourpair>\d-\d)'
    r'|4p3-(?P<abac>\d-\d-\d)'
    r'|4p4-(?P<quad>\d-\d-\d-\d)'
    r'|5p-(?P<fivetriple>\d-\d-\d)'
    r'|6p-(?P<sixpair>\d-\d)'
    r')$'
)

# Hardcoded independently of palette.MIN_HUE_DISTANCE_DEGREES: a test that reads its
# expected threshold from the same constant it's checking can never fail if that
# constant is weakened (confirmed by mutation testing - it didn't, until this fix).
EXPECTED_MIN_HUE_DISTANCE = 90.0

# Hardcoded independently of palette.PALETTE_HUES_DEGREES for the same reason as
# EXPECTED_MIN_HUE_DISTANCE above: these specific hues (not an evenly-spaced wheel)
# were chosen, and the borderline pairs re-rendered and visually re-checked, to avoid
# a green/chartreuse/cyan region where raw hue distance didn't track perceived
# difference - reverting to uniform spacing would silently reintroduce that bug.
EXPECTED_PALETTE_HUES_DEGREES = [0, 45, 105, 185, 230, 275, 320]


def digest_of(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def indices_in_name(name: str) -> tuple[int, ...]:
    match = NAME_PATTERN.match(name)
    assert match is not None, f'unexpected emblem name format: {name}'
    group = (
        match.group('solo')
        or match.group('pair')
        or match.group('abapair')
        or match.group('triple')
        or match.group('pie')
        or match.group('fourpair')
        or match.group('abac')
        or match.group('quad')
        or match.group('fivetriple')
        or match.group('sixpair')
    )
    return tuple(int(part) for part in group.split('-'))


class TestValidCombinations(unittest.TestCase):
    def test_min_hue_distance_constant_matches_the_design_decision(self):
        self.assertEqual(MIN_HUE_DISTANCE_DEGREES, EXPECTED_MIN_HUE_DISTANCE)

    def test_pairs_and_triples_are_nonempty(self):
        self.assertGreater(len(VALID_PAIRS), 0)
        self.assertGreater(len(VALID_TRIPLES), 0)

    def test_every_valid_pair_satisfies_the_contrast_rule(self):
        for a, b in VALID_PAIRS:
            hue_diff = abs(PALETTE[a][0] - PALETTE[b][0]) % 360
            hue_diff = min(hue_diff, 360 - hue_diff)
            self.assertGreaterEqual(hue_diff, EXPECTED_MIN_HUE_DISTANCE)

    def test_every_valid_triple_satisfies_the_contrast_rule(self):
        for triple in VALID_TRIPLES:
            for a, b in combinations(triple, 2):
                hue_diff = abs(PALETTE[a][0] - PALETTE[b][0]) % 360
                hue_diff = min(hue_diff, 360 - hue_diff)
                self.assertGreaterEqual(hue_diff, EXPECTED_MIN_HUE_DISTANCE)

    def test_palette_hues_match_the_verified_design(self):
        self.assertEqual([hue for hue, _, _ in PALETTE], EXPECTED_PALETTE_HUES_DEGREES)

    def test_abac_and_quads_are_nonempty(self):
        self.assertGreater(len(VALID_ABAC_TRIPLES), 0)
        self.assertGreater(len(VALID_QUADS), 0)

    def test_every_abac_triple_satisfies_the_anchor_only_contrast_rule(self):
        """Only anchor-b and anchor-c need to clear the threshold (they're the only
        pairs that touch in the (anchor, b, anchor, c) 4-slice layout) - b and c are
        diagonal to each other and never need to differ."""
        for anchor, b, c in VALID_ABAC_TRIPLES:
            for other in (b, c):
                hue_diff = abs(PALETTE[anchor][0] - PALETTE[other][0]) % 360
                hue_diff = min(hue_diff, 360 - hue_diff)
                self.assertGreaterEqual(hue_diff, EXPECTED_MIN_HUE_DISTANCE)

    def test_some_abac_triples_have_a_close_diagonal_pair(self):
        """Regression guard for the relaxed rule itself: if b and c always happened
        to also be far apart, this pool wouldn't actually be exercising the
        anchor-only relaxation - it'd just be a subset of VALID_TRIPLES in disguise."""
        has_close_diagonal = any(
            min(abs(PALETTE[b][0] - PALETTE[c][0]) % 360, 360 - abs(PALETTE[b][0] - PALETTE[c][0]) % 360)
            < EXPECTED_MIN_HUE_DISTANCE
            for _, b, c in VALID_ABAC_TRIPLES
        )
        self.assertTrue(has_close_diagonal)

    def test_every_quad_satisfies_the_adjacency_only_contrast_rule(self):
        """Only the 4 adjacent pairs in the cycle need to clear the threshold - the
        2 diagonal pairs never touch in a 4-slice pie and never need to differ."""
        for cycle in VALID_QUADS:
            for i in range(4):
                a, b = cycle[i], cycle[(i + 1) % 4]
                hue_diff = abs(PALETTE[a][0] - PALETTE[b][0]) % 360
                hue_diff = min(hue_diff, 360 - hue_diff)
                self.assertGreaterEqual(hue_diff, EXPECTED_MIN_HUE_DISTANCE)

    def test_no_quad_satisfies_the_stricter_all_pairs_contrast_rule(self):
        """Regression guard for the relaxed rule itself: requiring all 6 pairs (not
        just the 4 adjacent ones) to clear the threshold admits zero quadruples on
        this 7-hue palette - confirming VALID_QUADS only exists because of the
        adjacency-only relaxation, not despite it being unnecessary."""
        for cycle in VALID_QUADS:
            diagonal_pairs = [(cycle[0], cycle[2]), (cycle[1], cycle[3])]
            all_far_enough = all(
                min(abs(PALETTE[a][0] - PALETTE[b][0]) % 360, 360 - abs(PALETTE[a][0] - PALETTE[b][0]) % 360)
                >= EXPECTED_MIN_HUE_DISTANCE
                for a, b in diagonal_pairs
            )
            self.assertFalse(all_far_enough)

    def test_indices_are_within_palette_range(self):
        for pair in VALID_PAIRS:
            for index in pair:
                self.assertGreaterEqual(index, 0)
                self.assertLess(index, PALETTE_SIZE)
        for triple in VALID_TRIPLES:
            for index in triple:
                self.assertGreaterEqual(index, 0)
                self.assertLess(index, PALETTE_SIZE)


class TestAllEmblemNames(unittest.TestCase):
    def test_no_duplicate_names(self):
        """ALL_EMBLEM_NAMES is indexed directly by digest % len(...) - a duplicate
        would silently shrink the effective selection space and skew probability
        toward whichever name repeats, the exact bug this list exists to avoid."""
        self.assertEqual(len(ALL_EMBLEM_NAMES), len(set(ALL_EMBLEM_NAMES)))


class TestHashToEmblemName(unittest.TestCase):
    def test_index_maps_directly_into_all_emblem_names(self):
        """Pins down the actual selection algorithm - the full digest read as one big
        integer, modulo len(ALL_EMBLEM_NAMES) - rather than a per-byte 'pick a family,
        then a name within it' scheme. The old scheme picked among 5 families with
        roughly equal probability regardless of family size, so a name in the
        7-entry solid family was ~30x more likely than one in the 216-entry pair
        family - every entry here must instead have exactly equal odds."""
        total = len(ALL_EMBLEM_NAMES)
        for index in (0, 1, total - 1, total, total + 5, 2 * total - 1):
            digest = index.to_bytes(32, 'big')
            self.assertEqual(hash_to_emblem_name(digest), ALL_EMBLEM_NAMES[index % total])

    def test_deterministic(self):
        digest = digest_of(b'same input')
        self.assertEqual(hash_to_emblem_name(digest), hash_to_emblem_name(digest))

    def test_matches_expected_format(self):
        for data in (b'a', b'b', b'c', b'', os.urandom(32)):
            name = hash_to_emblem_name(digest_of(data))
            self.assertRegex(name, NAME_PATTERN)

    def test_different_digests_can_produce_different_names(self):
        names = {hash_to_emblem_name(digest_of(bytes([i]))) for i in range(50)}
        self.assertGreater(len(names), 1)

    def test_generated_name_colors_satisfy_the_contrast_rule(self):
        """The name isn't just built from an already-filtered pool in isolation -
        confirm the actual colors it encodes are mutually far enough apart, tying
        the public hash_to_emblem_name() output back to the contrast requirement.
        Skips 4p3/4p4 names: those styles only require *adjacent* slices to
        contrast, not every pair (see test_four_slice_three_color_uses_valid_abac
        and test_four_slice_four_color_uses_valid_quad below for their own,
        weaker, correctly-scoped rule)."""
        for data in [bytes([i]) for i in range(100)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            if match.group('abac') is not None or match.group('quad') is not None:
                continue
            indices = indices_in_name(name)
            for a, b in combinations(indices, 2):
                hue_diff = abs(PALETTE[a][0] - PALETTE[b][0]) % 360
                hue_diff = min(hue_diff, 360 - hue_diff)
                self.assertGreaterEqual(hue_diff, EXPECTED_MIN_HUE_DISTANCE)

    def test_band_style_names_use_a_known_angle(self):
        found_band = False
        for data in [bytes([i]) for i in range(100)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            angle = match.group('angle1') or match.group('angle2') or match.group('angle3')
            if angle is not None:
                found_band = True
                self.assertIn(int(angle), ANGLES_DEGREES)
        self.assertTrue(found_band, 'expected at least one band-style name across 100 samples')

    def test_aba_band_style_uses_a_valid_pair(self):
        """The (a, b, a) 3-band style repeats a VALID_PAIRS entry as outer/middle/
        outer bands, instead of needing a third mutually-distinguishable color - this
        confirms the encoded pair really is drawn from that pool, not built ad hoc."""
        found_aba = False
        for data in [bytes([i]) for i in range(200)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            if match.group('abapair') is not None:
                found_aba = True
                a, b = (int(part) for part in match.group('abapair').split('-'))
                self.assertIn(tuple(sorted((a, b))), VALID_PAIRS)
        self.assertTrue(found_aba, 'expected at least one 3ba-style name across 200 samples')

    def test_four_and_six_slice_pies_use_a_valid_pair(self):
        """4p and 6p alternate a VALID_PAIRS entry around an even number of pie
        slices (2 colors alternate cleanly with no adjacent seam clash, unlike an
        odd count - see test_five_slice_pattern_has_no_adjacent_same_color below)."""
        found_four = False
        found_six = False
        for data in [bytes([i]) for i in range(200)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            for group_name in ('fourpair', 'sixpair'):
                group = match.group(group_name)
                if group is None:
                    continue
                found_four = found_four or group_name == 'fourpair'
                found_six = found_six or group_name == 'sixpair'
                a, b = (int(part) for part in group.split('-'))
                self.assertIn(tuple(sorted((a, b))), VALID_PAIRS)
        self.assertTrue(found_four, 'expected at least one 4p-style name across 200 samples')
        self.assertTrue(found_six, 'expected at least one 6p-style name across 200 samples')

    def test_five_slice_pie_uses_a_valid_triple(self):
        found_five = False
        for data in [bytes([i]) for i in range(200)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            if match.group('fivetriple') is not None:
                found_five = True
                a, b, c = (int(part) for part in match.group('fivetriple').split('-'))
                self.assertIn(tuple(sorted((a, b, c))), VALID_TRIPLES)
        self.assertTrue(found_five, 'expected at least one 5p-style name across 200 samples')

    def test_four_slice_three_color_uses_valid_abac(self):
        found_abac = False
        for data in [bytes([i]) for i in range(200)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            if match.group('abac') is not None:
                found_abac = True
                anchor, b, c = (int(part) for part in match.group('abac').split('-'))
                self.assertIn((anchor,) + tuple(sorted((b, c))), VALID_ABAC_TRIPLES)
        self.assertTrue(found_abac, 'expected at least one 4p3-style name across 200 samples')

    def test_four_slice_four_color_uses_valid_quad(self):
        """Unlike the pair/triple pools, a quad's exact stored order matters (only
        some orderings of a given 4 colors satisfy the adjacency rule - see
        VALID_QUADS), so the encoded tuple must match one exactly, not just as a
        sorted/unordered set."""
        found_quad = False
        for data in [bytes([i]) for i in range(200)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            if match.group('quad') is not None:
                found_quad = True
                cycle = tuple(int(part) for part in match.group('quad').split('-'))
                self.assertIn(cycle, VALID_QUADS)
        self.assertTrue(found_quad, 'expected at least one 4p4-style name across 200 samples')

    def test_solid_color_style_uses_a_palette_index(self):
        """The 1-color family (plain solid emblem, no split) picks straight from the
        palette rather than a filtered pool like VALID_PAIRS/VALID_TRIPLES - there's
        no second color for it to need contrast against."""
        found_solo = False
        for data in [bytes([i]) for i in range(200)]:
            name = hash_to_emblem_name(digest_of(data))
            match = NAME_PATTERN.match(name)
            if match.group('solo') is not None:
                found_solo = True
                index = int(match.group('solo'))
                self.assertGreaterEqual(index, 0)
                self.assertLess(index, PALETTE_SIZE)
        self.assertTrue(found_solo, 'expected at least one 1-style name across 200 samples')

    def test_five_slice_pattern_has_no_adjacent_same_color(self):
        """Calls the same five_slice_pie_pattern() that generate_emblems.py renders
        from (not a formula re-derived independently in the test - a prior version of
        this test did that and couldn't have caught a regression in the real pattern
        construction). Verifies it never puts two same-colored slices next to each
        other, including the wrap-around seam, so a 5p emblem never looks like it has
        fewer than 5 visually distinct slices."""
        for triple in VALID_TRIPLES:
            for order in permutations(triple):
                pattern = five_slice_pie_pattern(order)
                for i in range(len(pattern)):
                    self.assertNotEqual(pattern[i], pattern[(i + 1) % len(pattern)])


if __name__ == '__main__':
    unittest.main()
