"""Display order, measured by a Program Change sweep.

The name enumeration returns storage order. Program Change addresses display
position. Sweeping PC 0-127 and reading the name the device announces for each
is the only way found so far to read display order off the LT.

Done 2026-08-23 on setlist USER 1 (wire 2, shown as 3). It confirmed the
operator's readings exactly and let the preset-data fixtures be relabelled
correctly for the first time.
"""
import json
import os
import unittest

from utils.packet_recorder import load_capture

FIXTURE = 'tests/fixtures/live/display_order_sweep.jsonl'
STORAGE = 'tests/fixtures/lt_setlist2.jsonl'


def parse_announcements(pkts):
    """(preset number, name) pairs the device sends on each change."""
    out = {}
    for p in pkts:
        s = p['bytes'][16:]
        num = name = None
        i = 0
        while i < len(s) - 3:
            if s[i] == 0x6c and s[i + 1] == 0xcd:
                num = (s[i + 2] << 8) | s[i + 3]
                i += 4
                continue
            if s[i] == 0x6d and 0xa1 < s[i + 1] < 0xc0:
                length = s[i + 1] - 0xa1
                raw = s[i + 2:i + 2 + length]
                if len(raw) == length and all(32 <= c <= 126 for c in raw):
                    name = ''.join(chr(c) for c in raw)
                    i += 2 + length
                    continue
            i += 1
        if num is not None and name is not None:
            out.setdefault(num, name)
    return out


class DisplayOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(FIXTURE):
            raise unittest.SkipTest('display-order fixture missing')
        _meta, pkts = load_capture(FIXTURE)
        cls.display = parse_announcements(pkts)
        with open(STORAGE, encoding='utf-8') as fh:
            cls.storage = json.loads(fh.readline())['expect']['names_by_index']

    def test_all_128_slots_mapped(self):
        self.assertEqual(128, len(self.display))
        self.assertEqual(set(range(128)), set(self.display))

    def test_matches_what_the_operator_read_off_the_device(self):
        """Every slot the operator reported, independently measured."""
        for slot, expected in ((25, 'A30 Fawn Brt'), (36, 'HendrixWind'),
                               (84, 'DistortedSoloAir'), (120, 'GilmRhytLead'),
                               (125, 'TwoPrinces'), (24, 'ACDC'),
                               (0, 'Run Like'), (20, 'BluesyOd')):
            with self.subTest(slot=slot):
                self.assertEqual(expected, self.display[slot])

    def test_display_and_storage_differ(self):
        differing = [n for n in range(128) if self.display[n] != self.storage[str(n)]]
        self.assertTrue(differing, 'if these ever agree, the divergence is gone')
        self.assertEqual(25, min(differing))

    def test_the_permutation_is_a_single_move(self):
        """One preset moved to the end; everything after it shifted by one.

        Storage 0-24 unchanged, storage 26-125 shifted down one, storage 25
        (TwoPrinces) landing at display 125.
        """
        for n in range(25):
            self.assertEqual(self.storage[str(n)], self.display[n])
        for n in range(25, 125):
            self.assertEqual(self.storage[str(n + 1)], self.display[n])
        self.assertEqual(self.storage['25'], self.display[125])
        for n in (126, 127):
            self.assertEqual(self.storage[str(n)], self.display[n])


class PresetFixtureLabellingTest(unittest.TestCase):
    """The preset-data fixtures are now labelled from display order."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(FIXTURE):
            raise unittest.SkipTest('display-order fixture missing')
        _meta, pkts = load_capture(FIXTURE)
        cls.display = parse_announcements(pkts)

    def test_names_match_the_program_change_used_to_capture_them(self):
        import glob
        import re
        paths = glob.glob('tests/fixtures/presets/sl2_preset*.jsonl')
        self.assertTrue(paths)
        for path in paths:
            pc = int(re.search(r'sl2_preset(\d+)', path).group(1))
            with open(path, encoding='utf-8') as fh:
                meta = json.loads(fh.readline())
            with self.subTest(fixture=os.path.basename(path)):
                self.assertEqual(self.display[pc], meta['preset_name'])
                self.assertTrue(meta['preset_name_reliable'])
                self.assertEqual('USER 1', meta['setlist_name'])


if __name__ == '__main__':
    unittest.main()
