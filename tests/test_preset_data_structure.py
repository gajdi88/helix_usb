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
from utils.preset_parser import HxPreset

SEGMENT_MARKER = '8213'
EMPTY_SLOT_HEAD = '0814c0'
GROUP_MARKERS = {0: '00', 9: '01', 10: '02', 19: '03'}
ASSIGNABLE = [1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 16, 17, 18]
STOMP_FOOTSWITCH_MARKER = '0895'
STOMP_SNAPSHOT_MARKER = '860600070208'
LT_SECTION_BREAK = '089d'
LT_SECTION_END = '04dc'


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

    def test_every_capture_parses_without_error(self):
        """Was a characterisation test pinning the ValueError; now the fix."""
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertIsNone(r.parse_error)
                self.assertIsNotNone(r.hx_preset)


class LtSectionMarkersTest(unittest.TestCase):
    """The LT's own markers, in place of the Stomp's."""

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p) for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')

    def _aligned_count(self, hex_str, marker):
        return sum(1 for i in range(0, len(hex_str) - len(marker) + 1, 2)
                   if hex_str[i:i + len(marker)] == marker)

    def test_section_break_marker_present_exactly_once(self):
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertEqual(1, self._aligned_count(r.hex_str, LT_SECTION_BREAK))

    def test_section_end_marker_follows_the_break(self):
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                tail = r.hex_str[r.hex_str.index(LT_SECTION_BREAK):]
                self.assertIn(LT_SECTION_END, tail)

    def test_forty_slot_sections_extracted(self):
        # Two groups of twenty: the whole point of the layout finding.
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertEqual(40, len(HxPreset.extract_slot_sections(r.hex_str)))

    def test_footswitch_sections_are_bounded(self):
        # Without a terminator the scan manufactures a section per 0xc0 byte
        # in the trailing padding; that produced 545 sections before the fix.
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                n = len(HxPreset.extract_footswitch_sections(r.hex_str))
                self.assertGreater(n, 0)
                self.assertLess(n, 32)

    def test_footswitch_labels_are_recoverable(self):
        r = self.caps['sl2_preset120.jsonl']
        blob = b''.join(HxPreset.extract_footswitch_sections(r.hex_str))
        for label in (b'Kinky Boost', b'GrammaticoLG Brt', b'6 Switch Looper'):
            self.assertIn(label, blob)

    def test_empty_preset_has_no_footswitch_labels(self):
        r = self.caps['sl3_preset127_empty.jsonl']
        blob = b''.join(HxPreset.extract_footswitch_sections(r.hex_str))
        self.assertFalse([b for b in blob if 32 <= b <= 126],
                         'empty preset should carry no printable footswitch labels')

    def test_known_blocks_are_named(self):
        """End to end: bytes off the wire to named modules."""
        r = self.caps['sl2_preset120.jsonl']
        names = []
        for slot in r.hx_preset.slot_info[:20]:
            if slot is None:
                continue
            info = slot.id_to_names()
            for entry in info:
                if entry:
                    names.append(entry[1])
        joined = ' '.join(names)
        self.assertIn('Kinky Boost', joined)
        self.assertIn('Deluxe Comp', joined)


class SnapshotNamesTest(unittest.TestCase):
    """Snapshot names, stored as 04 <0xA1+len> <ascii>.

    The LT holds eight snapshots against the HX Stomp's three, and each is a
    fixed-size block opening with its name.
    """

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p) for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')

    def test_every_capture_yields_eight(self):
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                self.assertEqual(8, len(r.hx_preset.snapshot_names))

    def test_names_are_plausible_strings(self):
        for name, r in self.caps.items():
            for idx, snap in enumerate(r.hx_preset.snapshot_names):
                with self.subTest(fixture=name, snapshot=idx):
                    self.assertTrue(snap)
                    self.assertTrue(all(32 <= ord(c) <= 126 for c in snap))

    def test_custom_names_decode(self):
        """The real proof: user-set names, not the default template.

        If the parser were matching a fixed pattern rather than reading the
        stored strings, these would come back as SNAPSHOT 1/2/3.
        """
        self.assertEqual(['lead', 'rhytm'],
                         self.caps['sl2_preset120.jsonl'].hx_preset.snapshot_names[:2])
        self.assertEqual(['spring', 'dd', 'deluxe'],
                         self.caps['sl2_preset096.jsonl'].hx_preset.snapshot_names[:3])

    def test_untouched_snapshots_keep_default_names(self):
        empty = self.caps['sl3_preset127_empty.jsonl'].hx_preset.snapshot_names
        self.assertEqual(['SNAPSHOT %d' % i for i in range(1, 9)], empty)

    def test_snapshot_prefix_does_not_collide_with_footswitch_labels(self):
        # Snapshot names use prefix 0x04, footswitch labels 0x05.
        r = self.caps['sl2_preset120.jsonl']
        fs_blob = b''.join(HxPreset.extract_footswitch_sections(r.hex_str))
        for snap in ('lead', 'rhytm'):
            self.assertNotIn(snap.encode(), fs_blob)
        for label in (b'Kinky Boost', b'6 Switch Looper'):
            self.assertIn(label, fs_blob)


if __name__ == '__main__':
    unittest.main()
