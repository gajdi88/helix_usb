# Backlog

Ideas and known gaps, roughly in priority order. Working notes and confirmed
protocol facts live in `CLAUDE.md`; this file is for what is *not* done yet.

## In progress — picking up here

Preset-data capture, round 2. The device operator needs to identify presets by
characteristic, because block count cannot be read out of a capture without
the parser. **Ask for these, on the device's setlist 3 (wire index 2)**, where
the existing 14 captures came from:

- fewest blocks (1 if one exists)
- ~8 blocks (the HX Stomp's maximum — useful comparison point)
- the most complex preset available (upper bound; most valuable single capture)
- one using the parallel/split path
- one with the most footswitches assigned

One preset may cover several rows. Rough counts are fine; the count is the
point, since it becomes the fixture's ground truth.

Two capture routes: have the operator navigate to each preset and capture
whatever is loaded (like `sl3_preset127_empty.jsonl` — avoids slot-number
conversion), or take all five slot numbers and select them over MIDI PC in one
session (faster, but see the numbering caveat below).

**Open question — bank/letter to slot conversion.** With the device showing
"32B" the wire reported slot 127. The assumed mapping
`(bank - 1) * 4 + [A=0, B=1, C=2, D=3]` gives 125, not 127. Settle this before
converting any operator-supplied bank+letter numbers, or capture the loaded
preset instead and sidestep it.

## Next up

### Preset parsing — what is left after the 2026-08-23 fix
Section extraction works and all 15 captures parse. Remaining, in order:

- **`FootSwitchInfo` populates nothing.** The sections and their labels are
  extracted correctly; the field parser inside produces empty objects.
- **Snapshot detection is dead** — Stomp marker `860600070208` is absent from
  LT data, and the code only handles snapshots 1–3 against the LT's 8.
- **Missing module ids** in `modules.py` (`cd02bb`, `cd02cd`, …).
- **`to_string()` bank arithmetic** assumes 3 presets per bank; the LT has 4.
- **Splits/merges and the 1→2 routing block** are still entirely unmodelled.

### Original notes on the big job
`utils/preset_parser.py::extract_footswitch_sections` does `data.index('0895')`
and raises `ValueError` on LT presets (`0895` is an HX Stomp marker). This
kills `modes/request_preset` in a worker thread on **every** startup — three
tracebacks per run. Preset names are unaffected.

The LT is structurally bigger than the Stomp everywhere the parser assumes
size: two DSP paths with ~16 block positions plus splits/merges and a 1→2
routing block (Stomp: one path of 8), 8 snapshots (3), 8+ footswitches (3),
4 send/returns (1). Slot geometry lives in `next_gen_slot_parser.py`.

### Capture matrix for preset data
All eight setlists are captured (`tests/fixtures/lt_setlist*.jsonl`), plus 14
preset-data captures from setlist 2 (`tests/fixtures/presets/`), recorded
2026-08-22 by MIDI PC within one session. All 14 verified distinct.

Still missing, and **not obtainable by selecting presets alone**:

- **Known block counts (1 / 8 / 16).** Block count cannot be determined from a
  capture without the parser, so the recorded spread is uncharacterised. The
  quickest way through: name presets whose block counts you already know (from
  HX Edit), and capture those specifically.
- **An empty preset.** Setlist 2 is fully populated. Setlists 1 and 3–6 have
  "New Preset" at slot 127, but MIDI PC only moves within the device's *active*
  setlist, so the device has to be switched to one of those first.
- **A split path** and **all footswitches assigned** — same problem: no way to
  confirm from the raw capture which presets have them.

### Leads from the preset-data captures
Observations from an ASCII scan of the 14 captures, not from a parser:

- Effect **block names appear as plain ASCII** (`Courtesan Flange`,
  `Scream 808`, `Tycoctavia Fuzz`, `10 Band Graphic`, `6 Switch Looper`).
  Best entry point for the block parser.
- **Snapshot labels** appear the same way (`SNAPSHOT 1` … `SNAPSHOT 8`).
- **IR/cab references** appear as `!` + 32 hex chars; presets carrying them are
  ~9.6KB against ~7.4KB for those without.
- **The preset name is *not* in the preset-data stream** — not as a `0x6D`
  string and not as raw ASCII. Don't go looking for it there.
- Matching `modules.py` 3-byte `cdXXXX` ids against the raw stream **does not
  work** — ~50 false hits per capture, near-identical across every preset.
  Chance collisions dominate at that pattern length; the ids must need
  surrounding framing to locate.

### Extend the replay harness to RequestPreset
`tests/replay.py` hardcodes `RequestPresetNames`. Preset-data fixtures need an
equivalent entry point. The recorder, `ReplayHelixUsb` and the
fixture-discovery pattern all carry over unchanged.

## UI

### The signal chain is still HX Stomp shaped
`helix_qt_ui.py` has `HX_STOMP_BLOCK_COUNT = 10`,
`HX_STOMP_INPUT_SLOT_INDEX = 0`, `HX_STOMP_OUTPUT_SLOT_INDEX = 9` and
`HX_STOMP_EFFECT_SLOT_INDICES = [1..8]`, with `_slot_index_map` built from
them. The LT needs ~16 positions across two paths. Blocked on the parsing work
above — there is nothing to display until preset data parses.

### No setlist picker
The setlist is chosen by the `HELIX_SETLIST` env var at startup and the UI
shows one setlist's 128 presets. The device holds 8 × 128 = 1024. A picker
would need `RequestPresetNames` re-run on change.

### Audit for other hardcoded HX Stomp assumptions
The 2026-08-22 bug was the UI keeping its own `PRESET_LIST_COUNT = 125` while
`HelixUsb` had moved to 128 — the device sent 128 names and the list silently
dropped three. That was a *duplicated constant*, so worth sweeping for others
rather than waiting to trip over them.

## Robustness

### `data_in` can kill the reader thread
`HelixUsb.data_in()` calls `self.active_mode.data_in(data)` guarded only
against `IndexError`. Between `begin()` starting the 0x81 reader and
`switch_mode("Connect")` on the next line (`helix_usb.py:743-745`),
`active_mode` is `None`; the resulting `AttributeError` is not caught by
`endpoint_listener`, which would silently kill the reader thread. Narrow
window, never observed in the wild, found via tests.

### Unexplained startup noise
Pre-existing, harmless as far as anything shows, never investigated: two
`Errno 32` pipe errors reading strings 9/10, and one `No x1x10/x2x10
response!` pair at teardown. `Errno 16` on interface 3.1 is understood (audio
device in use).

## Housekeeping

### `modules.py` invalid escape sequences
`SyntaxWarning: "\s" is an invalid escape sequence` at `modules.py:69` and
`:233`. Pre-existing on upstream `main`; becomes a hard error in a future
Python. One-line fix (raw strings).

### Offer two commits upstream
`d63fddf` (SIGTERM/clean teardown) and `871a2e3` (packet recorder) are
device-agnostic and apply to `kempline/helix_usb`. Everything else assumes
128-preset LT behaviour and fails on upstream's 125-preset tree. Must be a
**separate branch cut from `upstream/main`**, dropping the fork-only CLAUDE.md
hunk and resolving a one-line `.gitignore` conflict. Ask before preparing it.

### Ask upstream about the `ideas/` captures
`ideas/` contains files named "18 Slots" and "20 Slots". Worth asking which
device they came from before duplicating that work.
