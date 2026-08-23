"""Replay a recorded .jsonl capture through the real parsing stack.

The point of this harness is that almost nothing is faked. `ReplayHelixUsb`
is the real `HelixUsb` with only the two methods that touch USB replaced, so
the packet matcher (`my_byte_cmp`), the keep-alive detector, the mode dispatch
in `data_in()` and the truncation logic in `set_preset_names()` are all the
production code paths. A test that passes here is a statement about the
shipping parser, not about a mock of it.
"""
import contextlib
import io
import logging
import os
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helix_usb import HelixUsb
from modes.request_preset import RequestPreset
from modes.request_preset_names import RequestPresetNames
from modes.standard import Standard
from utils.formatter import format_1
from utils.packet_recorder import load_capture

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
PRESET_FIXTURE_DIR = os.path.join(FIXTURE_DIR, 'presets')
LIVE_FIXTURE_DIR = os.path.join(FIXTURE_DIR, 'live')


class ReplayHelixUsb(HelixUsb):
	def __init__(self):
		# HelixUsb.__init__ honours HELIX_RECORD; a test run must never start
		# writing a capture of its own.
		previous = os.environ.pop('HELIX_RECORD', None)
		try:
			HelixUsb.__init__(self)
		finally:
			if previous is not None:
				os.environ['HELIX_RECORD'] = previous

		self.sent_packets = []
		self.mode_switches = []

	def endpoint_0x1_out(self, data, silent=False):
		self.sent_packets.append(list(data))

	def switch_mode(self, mode_name="Standard"):
		self.mode_switches.append(mode_name)


class _WarningCollector(logging.Handler):
	def __init__(self):
		logging.Handler.__init__(self, level=logging.WARNING)
		self.records = []

	def emit(self, record):
		self.records.append(record)

	@property
	def messages(self):
		return [r.getMessage() for r in self.records]


class ReplayResult(object):
	def __init__(self, meta, packets, helix, mode, warnings):
		self.meta = meta
		self.packets = packets
		self.helix = helix
		self.mode = mode
		self.warnings = warnings

	@property
	def names(self):
		return self.helix.preset_names

	@property
	def expect(self):
		return self.meta.get('expect', {})


def replay_preset_names(capture_path, setlist=None):
	"""Feed a capture through RequestPresetNames and return what came out."""
	meta, packets = load_capture(capture_path)
	if setlist is None:
		setlist = int(meta.get('setlist', 0))

	# Route logging to the collector alone for the duration of the replay: a
	# real capture carries the whole session, so the preset-names mode warns
	# on every packet that is not part of the name stream. The warnings are
	# still asserted on via result.warnings, just not printed.
	collector = _WarningCollector()
	root = logging.getLogger()
	saved_handlers, saved_level = root.handlers[:], root.level
	root.handlers = [collector]
	root.setLevel(logging.WARNING)

	helix = ReplayHelixUsb()
	mode = RequestPresetNames(helix)
	# Pin the setlist so a replay never depends on the environment or on what
	# the device happened to be showing. _choose_setlist() would otherwise
	# re-derive it in start().
	mode.setlist = setlist
	mode._choose_setlist = lambda: setlist
	helix.active_mode = mode

	try:
		mode.start()
		for packet in packets:
			if packet.get('ep', '0x81') != '0x81':
				continue
			helix.data_in('0x81', packet['bytes'])

		if not mode.transfer_complete:
			# Stand in for the 2.0s idle watchdog instead of sleeping for it.
			mode._on_idle_watchdog_timeout()
	finally:
		mode._cancel_idle_watchdog()
		root.handlers, root.level = saved_handlers, saved_level

	return ReplayResult(meta, packets, helix, mode, collector.messages)


class _NoopTimer(object):
	"""Stand-in for threading.Timer during a replay.

	RequestPreset arms a 0.02s timer after every packet to decide the transfer
	has ended. A whole capture replays in microseconds, so those timers would
	fire on background threads after the feed loop and parse concurrently.
	Replay drives the parse once, explicitly, instead.
	"""

	def __init__(self, *args, **kwargs):
		pass

	def start(self):
		pass

	def cancel(self):
		pass


