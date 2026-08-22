# helix_usb — Helix LT working notes

Fork of `kempline/helix_usb`. Upstream reverse-engineered the USB protocol
between HX Edit and an **HX Stomp**. This fork adds **Helix LT** support.

Upstream's own caveat still applies: roughly 30–40% of the message structure
is understood. Some exchanges are byte sequences replayed from HX Edit
captures without knowing what they carry. Treat any fixed offset as suspect.

## Hardware

Helix LT, `lsusb` ID **`0e41:424a`** (upstream knew only `0e41:4246` and
`0e41:5055`).

USB descriptor layout — confirmed, do not guess at these:

| Interface | Class | Endpoints | Purpose |
|---|---|---|---|
| 0 | Vendor Specific, iInterface "Msg Pipe" | `0x01` Bulk OUT, `0x81` Bulk IN | **the protocol pipe** |
| 1–3 | Audio | iso `0x03` OUT, `0x83` IN | audio streaming |
| 4 | Audio/MIDI, "HELIX MIDI" | `0x04` Bulk OUT, `0x84` Bulk IN | MIDI (Stomp uses `0x02`/`0x82`) |
| 5 | HID | `0x85` Interrupt IN | unknown |

Interface 0 is vendor-specific, so no kernel driver claims it and pyusb can
take it without disturbing ALSA. Interface 4 **is** claimed by `snd-usbmidi`;
detaching it removes the Helix MIDI ports from the system until release.
Claiming interface 3.1 fails with `Errno 16` when the audio device is in use —
harmless, logged as an error.

Linux access needs a udev rule:
`SUBSYSTEM=="usb", ATTRS{idVendor}=="0e41", TAG+="uaccess"`

## Wire encoding

Values are tag-prefixed. Confirmed tags:

| Bytes | Meaning |
|---|---|
| `0x81 0xCD hi lo` | preset index, 16-bit big-endian, **absolute across the device** |
| `0x6D <0xA1+len>` | string: length is `marker - 0xA1`, then that many ASCII bytes |
| `0x6B 0xCD hi lo` | setlist index (0–7) |
| `0x6C 0xCD hi lo` | preset number |
| `0x84 0xCD 0x00` | precedes the name tag in list entries; meaning unknown |

`0xCD` appears to introduce a 16-bit integer. `0xA1 + n` introduces an n-byte
string. This has been verified across ~256 real entries.

Key facts:

- A setlist holds **128** presets (32 banks × 4). Eight setlists, 1024 total.
- Preset indices are absolute: `setlist * 128 + slot`. Setlist 2 slot 25
  arrives as `0x81 0xCD 0x01 0x19` (281).
- **Entries arrive out of order.** Always key on the index, never on arrival
  position.
- Records are **variable length**. Upstream's fixed 25-byte record window
  desynchronises on short names (a 2-char name makes an 18-byte record).
- Names split across USB packets. Strip the 16-byte transport header from each
  packet and concatenate before parsing.

## What this fork changed

`modes/request_preset_names.py` (plural — enumerates a setlist)
- `expected_preset_name_count` 125 → 128
- setlist selectable via `HELIX_SETLIST` env var (0–7, default 0); it is
  written into the request array at the `0x6B` tag
- index read as 16-bit BE from the `0x81 0xCD` marker, rebased by
  `setlist * 128`, replacing the Stomp's `(bank * 25) + offset`
- parser is tag-driven over the whole stream, replacing the fixed record window
- idle watchdog 0.75s → 2.0s

`modes/request_preset_name.py` (singular — reads the current preset)
- response matcher: two bytes of the 16-byte template were device-specific and
  are now wildcards — offset 9 (`0x86` on Stomp, `0x87` on LT) and offset 13
  (hardcoded setlist 0; LT on setlist 2 sends `0x02`)
- name read via the `0x6D` tag instead of `slot_number_idx = 27`

`helix_usb.py`
- `PRESET_LIST_COUNT` 125 → 128 (it truncates before the UI sees the list)
- `MIDI_PROGRAM_MAX` 125 → 127 (MIDI PC is 0–127)

**Why the singular mode mattered:** it failed on LT, called `switch_mode()`
every 0.5s, and tore down `request_preset_names` before it could collect. The
symptom was a UI that hung and a log full of "Unexpected message in mode".
Fixing the matcher fixed the plural mode by side effect.

## Known broken

Open work and ideas not yet started are tracked in `BACKLOG.md`.

`utils/preset_parser.py::extract_footswitch_sections` does
`data.index('0895')` and raises `ValueError` on LT presets — `0895` is an HX
Stomp marker. This kills `modes/request_preset` in a worker thread on every
run. It does not affect preset names. Confirmed still failing on the
2026-08-22 hardware run: three tracebacks per startup.

This is the **big remaining job**: block/slot and footswitch parsing. The LT
has two DSP paths with ~16 block positions plus splits/merges and a 1→2
routing block, against the Stomp's single path of 8. Also 8 snapshots vs 3,
8+ footswitches vs 3, 4 send/returns vs 1. `next_gen_slot_parser.py` is where
the slot geometry lives. Upstream's `ideas/` directory contains raw captures
including files named "18 Slots" and "20 Slots" — ask upstream what device
those came from before duplicating that work.

## Conventions

- **Indentation is inconsistent across the repo.** `helix_usb.py` and
  `modes/request_preset_names.py` use **tabs**. `modes/request_preset_name.py`
  uses **4 spaces**. Match the file you are editing; do not normalise.
- `my_byte_cmp(left, right, length)` treats the string `"XX"` as a wildcard.
- Modes subclass `modes.standard.Standard`; `data_in()` returns `False` to
  suppress console printing of a message it handled, `True` otherwise.

## Working practice

