from modes.standard import Standard
import logging
import threading
log = logging.getLogger(__name__)


class RequestSetlistNames(Standard):
	"""Ask the device for the names of its eight setlists.

	The query (id 0x3e9) was sitting commented out in request_preset_names.py,
	inherited from upstream, where it was presumably tried against an HX Stomp.
	On the Helix LT it returns one record per setlist:

		81 cd <index 16-bit>  <0xA1 + len>  <ASCII name>  00

	Note the string here has no 0x6d tag before it, unlike preset names -- the
	length marker follows the index directly.

	Worth having because setlists are named, not numbered, on the front panel:
	wire index 2 is "USER 1", not "setlist 3".
	"""

	SETLIST_COUNT = 8

	def __init__(self, helix_usb):
		Standard.__init__(self, helix_usb=helix_usb, name="request_setlist_names")
		self.stream = []
		self.names_by_index = {}
		self.transfer_complete = False
		self.idle_watchdog_timer = None

	def start(self):
		log.info('Starting mode')
		self.stream = []
		self.names_by_index = {}
		self.transfer_complete = False
		self._cancel_idle_watchdog()
		data = [0x19, 0x0, 0x0, 0x18, 0x1, 0x10, 0xef, 0x3, 0x0, "XX", 0x0, 0x4, 0x1a, 0x10, 0x0, 0x0,
				0x1, 0x0, 0x2, 0x0, 0x9, 0x0, 0x0, 0x0, 0x83, 0x66, 0xcd, 0x3, 0xe9, 0x64, 0x0, 0x65,
				0xc0, 0x0, 0x0, 0x0]
		self.helix_usb.endpoint_0x1_out(data, silent=True)
		self._arm_idle_watchdog()

	def shutdown(self):
		log.info('Shutting down mode')
		self._cancel_idle_watchdog()

	def _cancel_idle_watchdog(self):
		if self.idle_watchdog_timer is not None:
			self.idle_watchdog_timer.cancel()
			self.idle_watchdog_timer = None

	def _arm_idle_watchdog(self):
		self._cancel_idle_watchdog()
		self.idle_watchdog_timer = threading.Timer(2.0, self._finish)
		self.idle_watchdog_timer.start()

	@staticmethod
	def parse_setlist_names(stream):
		"""Decode `81 cd hi lo <0xA1+len> <ascii>` records from a payload."""
		names, i = {}, 0
		while i < len(stream) - 4:
			if stream[i] == 0x81 and stream[i + 1] == 0xcd:
				index = (stream[i + 2] << 8) | stream[i + 3]
				marker = stream[i + 4]
				if 0xa1 < marker < 0xc0:
					length = marker - 0xa1
					raw = stream[i + 5:i + 5 + length]
					if len(raw) == length and all(32 <= c <= 126 for c in raw):
						names.setdefault(index, ''.join(chr(c) for c in raw))
						i += 5 + length
						continue
				i += 4
				continue
			i += 1
		return names

	def _finish(self):
		if self.transfer_complete:
			return
		self.transfer_complete = True
		self._cancel_idle_watchdog()
		self.names_by_index = self.parse_setlist_names(self.stream)
		ordered = [self.names_by_index.get(i, '') for i in range(self.SETLIST_COUNT)]
		if not all(ordered):
			log.warning('Setlist names incomplete: %s', ordered)
		self.helix_usb.set_setlist_names(ordered)
		for i, name in enumerate(ordered):
			log.info('Setlist %d (shown as %d): %s', i, i + 1, name)
		self.helix_usb.switch_mode()

	def data_in(self, data_in):
		if self.transfer_complete:
			return False
		if self.helix_usb.check_keep_alive_response(data_in):
			return False
		if self.helix_usb.my_byte_cmp(
				left=data_in,
				right=["XX", 0x0, 0x0, 0x18, 0xef, 0x3, 0x1, 0x10, 0x0, "XX", 0x0, 0x4],
				length=12):
			self.stream.extend(data_in[16:])
			self._arm_idle_watchdog()
			return False
		return Standard.data_in(self, data_in)
