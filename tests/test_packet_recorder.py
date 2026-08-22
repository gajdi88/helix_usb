"""Record -> replay round trip.

Proves the recorder writes a file the replayer can actually consume, and that
a packet survives the trip byte-for-byte. Needs no Helix attached: the
synthetic packets are pushed straight through HelixUsb.data_in(), which is the
same call the 0x81 reader thread makes against hardware.
"""
import os
import shutil
import tempfile
import unittest

from modes.standard import Standard
from tests.make_synthetic_capture import build_capture
from tests.replay import ReplayHelixUsb, replay_preset_names
from utils.packet_recorder import FIXTURE_KIND, load_capture


class PacketRecorderTest(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp(prefix='helix-capture-')
		self.capture_path = os.path.join(self.tmpdir, 'roundtrip.jsonl')
		self.meta, self.packets = build_capture()

	def tearDown(self):
		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def _record(self, setlist='2'):
		previous = os.environ.get('HELIX_SETLIST')
		os.environ['HELIX_SETLIST'] = setlist
		try:
			helix = ReplayHelixUsb()
			helix.set_packet_recorder(self.capture_path)
			# Standard mode, not the preset-names mode: recording must not
			# depend on the active mode understanding the packet.
			helix.active_mode = Standard(helix, name='standard')
			for packet in self.packets:
				helix.data_in('0x81', packet)
			helix.packet_recorder.close()
		finally:
			if previous is None:
				os.environ.pop('HELIX_SETLIST', None)
			else:
				os.environ['HELIX_SETLIST'] = previous
		return helix

	def test_capture_is_byte_faithful(self):
		self._record()
		meta, recorded = load_capture(self.capture_path)

		self.assertEqual(FIXTURE_KIND, meta.get('kind'))
		self.assertEqual('2', str(meta.get('setlist')))
		self.assertEqual(len(self.packets), len(recorded))

		for original, stored in zip(self.packets, recorded):
			self.assertEqual(list(original), stored['bytes'])

		# The 16-byte transport header must survive; a capture of stripped
		# payloads could not exercise the packet matcher on replay.
		self.assertEqual(self.packets[0][:16], recorded[0]['bytes'][:16])

	def test_recorded_capture_replays_to_the_same_names(self):
		self._record()

		expected = self.meta['expect']['names_by_index']
		result = replay_preset_names(self.capture_path, setlist=2)

		self.assertEqual(128, len(result.names))
		self.assertEqual('TwoPrinces', result.names[25])
		self.assertEqual('Voice', result.names[127])
		for index in range(128):
			self.assertEqual(expected[str(index)], result.names[index])

	def test_recording_is_off_by_default(self):
		previous = os.environ.pop('HELIX_RECORD', None)
		try:
			helix = ReplayHelixUsb()
			helix.active_mode = Standard(helix, name='standard')
			self.assertIsNone(helix.packet_recorder)
			helix.data_in('0x81', self.packets[0])
		finally:
			if previous is not None:
				os.environ['HELIX_RECORD'] = previous

	def test_capture_survives_an_unflushed_kill(self):
		# `timeout 10 python ...` kills with SIGTERM, which runs no atexit
		# handler, so every line must already be on disk.
		helix = ReplayHelixUsb()
		helix.set_packet_recorder(self.capture_path)
		helix.active_mode = Standard(helix, name='standard')
		for packet in self.packets[:5]:
			helix.data_in('0x81', packet)

		# Deliberately read back before close().
		_meta, recorded = load_capture(self.capture_path)
		self.assertEqual(5, len(recorded))
		helix.packet_recorder.close()


if __name__ == '__main__':
	unittest.main()
