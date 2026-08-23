"""Block layout, checked against a Helix LT screen.

On 2026-08-23 the operator read the signal chain of preset 24 ("ACDC", shown
as 7A) off the device, block by block, and reported bypass states with it.
This file encodes that reading. It is the only ground truth we have for the
row mapping, so it is the thing that stops the parser drifting back into
guesswork.

It settled three questions:
  * the two 20-segment groups are Path 1 and Path 2, each upper and lower
  * the 0x0a bool is `bypassed`, not `enabled` -- it reads inverted
  * the LT has four presets per bank, not the HX Stomp's three (24 -> 7A)
"""
import unittest

from tests.replay import replay_preset_data
from utils.preset_parser import HxPreset, SlotInfo

FIXTURE = 'tests/fixtures/presets/sl2_preset024.jsonl'

# (row, position) -> (name fragment, bypassed) as reported from the device.
# None means the operator saw an empty slot.
GROUND_TRUTH = {
    ('Path 1 upper', 1): ('Red Squeeze', False),
    ('Path 1 upper', 2): ('Studio Tube Pre', False),
    ('Path 1 upper', 3): None,
    ('Path 1 upper', 4): ('Brit Plexi Brt', False),
    ('Path 1 upper', 5): ('Greenback25', False),
    ('Path 1 upper', 6): ('Tile', True),
    ('Path 1 upper', 7): ('Simple EQ', True),
    ('Path 1 upper', 8): ('10 Band Graphic', True),

    ('Path 1 lower', 1): None,
    ('Path 1 lower', 2): None,
    ('Path 1 lower', 3): ('Cali Q Graphic', False),
    ('Path 1 lower', 4): None,

    ('Path 2 upper', 1): None,
    ('Path 2 upper', 2): None,
    # Re-checked on the device 2026-08-23: the parser was right and the first
    # reading was a slip. It is a 4x12 1960 T75.
    ('Path 2 upper', 3): ('1960 T75', False),
    ('Path 2 upper', 4): None,
    ('Path 2 upper', 5): ('Plate', True),
    ('Path 2 upper', 6): ('Simple EQ', True),
    ('Path 2 upper', 7): ('10 Band Graphic', True),
    ('Path 2 upper', 8): ('Glitz', False),

    ('Path 2 lower', 1): None,
    ('Path 2 lower', 2): None,
    ('Path 2 lower', 3): ('Greenback20', False),
    ('Path 2 lower', 4): ('Room', False),
    ('Path 2 lower', 5): None,
}


def _row_index(row_name, position):
    for name, idxs in SlotInfo.ROWS:
        if name == row_name:
            return list(idxs)[position - 1]
    raise KeyError(row_name)


class BlockLayoutGroundTruthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preset = replay_preset_data(FIXTURE).hx_preset

    def _slot(self, row, position):
        return self.preset.slot_info[_row_index(row, position)]

    def test_four_rows_of_eight(self):
        self.assertEqual(4, len(SlotInfo.ROWS))
        for _name, idxs in SlotInfo.ROWS:
            self.assertEqual(8, len(list(idxs)))

    def test_blocks_match_the_device(self):
        for (row, position), expected in GROUND_TRUTH.items():
            slot = self._slot(row, position)
            with self.subTest(row=row, position=position):
                names = [n[1] for n in slot.id_to_names() if n]
                if expected is None:
                    self.assertEqual([], names, 'expected an empty slot')
                    continue
                fragment, _bypassed = expected
                self.assertTrue(any(fragment in n for n in names),
                                'expected %r, got %r' % (fragment, names))

    def test_bypass_states_match_the_device(self):
        """The check that caught the inversion."""
        for (row, position), expected in GROUND_TRUTH.items():
            if expected is None:
                continue
            fragment, bypassed = expected
            slot = self._slot(row, position)
            with self.subTest(row=row, position=position, block=fragment):
                self.assertEqual(bypassed, bool(getattr(slot, 'bypassed', False)))
                self.assertEqual(not bypassed, slot.enabled)

    def test_path2_upper_3_is_the_1960_cab(self):
        slot = self._slot('Path 2 upper', 3)
        names = [n[1] for n in slot.id_to_names() if n]
        self.assertTrue(any('1960 T75' in n for n in names), names)

    def test_enabled_is_the_inverse_of_bypassed(self):
        for slot in self.preset.slot_info:
            if slot is None or not hasattr(slot, 'bypassed'):
                continue
            self.assertEqual(not slot.bypassed, slot.enabled)


