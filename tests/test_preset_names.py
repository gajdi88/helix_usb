"""Regression tests for setlist preset-name enumeration.

Every .jsonl in tests/fixtures/ is replayed through the real parsing stack and
checked against the `expect` block in its own meta record, so adding a capture
recorded off hardware needs no new test code -- only an `expect` block.

Run with:
    .venv/bin/python -m unittest discover -s tests -t .
"""
import os
import unittest

from tests.make_synthetic_capture import PAYLOAD_BYTES, build_capture
from tests.replay import fixture_paths, replay_preset_names

TRUNCATION_MARKERS = ('truncating extra entries', 'shorter than expected')


class PresetNameFixtureTest(unittest.TestCase):
	def test_fixtures_present(self):
		self.assertTrue(fixture_paths(), 'no capture fixtures in tests/fixtures/')

	def test_every_fixture_parses(self):
		for path in fixture_paths():
			with self.subTest(fixture=os.path.basename(path)):
				self._check_fixture(path)

	def _check_fixture(self, path):
		result = replay_preset_names(path)
		expect = result.expect
		names = result.names

		self.assertTrue(expect, 'fixture %s has no "expect" block in its meta record' % path)

		expected_count = expect.get('count', 128)
		self.assertEqual(expected_count, len(names),
						 'expected %d names, got %d' % (expected_count, len(names)))

		for index, expected_name in sorted(expect.get('names_by_index', {}).items(), key=lambda kv: int(kv[0])):
			index = int(index)
			self.assertEqual(expected_name, names[index],
							 'index %d: expected %r, got %r' % (index, expected_name, names[index]))

		if expect.get('no_placeholder', True):
			self.assertNotIn(result.helix.PRESET_PLACEHOLDER_NAME, names,
							 'placeholder entries present -- some names failed to decode')

		if expect.get('strict_indexing', True):
			self.assertEqual([], result.mode.decoded_preset_names_fallback,
							 'names decoded without an index; the 0x81 0xCD marker was missed')

		for message in result.warnings:
			for marker in TRUNCATION_MARKERS:
				self.assertNotIn(marker, message, 'unexpected truncation warning: %s' % message)


class SyntheticCaptureShapeTest(unittest.TestCase):
	"""Guard the properties the synthetic fixture is supposed to exercise.

	Without these, a change to the generator could quietly produce a fixture
	that no longer covers short names or split records, and the parser test
	above would still pass while testing much less.
	"""

	def setUp(self):
		self.meta, self.packets = build_capture()
		self.names = [self.meta['expect']['names_by_index'][str(i)] for i in range(128)]

	def test_covers_short_and_long_names(self):
		lengths = {len(name) for name in self.names}
		self.assertIn(2, lengths, 'no 2-character name; the short-record case is uncovered')
		self.assertGreaterEqual(max(lengths), 10)

	def test_entries_arrive_out_of_order(self):
		stream = []
		for packet in self.packets:
			stream.extend(packet[16:])

		indices = []
		i = 0
		while i < len(stream) - 3:
			if stream[i] == 0x81 and stream[i + 1] == 0xcd:
				indices.append((stream[i + 2] << 8) | stream[i + 3])
				i += 4
				continue
			i += 1

		self.assertEqual(128, len(indices))
		self.assertNotEqual(sorted(indices), indices, 'entries are in order; out-of-order arrival is uncovered')

	def test_names_straddle_packet_boundaries(self):
		# A record that starts in one packet and ends in the next is the case
		# that forces payload concatenation before parsing.
		boundaries = set()
		offset = 0
		for packet in self.packets[:-1]:
			offset += len(packet) - 16
			boundaries.add(offset)

		stream_offset = 0
		split_count = 0
		for slot_name in self._entries_in_stream_order():
			record_len = 9 + len(slot_name)
			start, end = stream_offset, stream_offset + record_len
			if any(start < b < end for b in boundaries):
				split_count += 1
			stream_offset = end

		self.assertGreater(split_count, 0, 'no record straddles a packet boundary')

	def _entries_in_stream_order(self):
		import random
		from tests.make_synthetic_capture import PRESET_COUNT, SHUFFLE_SEED

		slots = list(range(PRESET_COUNT))
		random.Random(SHUFFLE_SEED).shuffle(slots)
		return [self.names[slot] for slot in slots]

	def test_payload_size_forces_multiple_packets(self):
		# Many more packets than presets: the stream must be reassembled, not
		# read one-record-per-packet.
		self.assertGreater(len(self.packets), 50)
		for packet in self.packets:
			self.assertLessEqual(len(packet) - 16, PAYLOAD_BYTES)
			self.assertGreaterEqual(len(packet), 17, 'matcher needs at least one payload byte')


if __name__ == '__main__':
	unittest.main()