class PresetDataResult(object):
	def __init__(self, meta, packets, helix, mode, warnings, parse_error):
		self.meta = meta
		self.packets = packets
		self.helix = helix
		self.mode = mode
		self.warnings = warnings
		self.parse_error = parse_error

	@property
	def preset_data(self):
		"""Concatenated payload, transport headers stripped."""
		return self.mode.preset_data

	@property
	def hex_str(self):
		"""The payload as the flat hex string the parser consumes."""
		return format_1(', '.join(hex(b) for b in self.mode.preset_data))

	@property
	def hx_preset(self):
		return self.mode.hx_preset

	@property
	def observed(self):
		return self.meta.get('observed', {})


def replay_preset_data(capture_path):
	"""Feed a preset-data capture through RequestPreset.

	Returns the accumulated payload whether or not parsing succeeded --
	`extract_footswitch_sections` currently raises on every LT preset, and the
	captured bytes are exactly what is needed to fix that, so a parse failure
	must not cost us the data.
	"""
	meta, packets = load_capture(capture_path)

	collector = _WarningCollector()
	root = logging.getLogger()
	saved_handlers, saved_level = root.handlers[:], root.level
	root.handlers = [collector]
	root.setLevel(logging.WARNING)

	helix = ReplayHelixUsb()
	mode = RequestPreset(helix)
	helix.active_mode = mode
	parse_error = None

	try:
		# HxPreset.to_string() prints the whole preset to stdout; a replay of
		# every fixture would bury the test output.
		with mock.patch.object(threading, 'Timer', _NoopTimer), \
				contextlib.redirect_stdout(io.StringIO()):
			mode.start()
			for packet in packets:
				if packet.get('ep', '0x81') != '0x81':
					continue
				helix.data_in('0x81', packet['bytes'])
			try:
				mode.parse_preset_data()
			except Exception as e:      # noqa: BLE001 - recording it is the point
				parse_error = e
	finally:
		root.handlers, root.level = saved_handlers, saved_level

	return PresetDataResult(meta, packets, helix, mode, collector.messages, parse_error)


def fixture_paths():
	if not os.path.isdir(FIXTURE_DIR):
		return []
	return sorted(
		os.path.join(FIXTURE_DIR, name)
		for name in os.listdir(FIXTURE_DIR)
		if name.endswith('.jsonl')
	)


class StandardResult(object):
    def __init__(self, meta, packets, helix, snapshots, warnings):
        self.meta = meta
        self.packets = packets
        self.helix = helix
        self.snapshots = snapshots        # every set_snapshot value, in order
        self.warnings = warnings

    @property
    def expect(self):
        return self.meta.get('expect', {})


def replay_standard(capture_path):
	"""Feed a live session capture through Standard mode.

	Standard is where the device's unsolicited UI events land -- snapshot
	changes, preset switches, view changes -- so this is the harness for
	captures recorded while someone operates the front panel.
	"""
	meta, packets = load_capture(capture_path)

	collector = _WarningCollector()
	root = logging.getLogger()
	saved_handlers, saved_level = root.handlers[:], root.level
	root.handlers = [collector]
	root.setLevel(logging.WARNING)

	helix = ReplayHelixUsb()
	snapshots = []
	helix.register_snapshot_change_cb_fct(snapshots.append)
	helix.active_mode = Standard(helix, name='standard')

	try:
		with contextlib.redirect_stdout(io.StringIO()):
			for packet in packets:
				if packet.get('ep', '0x81') != '0x81':
					continue
				try:
					helix.data_in('0x81', packet['bytes'])
				except Exception:      # noqa: BLE001
					# Standard mode is not the mode these packets were sent
					# for; a handler tripping must not stop the replay.
					pass
	finally:
		root.handlers, root.level = saved_handlers, saved_level

	return StandardResult(meta, packets, helix, snapshots, collector.messages)


def live_fixture_paths():
	if not os.path.isdir(LIVE_FIXTURE_DIR):
		return []
	return sorted(
		os.path.join(LIVE_FIXTURE_DIR, name)
		for name in os.listdir(LIVE_FIXTURE_DIR)
		if name.endswith('.jsonl')
	)


def preset_fixture_paths():
	if not os.path.isdir(PRESET_FIXTURE_DIR):
		return []
	return sorted(
		os.path.join(PRESET_FIXTURE_DIR, name)
		for name in os.listdir(PRESET_FIXTURE_DIR)
		if name.endswith('.jsonl')
	)