class BankNumberingTest(unittest.TestCase):
    """The device shows preset 24 as 7A -- four per bank, not three."""

    def test_presets_per_bank(self):
        self.assertEqual(4, HxPreset.PRESETS_PER_BANK)

    def test_known_mappings(self):
        for preset_no, expected in ((0, '1A'), (24, '7A'), (25, '7B'), (127, '32D')):
            bank = preset_no // HxPreset.PRESETS_PER_BANK + 1
            letter = chr(ord('A') + preset_no % HxPreset.PRESETS_PER_BANK)
            with self.subTest(preset=preset_no):
                self.assertEqual(expected, '%d%s' % (bank, letter))


if __name__ == '__main__':
    unittest.main()


class PresetReferenceTest(unittest.TestCase):
    """Presets must be identifiable the way the device shows them.

    A flat 0-127 index is meaningless to someone standing at the LT, and
    ambiguous across setlists. Anything a person reads needs the bank+letter
    reference and ideally the setlist and preset name too.
    """

    def test_reference_matches_the_device(self):
        for preset_no, expected in ((0, '1A'), (24, '7A'), (25, '7B'),
                                    (120, '31A'), (125, '32B'), (127, '32D')):
            with self.subTest(preset=preset_no):
                self.assertEqual(expected, HxPreset.preset_reference(preset_no))

    def test_reference_handles_nonsense(self):
        self.assertEqual('?', HxPreset.preset_reference(None))
        self.assertEqual('?', HxPreset.preset_reference(-1))

    def test_setlist_display_is_one_based(self):
        self.assertEqual(1, HxPreset.setlist_display(0))
        self.assertEqual(3, HxPreset.setlist_display(2))
        self.assertEqual(8, HxPreset.setlist_display(7))

    def test_every_preset_fixture_is_identifiable(self):
        """Each fixture must carry enough to find it on the device."""
        import glob
        import json
        paths = glob.glob('tests/fixtures/presets/*.jsonl')
        self.assertTrue(paths)
        for path in paths:
            with open(path, encoding='utf-8') as fh:
                meta = json.loads(fh.readline())
            with self.subTest(fixture=path):
                self.assertTrue(meta.get('preset_display'), 'no bank+letter reference')
                self.assertTrue(meta.get('setlist_display'), 'no setlist')
                self.assertTrue(meta.get('preset_name'), 'no preset name')


class LayoutViewTest(unittest.TestCase):
    """HxPreset.to_layout(): the plain-data view the UI consumes."""

    @classmethod
    def setUpClass(cls):
        cls.layout = replay_preset_data(FIXTURE).hx_preset.to_layout()

    def test_shape(self):
        self.assertEqual(4, len(self.layout['rows']))
        for row in self.layout['rows']:
            self.assertEqual(8, len(row['blocks']))
            self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8],
                             [b['position'] for b in row['blocks']])

    def test_carries_routing_and_snapshots(self):
        self.assertEqual(2, len(self.layout['routing']))
        self.assertEqual(8, len(self.layout['snapshot_names']))

    def test_matches_the_device_reading(self):
        rows = {r['name']: r['blocks'] for r in self.layout['rows']}
        self.assertIn('Red Squeeze', rows['Path 1 upper'][0]['name'])
        self.assertIsNone(rows['Path 1 upper'][2]['name'])
        self.assertTrue(rows['Path 1 upper'][5]['bypassed'])       # Tile
        self.assertFalse(rows['Path 2 upper'][7]['bypassed'])      # Glitz

    def test_an_unknown_module_id_is_surfaced_not_swallowed(self):
        """An id missing from modules.py must still read as an occupied slot.

        Tested with a fabricated id rather than by relying on the fixtures
        containing one -- they no longer do, now that all seven have been read
        off the device, and a test that silently stops exercising anything is
        worse than no test.
        """
        preset = replay_preset_data(FIXTURE).hx_preset
        slot = next(s for s in preset.slot_info
                    if s is not None and any(s.id_to_names()))
        original = slot.amp_effect_slot_a
        slot.amp_effect_slot_a = bytes.fromhex('cdffff')
        try:
            layout = preset.to_layout()
        finally:
            slot.amp_effect_slot_a = original
        found = [b for row in layout['rows'] for b in row['blocks']
                 if b.get('unknown_id') == 'cdffff']
        self.assertEqual(1, len(found))
        self.assertEqual('?cdffff', found[0]['name'])
        self.assertEqual('Unknown', found[0]['category'])