- **Read-only by default.** Enumerating names does not write to the device.
  Do not call rename / footswitch-label / write functions without asking —
  there is no Linux backup path, only HX Edit in a Windows VM.
- Only one process can hold the device. Close the DAW before testing.
- **`helix_qt_ui.py` is a Qt GUI with no exit path — never run it directly, it
  will hang the session.** Always bound it and capture the output:

  ```
  timeout 10 .venv/bin/python helix_qt_ui.py 2>&1 | tee /tmp/helix.log
  ```

  then read `/tmp/helix.log`. Note `.venv/bin/python`, not bare `python`.
- Prefer fixtures to hardware. `--record` and the fixture tests exist now —
  see **Non-interactive testing** below. Iterating on a parser needs no LT
  attached.
- Lock in current behaviour with a fixture test before refactoring. 128 names
  from setlist 2 currently parse correctly — that is the regression baseline.

## Non-interactive testing

Recording (needs the LT attached, DAW closed). `HELIX_RECORD` writes every
inbound packet verbatim — 16-byte transport header included — to a `.jsonl`:

```
HELIX_SETLIST=2 HELIX_RECORD=tests/fixtures/lt_setlist2.jsonl \
  timeout 10 .venv/bin/python helix_qt_ui.py 2>&1 | tee /tmp/helix.log
```

`helix_usb.py` also takes `-r <file.jsonl>`. Lines are flushed as they are
written, so a `timeout` SIGTERM does not lose the capture.

Replaying (needs nothing attached):

```
.venv/bin/python -m unittest discover -s tests -t .
```

`tests/replay.py` feeds a capture through the **real** stack — `ReplayHelixUsb`
is `HelixUsb` with only `endpoint_0x1_out` and `switch_mode` replaced, so the
packet matcher, keep-alive detector and `set_preset_names` truncation are all
production code. Every `.jsonl` in `tests/fixtures/` is replayed and checked
against the `expect` block in its own meta record, so **adding a hardware
capture needs no new test code** — only an `expect` block:

```json
{"setlist": 2, "expect": {"count": 128, "no_placeholder": true,
 "names_by_index": {"25": "TwoPrinces", "127": "Voice"}}}
```

Capture matrix still worth recording: each setlist; presets with 1 / 8 / 16
blocks; a split path; all footswitches assigned; an empty preset.

## Process lifecycle and SIGTERM

**SIGTERM is handled (fixed 2026-08-22).** `timeout N python ...` used to kill
the process outright: `HelixUsb.shutdown()` never ran, USB interfaces were
never released, and the *next* run then failed — 8 packets, never reaching
`request_preset_names`. In a sequential sweep this alternates with run order,
so it looks exactly like "even setlists work, odd ones don't". It is not
setlist-dependent. Three things were wrong and all three are fixed:

- Neither entry point trapped SIGTERM. `helix_qt_ui.py` now installs handlers
  for SIGINT/SIGTERM that call `app.quit()`, plus a 200ms no-op `QTimer` —
  Python signal handlers only run between bytecodes, and nothing executes
  while `app.exec()` is blocked in C++. `main()` calls `bridge.stop()` in a
  `finally`, because `app.quit()` delivers no `closeEvent`. `helix_usb.py`
  registers SIGTERM alongside its existing SIGINT handler.
- `shutdown()` joined the keep-alive threads with a 1.0s timeout against a
  1.04s keep-alive cycle, so the join always timed out and
  `dispose_resources()` ran under a live thread whose next write blocked on a
  disposed endpoint. Join is now 2.5s and warns if a thread outlives it.
- The keep-alive, reader and USB-monitor threads were non-daemon, so one stuck
  in a USB write held the process open. All are now daemon.

Teardown costs ~0.8s and logs `Shutdown complete; USB interfaces released`.
Note the Qt bridge's own "Shutdown complete" status is emitted *after* the
event loop stops, so its slot never runs — don't use it as a marker.

Back-to-back runs still want a small gap: **3s is verified good** (it was the
gap that used to fail every second run), 1s is still too short. 8s if you want
margin.

## Verified baseline

Nine fixtures, all replayed by the same test:

- `tests/fixtures/lt_setlist0.jsonl` … `lt_setlist7.jsonl` — **recorded from
  the LT** on 2026-08-22, one per setlist, via normal `helix_qt_ui.py`
  startups. ~150 packets each of full session traffic, not just the name
  stream. Each `expect` block holds the 128 names the device printed during
  that live run; replaying each capture reproduces them exactly, 0 mismatches.
  All eight setlists are full — slot 0 is `US Double Nrm`, `Bentique`,
  `Run Like`, `Bluesy`, `CleanBrup`, `Litigator Cl2`, `Comf Numb Lead2`,
  `Quick Start` respectively.
- `tests/fixtures/synthetic_setlist2.jsonl` — **generated from the wire model
  in this file, not from hardware** (`tests/make_synthetic_capture.py`). Keeps
  the short-name, out-of-order and split-record cases covered deterministically.

All nine were verified to go red individually on a fixed 25-byte record window,
on `expected_preset_name_count = 125`, and on ignoring the `0x81 0xCD` index
marker.

Live startup on hardware (`HELIX_SETLIST=2`, run as above) reaches
`request_preset_names` through connect → reconfigure_x1 → request_preset_name
→ request_preset, logs 128 names with "Run Like" at 0, "TwoPrinces" at 25 and
"Voice" at 127, and no truncation warning.

Expected noise in that log, all pre-existing and none of it affecting names:
`Errno 16` claiming interface 3.1 (audio in use), two `Errno 32` pipe errors
reading strings 9/10, one `No x1x10/x2x10 response!` pair at teardown, and
three `ValueError: substring not found` tracebacks from the known-broken
footswitch parser above.
