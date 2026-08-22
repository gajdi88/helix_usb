"""Raw bulk-IN packet recorder and capture loader.

Records every inbound packet verbatim to a .jsonl file so that parsers can be
exercised with no Helix attached. Packets are stored **exactly as they came
off the wire, 16-byte transport header included** -- a fixture that stores
pre-stripped payloads cannot validate a change to the header handling, which
is precisely the layer most likely to be wrong on a device upstream never saw.

File layout: one JSON object per line. The first line is a meta record, every
line after it is a packet record.

	{"kind": "helix-usb-packet-capture", "version": 1, "setlist": 2}
	{"seq": 0, "t": 0.0041, "ep": "0x81", "len": 40, "data": "08010018ef03..."}

`t` is seconds since the recorder was opened, kept only as a debugging aid --
replay ignores it.
"""
import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

FIXTURE_KIND = 'helix-usb-packet-capture'
FIXTURE_VERSION = 1


class PacketRecorder:
	def __init__(self, path, meta=None):
		self.path = path
		self.seq = 0
		self.t0 = time.time()
		self.lock = threading.Lock()
		self.closed = False

		directory = os.path.dirname(os.path.abspath(path))
		if directory and not os.path.isdir(directory):
			os.makedirs(directory, exist_ok=True)

		self.fh = open(path, 'w', encoding='utf-8')

		header = {'kind': FIXTURE_KIND, 'version': FIXTURE_VERSION}
		if meta:
			header.update(meta)
		self._write(header)
		log.info('Recording raw packets to %s', path)

	def _write(self, record):
		# Flush every line: `timeout N python ...` kills the process with
		# SIGTERM, which runs no atexit handler, so anything still sitting in
		# the buffer is lost.
		self.fh.write(json.dumps(record) + '\n')
		self.fh.flush()

	def record(self, endpoint_id, data):
		if self.closed:
			return
		with self.lock:
			if self.closed:
				return
			payload = bytes(bytearray(data))
			self._write({
				'seq': self.seq,
				't': round(time.time() - self.t0, 6),
				'ep': endpoint_id,
				'len': len(payload),
				'data': payload.hex(),
			})
			self.seq += 1

	def close(self):
		with self.lock:
			if self.closed:
				return
			self.closed = True
			try:
				self.fh.close()
			except OSError as e:
				log.warning('Failed to close packet capture %s: %s', self.path, str(e))
		log.info('Wrote %d packets to %s', self.seq, self.path)


def load_capture(path):
	"""Read a .jsonl capture.

	Returns (meta, packets) where each packet is a dict with an added
	`bytes` key holding the packet as a list of ints, ready to hand to a
	mode's data_in().
	"""
	meta = {}
	packets = []

	with open(path, 'r', encoding='utf-8') as fh:
		for line_no, line in enumerate(fh, start=1):
			line = line.strip()
			if not line:
				continue
			try:
				record = json.loads(line)
			except ValueError as e:
				raise ValueError('%s:%d is not valid JSON: %s' % (path, line_no, str(e)))

			if 'data' not in record:
				meta.update(record)
				continue

			record['bytes'] = list(bytes.fromhex(record['data']))
			packets.append(record)

	return meta, packets
