"""Split and merge geometry.

PROVISIONAL until A2. Everything here is derived from three presets agreeing
plus one operator description; nothing has yet been falsified by changing a
split on the device and re-capturing. If A2 contradicts it, this file is the
thing to update, not the evidence.

The operator's reading of preset 24 on 2026-08-23:
  Path 1 - Y split after upper block 4, lower branch carrying one EQ, merging
           back "just before the very end".
  Path 2 - A/B split at upper position 3, lower branch carrying a cab and a
           reverb, merging back before Plate at upper position 5.
"""
import os
import unittest

from tests.replay import preset_fixture_paths, replay_preset_data
from utils.preset_parser import HxPreset

SERIAL = ('sl2_preset036.jsonl', 'sl2_preset048.jsonl', 'sl2_preset000.jsonl',
          'sl3_preset127_empty.jsonl')


class RoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p).hx_preset
                    for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')

    def _path(self, fixture, path_no):
        for entry in self.caps[fixture].routing:
            if entry['path'] == path_no:
                return entry
        self.fail('no path %d in %s' % (path_no, fixture))

    def test_every_preset_reports_both_paths(self):
        for name, preset in self.caps.items():
            with self.subTest(fixture=name):
                self.assertEqual([1, 2], [e['path'] for e in preset.routing])

    def test_preset24_path1_matches_the_device(self):
        """Y split after block 4, merging at the output."""
        p1 = self._path('sl2_preset024.jsonl', 1)
        self.assertEqual(5, p1['split_position'])
        self.assertTrue(p1['merges_at_output'])
        self.assertIsNone(p1['merge_position'])

    def test_preset24_path2_matches_the_device(self):
        """A/B split at 3, merging back at 5, before Plate."""
        p2 = self._path('sl2_preset024.jsonl', 2)
        self.assertEqual(3, p2['split_position'])
        self.assertEqual(5, p2['merge_position'])
        self.assertFalse(p2['merges_at_output'])

    def test_serial_presets_report_no_split(self):
        for name in SERIAL:
            for entry in self.caps[name].routing:
                with self.subTest(fixture=name, path=entry['path']):
                    self.assertIsNone(entry['split_position'])
                    self.assertIsNone(entry['merge_position'])
                    self.assertFalse(entry['merges_at_output'])

    def test_a_split_always_has_a_described_destination(self):
        """Weakened by evidence, deliberately.

        This began as "a split branch must rejoin, at a numbered position or
        at the path output". The A2 baseline disproved it: the operator built
        a Path 1 that splits and never merges, because the lower branch exits
        to the output on its own while the upper branch feeds Path 2. That
        path reports merge_flag 1 with no merge position.

        So the real invariant is weaker: a split always has its destination
        described somehow, by a merge position or by a non-zero flag.
        """
        for name, preset in self.caps.items():
            for entry in preset.routing:
                if not entry['split_position']:
                    continue
                with self.subTest(fixture=name, path=entry['path']):
                    self.assertTrue(entry['merge_position']
                                    or entry['merges_at_output']
                                    or entry['merge_flag'],
                                    'split with no destination described')

    def test_a2_baseline_matches_the_operator_build(self):
        """Predicted before the capture was parsed, then confirmed.

        The operator built this preset deliberately: one block at position 5
        on each of the four rows, a split just before block 5 on both paths,
        a merge just after block 5 on Path 2 only. Predicted split 5/5 and
        merge None/6; got exactly that.
        """
        fixture = 'a2_routing_baseline.jsonl'
        if fixture not in self.caps:
            self.skipTest('A2 baseline not present')
        p1 = self._path(fixture, 1)
        p2 = self._path(fixture, 2)
        self.assertEqual(5, p1['split_position'])
        self.assertIsNone(p1['merge_position'])
        self.assertEqual(5, p2['split_position'])
        self.assertEqual(6, p2['merge_position'])

    def test_split_positions_are_within_the_row(self):
        for name, preset in self.caps.items():
            for entry in preset.routing:
                for key in ('split_position', 'merge_position'):
                    value = entry[key]
                    if value is None:
                        continue
                    with self.subTest(fixture=name, path=entry['path'], field=key):
                        self.assertGreaterEqual(value, 1)
                        self.assertLessEqual(value, 8)

    def test_merge_at_output_flag_value(self):
        self.assertEqual(2, HxPreset.MERGE_AT_OUTPUT)

    def test_a_populated_lower_row_always_shows_routing(self):
        """Cross-check against the slot data, parsed from a different place.

        A lower row with blocks in it must be reachable, so the endpoints have
        to say something about routing. This started as the stronger claim
        that it implies a `split_position`, and that failed: presets 84, 125
        and 127 carry a full Path 2 lower row from position 1 with
        `split_position` unset, and `merge_flag` of 12, 12 and 1.

        The likely reading is that those paths split at the input rather than
        mid-row, so the position is 0 and the mode lives in the flag -- but
        that is a guess from three presets, so the assertion here is only the
        part that holds: routing is described one way or the other.
        """
        rows = {1: 'Path 1 lower', 2: 'Path 2 lower'}
        from utils.preset_parser import SlotInfo
        for name, preset in self.caps.items():
            for entry in preset.routing:
                idxs = next(i for n, i in SlotInfo.ROWS if n == rows[entry['path']])
                occupied = [i for i in idxs
                            if preset.slot_info[i] is not None
                            and any(preset.slot_info[i].id_to_names())]
                if not occupied:
                    continue
                with self.subTest(fixture=name, path=entry['path']):
                    self.assertTrue(entry['split_position'] or entry['merge_flag'],
                                    'lower row has blocks but routing says nothing')

    def test_unsplit_paths_with_an_empty_lower_row_are_inert(self):
        """The converse: no blocks, no split, and a zero flag."""
        rows = {1: 'Path 1 lower', 2: 'Path 2 lower'}
        from utils.preset_parser import SlotInfo
        for name, preset in self.caps.items():
            for entry in preset.routing:
                idxs = next(i for n, i in SlotInfo.ROWS if n == rows[entry['path']])
                occupied = [i for i in idxs
                            if preset.slot_info[i] is not None
                            and any(preset.slot_info[i].id_to_names())]
                if occupied or entry['split_position']:
                    continue
                with self.subTest(fixture=name, path=entry['path']):
                    self.assertFalse(entry['merge_flag'],
                                     'empty unsplit path carries a routing flag')


if __name__ == '__main__':
    unittest.main()
