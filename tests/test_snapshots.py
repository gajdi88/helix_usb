"""Snapshot handling: the stored index, and live change events.

Both were worked out on 2026-08-23. The stored index came from capturing one
preset on snapshot 1 and again on snapshot 3; the live event came from a
session capture recorded while the operator pressed through snapshots on the
device. Neither is inferred from the HX Stomp layout, which does not apply --
the Stomp's 8606 0N 07 02 08 sequence never occurs on the LT.
"""
import os
import unittest

from helix_usb import HelixUsb
from modes.request_preset import RequestPreset
from tests.replay import (ReplayHelixUsb, live_fixture_paths, preset_fixture_paths,
                          replay_preset_data, replay_standard)


class StoredSnapshotTest(unittest.TestCase):
    """The active snapshot saved in preset data: byte 2 of the 8606 record."""

    @classmethod
    def setUpClass(cls):
        cls.caps = {os.path.basename(p): replay_preset_data(p) for p in preset_fixture_paths()}
        if not cls.caps:
            raise unittest.SkipTest('no preset-data fixtures')
        cls.mode = RequestPreset(ReplayHelixUsb())

    def test_every_capture_reports_a_snapshot_in_range(self):
        for name, r in self.caps.items():
            with self.subTest(fixture=name):
                snap = self.mode.extract_active_snapshot(r.hex_str)
                self.assertIsNotNone(snap)
                self.assertGreaterEqual(snap, 1)
                self.assertLessEqual(snap, HelixUsb.SNAPSHOT_COUNT)

    def test_presets_saved_on_other_snapshots(self):
        """Corroborated independently: these are exactly the captures whose
        snapshot names were customised, which is what you would expect of a
        preset someone actually worked on."""
        self.assertEqual(2, self.mode.extract_active_snapshot(
            self.caps['sl2_preset120.jsonl'].hex_str))
        self.assertEqual(3, self.mode.extract_active_snapshot(
            self.caps['sl2_preset096.jsonl'].hex_str))
        self.assertEqual(1, self.mode.extract_active_snapshot(
            self.caps['sl3_preset127_empty.jsonl'].hex_str))

    def test_index_is_read_byte_aligned(self):
        # A nibble-offset match would read a different byte entirely.
        r = self.caps['sl2_preset096.jsonl']
        shifted = '0' + r.hex_str          # break byte alignment
        self.assertNotEqual(3, self.mode.extract_active_snapshot(shifted))

    def test_missing_record_returns_none(self):
        self.assertIsNone(self.mode.extract_active_snapshot('00' * 64))


class LiveSnapshotEventTest(unittest.TestCase):
    """Snapshot changes pressed on the device, seen through Standard mode."""

    @classmethod
    def setUpClass(cls):
        paths = live_fixture_paths()
        if not paths:
            raise unittest.SkipTest('no live fixtures')
        cls.results = {os.path.basename(p): replay_standard(p) for p in paths}

    def test_presses_are_reported_in_order(self):
        for name, r in self.results.items():
            expected = r.expect.get('snapshot_presses')
            if not expected:
                continue
            with self.subTest(fixture=name):
                # Startup traffic also reports snapshot state; the deliberate
                # presses are the tail of the sequence.
                self.assertEqual(expected, r.snapshots[-len(expected):])

    def test_snapshot_values_stay_in_range(self):
        for name, r in self.results.items():
            for snap in r.snapshots:
                with self.subTest(fixture=name, snapshot=snap):
                    self.assertGreaterEqual(snap, 1)
                    self.assertLessEqual(snap, HelixUsb.SNAPSHOT_COUNT)


class SetSnapshotBoundsTest(unittest.TestCase):
    def setUp(self):
        self.helix = ReplayHelixUsb()
        self.seen = []
        self.helix.register_snapshot_change_cb_fct(self.seen.append)

    def test_accepts_the_full_lt_range(self):
        for n in range(1, HelixUsb.SNAPSHOT_COUNT + 1):
            self.helix.set_snapshot(n)
        self.assertEqual(list(range(1, HelixUsb.SNAPSHOT_COUNT + 1)), self.seen)

    def test_rejects_out_of_range(self):
        for bad in (0, -1, HelixUsb.SNAPSHOT_COUNT + 1, 99):
            self.helix.set_snapshot(bad)
        self.assertEqual([], self.seen)

    def test_repeat_of_current_value_is_not_reported(self):
        # Each press emits two messages; the second must not double-fire.
        self.helix.set_snapshot(4)
        self.helix.set_snapshot(4)
        self.assertEqual([4], self.seen)


if __name__ == '__main__':
    unittest.main()


class ProgramChangeIndexTest(unittest.TestCase):
    """Program Change and the name enumeration use different indices.

    Captured 2026-08-23: PC 25 was sent and the device asked what it had
    loaded. It answered "A30 Fawn Brt" with preset tag 25, while the name
    enumeration lists TwoPrinces at storage index 25. The operator had moved
    TwoPrinces to the end of the setlist.

    This is why preset names on the sl2_preset* fixtures are unreliable: those
    captures were selected by Program Change (display position) and then
    labelled from the enumeration (storage index).
    """

    FIXTURE = 'tests/fixtures/live/program_change_25.jsonl'

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(cls.FIXTURE):
            raise unittest.SkipTest('program-change fixture missing')
        from utils.packet_recorder import load_capture
        cls.meta, pkts = load_capture(cls.FIXTURE)
        cls.stream = [b for p in pkts for b in p['bytes'][16:]]

    def _tag16(self, tag):
        out, i = [], 0
        while i < len(self.stream) - 3:
            if self.stream[i] == tag and self.stream[i + 1] == 0xcd:
                out.append((self.stream[i + 2] << 8) | self.stream[i + 3])
                i += 4
                continue
            i += 1
        return sorted(set(out))

    def _names(self):
        out, i = [], 0
        while i < len(self.stream) - 1:
            if self.stream[i] == 0x6d and 0xa1 < self.stream[i + 1] < 0xc0:
                length = self.stream[i + 1] - 0xa1
                raw = self.stream[i + 2:i + 2 + length]
                if len(raw) == length and all(32 <= c <= 126 for c in raw):
                    out.append(''.join(map(chr, raw)))
                    i += 2 + length
                    continue
            i += 1
        return out

    def test_device_reports_the_program_number_it_was_sent(self):
        self.assertIn(25, self._tag16(0x6c))

    def test_device_loaded_a_different_preset_than_storage_index_25(self):
        loaded = self._names()[0]
        self.assertEqual('A30 Fawn Brt', loaded)
        self.assertNotEqual('TwoPrinces', loaded)

    def test_enumeration_still_lists_twoprinces_at_storage_25(self):
        import json
        names = json.loads(
            open('tests/fixtures/lt_setlist2.jsonl').readline())['expect']['names_by_index']
        self.assertEqual('TwoPrinces', names['25'])
        self.assertEqual('A30 Fawn Brt', names['26'])

    def test_name_records_carry_no_display_index(self):
        """The name list has only the storage index and a constant zero."""
        from utils.packet_recorder import load_capture
        _meta, pkts = load_capture('tests/fixtures/lt_setlist2.jsonl')
        stream = []
        for p in pkts:
            b = p['bytes']
            if len(b) > 16 and b[4] == 0xef and b[11] == 0x04:
                stream.extend(b[16:])
        seen = set()
        i = 0
        while i < len(stream) - 3:
            if stream[i + 1] == 0xcd:
                seen.add(stream[i])
            i += 1
        self.assertEqual({0x81, 0x84, 0x66}, seen)
