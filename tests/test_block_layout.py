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
    # Position 3 is disputed: the parser reads "4x12 1960 T75", the operator
    # recalled "4x12 Greenback 25" (which does appear on Path 1 upper 5, so a
    # mis-recollection is plausible). Both are cabs, so assert only that much
    # until someone re-reads that one block on the device.
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

    def test_disputed_slot_is_at_least_a_cab(self):
        slot = self._slot('Path 2 upper', 3)
        names = [n[1] for n in slot.id_to_names() if n]
        categories = [n[0] for n in slot.id_to_names() if n]
        self.assertTrue(names)
        self.assertIn('Cab', categories)

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
