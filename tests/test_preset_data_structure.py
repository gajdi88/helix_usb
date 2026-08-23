"""Structure of Helix LT preset data, derived from captures.

Nothing here was known when these fixtures were recorded. It was worked out by
diffing an empty preset against populated ones, and every claim is asserted
against all 15 captures so it cannot rot silently.

The headline: the LT's preset payload is upstream's HX Stomp layout **twice**.
Upstream splits on `8213` and expects 20 segments -- one marker, 8 slots, two
markers, 8 slots, one marker -- with 16 assignable slots. The LT emits 41
segments: a header, then that same 20-segment group repeated, giving 32
assignable slot positions across its two DSP paths.
"""
import os
import unittest

from tests.replay import preset_fixture_paths, replay_preset_data

SEGMENT_MARKER = '8213'
EMPTY_SLOT_HEAD = '0814c0'
GROUP_MARKERS = {0: '00', 9: '01', 10: '02', 19: '03'}
ASSIGNABLE = [1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 16, 17, 18]
STOMP_FOOTSWITCH_MARKER = '0895'
STOMP_SNAPSHOT_MARKER = '860600070208'


def groups_of(hex_str):
    """The two 20-segment groups that follow the header segment."""
    seg = hex_str.split(SEGMENT_MARKER)
    return seg, [seg[1:21], seg[21:41]]


def occupied_slots(hex_str):
    _seg, groups = groups_of(hex_str)
    out = []
    for gi, group in enumerate(groups, start=1):
        for si in ASSIGNABLE:
            if not group[si].startswith(EMPTY_SLOT_HEAD):
                out.append((gi, si))
    return out


class PresetDataStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p) for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')

    def test_fixtures_yield_payload(self):
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertGreater(len(r.preset_data), 1000)

    def test_every_capture_has_41_segments(self):
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertEqual(41, len(r.hex_str.split(SEGMENT_MARKER)))

    def test_segment_marker_is_byte_aligned(self):
        # Splitting a hex *string* would silently corrupt the layout if the
        # marker ever landed on an odd nibble boundary.
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                for seg in r.hex_str.split(SEGMENT_MARKER):
                    self.assertEqual(0, len(seg) % 2, 'segment split mid-byte')

    def test_both_groups_carry_the_same_marker_layout(self):
        for name, r in self.caps.items():
            _seg, groups = groups_of(r.hex_str)
            for gi, group in enumerate(groups, start=1):
                for idx, prefix in GROUP_MARKERS.items():
                    with self.subTest(fixture=name, group=gi, segment=idx):
                        self.assertEqual(20, len(group))
                        self.assertTrue(group[idx].startswith(prefix),
                                        'segment %d starts %r, expected %r'
                                        % (idx, group[idx][:4], prefix))

    def test_empty_preset_has_no_occupied_slots(self):
        """The control that makes the whole model credible."""
        empty = self.caps.get('sl3_preset127_empty.jsonl')
        self.assertIsNotNone(empty, 'the empty-preset fixture is the control; do not remove it')
        self.assertEqual([], occupied_slots(empty.hex_str))

    def test_populated_presets_have_occupied_slots(self):
        for name, r in self.caps.items():
            if 'empty' in name:
                continue
            with self.subTest(fixture=name):
                n = len(occupied_slots(r.hex_str))
                self.assertGreater(n, 0)
                self.assertLessEqual(n, len(ASSIGNABLE) * 2)


class StompMarkersAbsentTest(unittest.TestCase):
    """Why the inherited parser fails on every LT preset."""

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p) for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')

    def test_footswitch_marker_never_appears(self):
        # utils/preset_parser.py does data.index('0895') and raises ValueError.
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertNotIn(STOMP_FOOTSWITCH_MARKER, r.hex_str)

    def test_snapshot_marker_never_appears(self):
        # modes/request_preset.py tests for this to detect the active snapshot,
        # so snapshot reporting is silently dead on the LT too.
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertNotIn(STOMP_SNAPSHOT_MARKER, r.hex_str)

    def test_parsing_currently_fails(self):
        """Characterisation test: records today's breakage, not desired behaviour.

        When the footswitch parser is taught the LT layout this will start
        failing. That is the point -- update it then; do not delete it now.
        """
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertIsInstance(r.parse_error, ValueError)
                self.assertIn('substring not found', str(r.parse_error))


if __name__ == '__main__':
    unittest.main()
