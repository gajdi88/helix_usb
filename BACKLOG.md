# Backlog

Ideas and known gaps, roughly in priority order. Working notes and confirmed
protocol facts live in `CLAUDE.md`; this file is for what is *not* done yet.

## In progress — picking up here

### Display order is not readable — the preset numbering problem

**The problem.** Two different preset numberings exist and we can only read
one of them.

- The name enumeration returns names against a **storage index**
  (`0x81 0xCD`, absolute across the device).
- MIDI Program Change and the `0x6C` tag use **display position** — the slot
  the device actually shows, e.g. `07B`.

They are identical until a preset is moved, and then they diverge. On this
device `TwoPrinces` was moved to the end of setlist 3, so display position is
storage index − 1 for everything from storage 26 to 125.

Proved in `tests/fixtures/live/program_change_25.jsonl`: Program Change 25
loads `A30 Fawn Brt` and the device reports preset 25, while the enumeration
lists `TwoPrinces` at storage 25.

**Why it matters.** Every preset-data capture was selected by Program Change
(display) and then labelled from the enumeration (storage), so
`preset_name` on `tests/fixtures/presets/sl2_preset*.jsonl` is wrong for
anything after the move — they are flagged `preset_name_reliable: false`. It
also means any preset reference given to the operator is wrong unless it came
from a Program Change number.

**What upstream did, and why it does not help directly.** The HX Stomp
version of `_extract_record_preset_index()` ignored `0x81` entirely. It looked
inside each record for `0x6B` and `0x6C` and computed
`index = idx_6b * 25 + idx_6c` — bank and offset, i.e. display coordinates.
This fork replaced that with the `0x81 0xCD` read when adding LT support,
which is where the storage index came from.

The LT's records simply do not contain those fields. A full record is:

```
81 cd <abs>   84 cd 00   6d <0xA1+len> <name>   00 7b c2 7c c2 7d 00
```

`0x84 0xCD` is constant `0` in all 1024 records across the eight setlists, and
the trailer is byte-identical in 1018 of them (the other six are artefacts of
splitting at packet boundaries). There is nowhere for a display index to hide.

**Leads, in order of cheapness.**

1. ~~The two commented-out request arrays.~~ Tried 2026-08-23. Neither
   returns preset names or display coordinates. `0x3e9` turned out to be
   **list setlist names** and is now implemented as
   `modes/request_setlist_names.py`. `0x3e8` returns a 20-byte reply
   (`...83 66 cd 03 e8 67 00 68 c0 79 1b 6a`) with no names and no obvious
   payload — unidentified, possibly an ack or a status word.
2. Capture HX Edit talking to the LT in the Windows VM while it renders the
   preset list. It must obtain display order somehow.
3. Ask upstream whether the Stomp's `0x6B`/`0x6C` record fields have a known
   LT equivalent.

**Measured 2026-08-23.** The Program Change sweep works and is now the way to
read display order: the device announces every change unprompted with number
and name, so PC 0-127 yields the full map
(`tests/fixtures/live/display_order_sweep.jsonl`). It confirmed every slot the
operator had read and let the preset-data fixtures be relabelled correctly.

It is a workaround, not a solution. The map describes the *current*
arrangement and must be re-measured whenever a preset moves, it takes about
four minutes, and the device stops announcing after a few dozen changes so it
has to be done in passes. Finding the message HX Edit uses would still be
better.

### Block parsing: plan as of 2026-08-23

Layout is **confirmed** against the device (see CLAUDE.md). What follows is
ordered by dependency. "Device" marks anything needing hands on the LT.

**A. Routing — splits and merges.** The biggest gap and now the most
tractable. Splits/merges are not slots; they live in the four chain-endpoint
segments (slot indices 0/9/10/19 and 20/29/30/39).

Working hypothesis, from diffing preset 24 (Y split + A/B split + two merges)
against presets 36 and 48 (serial):

- `0d <n>` in an **in-lower** endpoint = the position where the lower branch
  begins. Path 1 reads `0d 05` (split after block 4); Path 2 reads `0d 03`.
  Serial presets read `0d 00`.
- `0d <n>` in an **out-lower** endpoint = the position where it merges back.
  Path 2 reads `0d 05`, matching the merge before `Plate`.
- `0xca` + 4 bytes are IEEE-754 floats — mixer level/pan, which is what a
  merge block holds. `utils/ieee754_convert.py` already decodes these.

  A1. (no device) Implement the reader, assert preset 24's topology matches
      what the operator described, and assert serial presets report no split.
  A2. (device) Falsify it properly: take one preset and capture it with the
      split at two different positions. If `0d <n>` tracks, it is confirmed;
      if not, the number is something else that merely correlates on one
      preset. **Do not skip this** — the hypothesis currently rests on two
      presets agreeing.
  A3. (device) Capture a preset with no lower row in use at all, to see what
      an unused path looks like versus a serial one.

**B. Seven unknown module ids.** DONE 2026-08-23. All read off the device and
added to `modules.py`: three Dynamic reverbs, three cabs and an IR block.
Every block in every capture now resolves, and a test fails if a future
capture introduces a new unknown id.

Only loose end: `cd02c4` was reported as "an IR block", so its category is
certain but its exact block name is not; it is entered generically as
`Impulse Response`.

**C. Bypass toggle.** Largely settled already — the operator's reading of
preset 24 confirmed the `0x0a` inversion across seven blocks. To close it:
(device) capture one preset, toggle one block's bypass, capture again, and
check only that slot's flag moves.

**D. UI: four rows of eight.** DONE 2026-08-23. The grid is fed by
`HxPreset.to_layout()` through `HelixUsb.set_preset_layout()`, with bypass
shading, category colours, per-row routing summaries and click-to-inspect.
The legacy HX Stomp strip and its `set_slot_info()` feed were never called and
are now inert; `_set_selected_slot()` in particular called `highlight_slot()`,
which writes to the device.

Left over from it: the grid is display-only. Selecting or bypassing a block
from the UI would write device state and has not been asked for.

**E. Snapshot parameter values.** Each snapshot block is ~628 bytes of
per-block state, unparsed. Deferred: large, and worth having A and D first so
there is somewhere to show the result.

Suggested order: A1 (no device) → A2, B, C in one device session → D → E.


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
- **Snapshot parameter values.** Names, the stored index and live changes all
  work now; the ~628 bytes of per-snapshot parameter state do not.
- **Selecting a snapshot from the UI.** The snapshot row is display-only;
  making the pills clickable means writing device state, which needs asking
  first. The device presumably accepts a snapshot-select message — the one it
  *emits* on a press (`82 69 2a/2e 6a 81 5c <n> 44`) is the obvious starting
  point, but sending it is untested and unasked-for.
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
