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
        """Y split after block 4. The merge is not represented as a position.

        The operator described a merge "just before the very end" here, but no
        merge position is recorded and merge_flag reads 2. Since A2 showed a
        merge at the end is stored as position 9, flag 2 means something else
        that is still unexplained.
        """
        p1 = self._path('sl2_preset024.jsonl', 1)
        self.assertEqual(5, p1['split_position'])
        self.assertIsNone(p1['merge_position'])
        self.assertEqual(2, p1['merge_flag'])

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
                        # 9 is the path output, a legal merge target.
                        self.assertLessEqual(value, 9)

    def test_merge_at_output_is_position_nine(self):
        self.assertEqual(9, HxPreset.MERGE_AT_OUTPUT_POSITION)
        moved = self._path('a2_routing_moved.jsonl', 1)
        self.assertTrue(moved['merges_at_output'])

    def test_a_populated_lower_row_always_shows_routing(self):
        """Cross-check against the slot data, parsed from a different place.

        A lower row with blocks in it must be reachable, so the endpoints have
        to say something about routing. This started as the stronger claim
        that it implies a `split_position`, and that failed: presets 84, 125
        and 127 carry a full Path 2 lower row from position 1 with
        `split_position` unset, and `merge_flag` of 12, 12 and 1.

        That was resolved by the fan-out capture: a lower row can be fed from
        an *upstream path* instead of by its own split. Setting Path 1's exit
        to feed both Path 2 rows made Path 2's split disappear while its lower
        row stayed populated -- exactly the shape presets 84, 125 and 127 have.

        So a populated lower row must be reachable one of two ways: its own
        split, or an upstream exit fanning into it.
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
                fed_from_upstream = any(
                    other['upper_exit'] == 4 or other['lower_exit'] == 4
                    for other in preset.routing if other['path'] < entry['path'])
                with self.subTest(fixture=name, path=entry['path']):
                    self.assertTrue(entry['split_position']
                                    or entry['lower_exit']
                                    or fed_from_upstream,
                                    'lower row has blocks but nothing feeds it')

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


class RoutingFalsificationTest(unittest.TestCase):
    """A2: the same preset captured before and after moving its routing.

    This is the only evidence that the fields mean what they are named rather
    than correlating by chance on presets that happened to exist. Predictions
    were written down before either capture was parsed.
    """

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p).hx_preset
                    for p in preset_fixture_paths()}
        for needed in ('a2_routing_baseline.jsonl', 'a2_routing_moved.jsonl'):
            if needed not in cls.caps:
                raise unittest.SkipTest('missing %s' % needed)

    def _routing(self, fixture):
        return {e['path']: e for e in self.caps[fixture].routing}

    def test_edits_moved_the_recorded_values(self):
        before = self._routing('a2_routing_baseline.jsonl')
        after = self._routing('a2_routing_moved.jsonl')

        # Path 2: split one position left, merge one position right.
        self.assertEqual((5, 6), (before[2]['split_position'], before[2]['merge_position']))
        self.assertEqual((4, 7), (after[2]['split_position'], after[2]['merge_position']))

        # Path 1: split moved to the very start, merge added at the very end.
        self.assertEqual(5, before[1]['split_position'])
        self.assertIsNone(before[1]['merge_position'])
        self.assertEqual(1, after[1]['split_position'])
        self.assertEqual(9, after[1]['merge_position'])

    def test_blocks_did_not_move(self):
        """Only routing changed, so the block layout must be identical."""
        from utils.preset_parser import SlotInfo
        for _name, idxs in SlotInfo.ROWS:
            for i in idxs:
                before = self.caps['a2_routing_baseline.jsonl'].slot_info[i]
                after = self.caps['a2_routing_moved.jsonl'].slot_info[i]
                with self.subTest(slot=i):
                    self.assertEqual(
                        [n[1] for n in before.id_to_names() if n] if before else None,
                        [n[1] for n in after.id_to_names() if n] if after else None)


class ExitDestinationTest(unittest.TestCase):
    """Each chain ends in an exit node whose property is its destination.

    Explained by the operator from the device UI: the node after the last
    merge on a chain has a property setting where its signal goes -- another
    path, both of them, or a physical output such as XLR or TRS. That is what
    marker 0x06 on the chain's output endpoint carries. It had been
    mis-modelled as a merge flag, which is why values 1, 2, 6 and 12 never
    fitted a merge story.
    """

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p).hx_preset
                    for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')

    def _p(self, fixture, path_no):
        return next(e for e in self.caps[fixture].routing if e['path'] == path_no)

    def test_preset24_exits_match_the_operator_reading(self):
        """Path 1 upper ended in "output to multi", lower in "output to path A"."""
        p1 = self._p('sl2_preset024.jsonl', 1)
        self.assertEqual('Multi output', p1['upper_exit_name'])
        self.assertEqual('Path 2A', p1['lower_exit_name'])

    def test_a2_baseline_exits_are_the_other_way_round(self):
        """1A fed Path 2A while 1B went straight to the output.

        The reverse of preset 24, so the two readings corroborate rather than
        restate each other.
        """
        p1 = self._p('a2_routing_baseline.jsonl', 1)
        self.assertEqual('Path 2A', p1['upper_exit_name'])
        self.assertEqual('Multi output', p1['lower_exit_name'])

    def test_merging_a_chain_clears_its_exit(self):
        """After Path 1 was merged at the end, the lower chain has no exit."""
        before = self._p('a2_routing_baseline.jsonl', 1)
        after = self._p('a2_routing_moved.jsonl', 1)
        self.assertEqual('Multi output', before['lower_exit_name'])
        self.assertEqual('merged', after['lower_exit_name'])
        self.assertEqual('Path 2A', after['upper_exit_name'])

    def test_the_last_path_usually_reaches_a_physical_output(self):
        # Path 2 upper is the end of the chain in nearly every preset.
        names = [self._p(f, 2)['upper_exit_name'] for f in self.caps]
        self.assertGreater(names.count('Multi output'), len(names) * 0.8)

    def test_unknown_values_are_reported_not_hidden(self):
        self.assertEqual('unknown (99)', HxPreset.exit_destination_name(99))
        self.assertIsNone(HxPreset.exit_destination_name(None))

    def test_physical_output_destinations(self):
        """6 and 12 named from the operator reading three presets.

        Each capture's exit value matched the output the operator named for
        that preset, and only under the display-position reading of which
        preset the capture came from -- see PresetSelectionMappingTest.
        """
        self.assertEqual('XLR', HxPreset.exit_destination_name(6))
        self.assertEqual('USB 5/6', HxPreset.exit_destination_name(12))

    def test_captures_carry_the_named_outputs(self):
        cases = [('sl2_preset120.jsonl', 2, 'upper_exit', 6),
                 ('sl2_preset084.jsonl', 2, 'lower_exit', 12),
                 ('sl2_preset125.jsonl', 2, 'lower_exit', 12)]
        for fixture, path_no, field, expected in cases:
            if fixture not in self.caps:
                continue
            with self.subTest(fixture=fixture):
                self.assertEqual(expected, self._p(fixture, path_no)[field])

    def test_a_merged_lower_chain_never_also_has_an_exit(self):
        """0 means merged, so it should not co-occur with a merge position
        pointing somewhere else... except it can, and that is the point:
        assert only that the value is one we have seen, so a new one surfaces
        as a failure rather than being silently renamed 'unknown'.
        """
        seen = {0, 1, 2, 4, 6, 12}
        for name, preset in self.caps.items():
            for entry in preset.routing:
                for key in ('upper_exit', 'lower_exit'):
                    with self.subTest(fixture=name, path=entry['path'], field=key):
                        self.assertIn(entry[key], seen)


class FanOutTest(unittest.TestCase):
    """Exit value 4 feeds both rows of the next path.

    Predicted 6 or 12 before capturing; it is 4. The prediction was wrong, but
    the capture answered a second question that had not been asked: Path 2's
    split vanished, because a row fed from upstream does not need one.
    """

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p).hx_preset
                    for p in preset_fixture_paths()}
        for needed in ('a2_routing_moved.jsonl', 'a2_routing_fanout.jsonl'):
            if needed not in cls.caps:
                raise unittest.SkipTest('missing %s' % needed)

    def _p(self, fixture, path_no):
        return next(e for e in self.caps[fixture].routing if e['path'] == path_no)

    def test_exit_four_is_named(self):
        self.assertEqual('Path 2A + Path 2B', HxPreset.exit_destination_name(4))

    def test_fanning_out_changes_only_the_exit_on_path_one(self):
        before = self._p('a2_routing_moved.jsonl', 1)
        after = self._p('a2_routing_fanout.jsonl', 1)
        self.assertEqual('Path 2A', before['upper_exit_name'])
        self.assertEqual('Path 2A + Path 2B', after['upper_exit_name'])
        # The split and merge on Path 1 were untouched.
        self.assertEqual(before['split_position'], after['split_position'])
        self.assertEqual(before['merge_position'], after['merge_position'])

    def test_fanning_out_removes_the_downstream_split(self):
        """The unpredicted result, and the more useful one."""
        before = self._p('a2_routing_moved.jsonl', 2)
        after = self._p('a2_routing_fanout.jsonl', 2)
        self.assertEqual(4, before['split_position'])
        self.assertIsNone(after['split_position'])
        # The merge stays: the two rows still rejoin at 7.
        self.assertEqual(7, after['merge_position'])

    def test_downstream_lower_row_is_still_populated(self):
        from utils.preset_parser import SlotInfo
        preset = self.caps['a2_routing_fanout.jsonl']
        idxs = next(i for n, i in SlotInfo.ROWS if n == 'Path 2 lower')
        occupied = [i for i in idxs
                    if preset.slot_info[i] and any(preset.slot_info[i].id_to_names())]
        self.assertTrue(occupied, 'the point of the test is a fed row with no split')


class PresetSelectionMappingTest(unittest.TestCase):
    """MIDI Program Change selects by display position, not storage index.

    The preset-name enumeration returns names against a *storage* index. The
    operator had moved a preset, so the device's display order no longer
    matches that index: the enumeration reports TwoPrinces at index 25 while
    the device shows A30 Fawn Brt at 7B.

    All 15 preset-data captures were selected with MIDI Program Change, so
    which preset each one actually holds depended on this. It was settled by
    the operator naming the Path 2 output of three presets by their *display*
    slot; every capture's exit value matched the display reading and PC 120
    contradicted the storage reading outright.

    Consequence: `preset_name` on those fixtures came from the storage index
    and is unreliable. The captured bytes are unaffected.
    """

    def test_preset_fixtures_declare_how_they_were_selected(self):
        import glob
        import json
        for path in glob.glob('tests/fixtures/presets/sl2_preset*.jsonl'):
            with open(path, encoding='utf-8') as fh:
                meta = json.loads(fh.readline())
            with self.subTest(fixture=os.path.basename(path)):
                self.assertIn('Program Change', meta.get('selected_by', ''))
                self.assertFalse(meta.get('preset_name_reliable', True),
                                 'storage-index name must not be presented as reliable')

    def test_storage_index_and_display_slot_disagree(self):
        """Guards the finding itself: if they ever agree again, revisit this."""
        import json
        names = json.loads(
            open('tests/fixtures/lt_setlist2.jsonl').readline())['expect']['names_by_index']
        # Operator, at the device: 7B is A30 Fawn Brt. Enumeration says index 25.
        self.assertEqual('TwoPrinces', names['25'])
        self.assertEqual('A30 Fawn Brt', names['26'])
