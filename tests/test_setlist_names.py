"""Setlist names, from query 0x3e9.

The query was commented out in request_preset_names.py, inherited from
upstream. On the Helix LT it returns the eight setlist names, which matters
because the front panel labels setlists by name: wire index 2 is "USER 1", not
"setlist 3". Referring to a setlist by position has caused repeated confusion.
"""
import os
import unittest

from helix_usb import HelixUsb
from modes.request_setlist_names import RequestSetlistNames
from tests.replay import ReplayHelixUsb
from utils.packet_recorder import load_capture

FIXTURE = 'tests/fixtures/live/setlist_names.jsonl'
EXPECTED = ['FACTORY 1', 'FACTORY 2', 'USER 1', 'USER 2',
            'Send1', 'ExtCab', 'USER 5', 'TEMPLATES']


class SetlistNameParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(FIXTURE):
            raise unittest.SkipTest('setlist-name fixture missing')
        _meta, pkts = load_capture(FIXTURE)
        cls.stream = [b for p in pkts
                      if len(p['bytes']) > 16 and p['bytes'][4] == 0xef and p['bytes'][11] == 0x04
                      for b in p['bytes'][16:]]

    def test_all_eight_decode(self):
        names = RequestSetlistNames.parse_setlist_names(self.stream)
        self.assertEqual(8, len(names))
        self.assertEqual(EXPECTED, [names[i] for i in range(8)])

    def test_user_5_is_not_setlist_5(self):
        """The mistake this fixes: the operator names setlists, I numbered them."""
        names = RequestSetlistNames.parse_setlist_names(self.stream)
        self.assertEqual('USER 5', names[6])
        self.assertNotEqual('USER 5', names[4])

    def test_captures_came_from_user_1(self):
        names = RequestSetlistNames.parse_setlist_names(self.stream)
        self.assertEqual('USER 1', names[2])

    def test_parser_ignores_noise(self):
        self.assertEqual({}, RequestSetlistNames.parse_setlist_names([0x00] * 64))


class SetlistLabelTest(unittest.TestCase):
    def setUp(self):
        self.helix = ReplayHelixUsb()

    def test_label_falls_back_to_the_number(self):
        self.assertEqual('setlist 3', self.helix.setlist_label(2))

    def test_label_uses_the_name_once_known(self):
        self.helix.set_setlist_names(EXPECTED)
        self.assertEqual('USER 1 (setlist 3)', self.helix.setlist_label(2))
        self.assertEqual('USER 5 (setlist 7)', self.helix.setlist_label(6))

    def test_display_number_is_one_based(self):
        self.assertEqual(1, HelixUsb.setlist_display_number(0))
        self.assertEqual(8, HelixUsb.setlist_display_number(7))

    def test_names_are_published_once(self):
        seen = []
        self.helix.register_setlist_names_change_cb_fct(seen.append)
        self.helix.set_setlist_names(EXPECTED)
        self.helix.set_setlist_names(EXPECTED)
        self.assertEqual(1, len(seen))


class SetlistModeReplayTest(unittest.TestCase):
    """Drive the real mode with the captured reply."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(FIXTURE):
            raise unittest.SkipTest('setlist-name fixture missing')

    def test_mode_publishes_the_names(self):
        _meta, pkts = load_capture(FIXTURE)
        helix = ReplayHelixUsb()
        mode = RequestSetlistNames(helix)
        helix.active_mode = mode
        mode.start()
        try:
            for p in pkts:
                helix.data_in('0x81', p['bytes'])
            mode._finish()
        finally:
            mode._cancel_idle_watchdog()
        self.assertEqual(EXPECTED, helix.setlist_names)


if __name__ == '__main__':
    unittest.main()
