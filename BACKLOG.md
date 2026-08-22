# Backlog

Ideas and known gaps, roughly in priority order. Working notes and confirmed
protocol facts live in `CLAUDE.md`; this file is for what is *not* done yet.

## Next up

### Block/slot and footswitch parsing — the big one
`utils/preset_parser.py::extract_footswitch_sections` does `data.index('0895')`
and raises `ValueError` on LT presets (`0895` is an HX Stomp marker). This
kills `modes/request_preset` in a worker thread on **every** startup — three
tracebacks per run. Preset names are unaffected.

The LT is structurally bigger than the Stomp everywhere the parser assumes
size: two DSP paths with ~16 block positions plus splits/merges and a 1→2
routing block (Stomp: one path of 8), 8 snapshots (3), 8+ footswitches (3),
4 send/returns (1). Slot geometry lives in `next_gen_slot_parser.py`.

### Capture matrix for preset data
All eight setlists are captured (`tests/fixtures/lt_setlist*.jsonl`). Still
missing, and needed before the parsing work above: presets with 1 / 8 / 16
blocks, a split path, all footswitches assigned, an empty preset.

**These need the active preset changed on the device — a write to its state.
Ask before recording them.**

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
