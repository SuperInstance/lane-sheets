# QUF-NOTES — lane sheets to actual QUF bytes (downward lane 2)

**SuperInstance, 2026-10-23.** DOWNWARD.md mapped lane-sheet constructs
to the Quilt fabric's opcodes and sketched (its §2) how a compiled
sheet would sit inside a QUF container. This lane builds the honestly
buildable part of that sketch: a QUF **writer** for the clean subset
(numeric value cells, their edges, sheet state), a **reader** that
reconstructs the fabric and verifies agreement by canonical hash, and
a **check suite** that pins every spec-determined byte of the worked
example. Labels, kept strict as in DOWNWARD.md: **SPEC** (pinned by
`SuperInstance/quilt-verilog/docs/QUF-SPEC.md`, cited as QUF-SPEC),
**SKETCH** (proposed, inside QUF's own extensibility rules), **BUILT**
(exists here and was run).

**Result: `python3 run_quf_check.py` → SUMMARY: 45/45 PASS** — byte
assertions, round-trip hash agreement on both fixtures, §8 skip
behaviour, seven §5a negative mutants, both CLIs standing alone, and
the shelf's own §11 golden vector parsed by this reader.

Files: `quf_write.py`, `quf_read.py`, `run_quf_check.py`,
`triage-clean.json` + `triage-clean.quf` (+ `.quf.json` manifest),
`triage-mini.json` + `triage-mini.quf` (+ manifest),
`golden-vector.hex` (extracted from QUF-SPEC §12.2; its sha256 equals
the §11 published digest — check H1), `lanesheet_emit.py` (copied from
the lane-sheets repo; its hash machinery is the contract under test).

---

## 1. The fixture decision: triage-mini is not clean, so triage-clean exists

The brief said to start from triage-mini's clean constructs and to
define a clean fixture if triage-mini carries more. It does: of its
three cells, only `inbox` (value) is a clean row in DOWNWARD §1.
`summarize` (prompt, row 2) and `post_digest` (tool, row 3) are
*lossy* rows — their dial/wiring shadow could cross, their content
cannot. A writer that put those cells into a "clean" image would be
doing silently exactly what DOWNWARD §1 warns against.

So: **`triage-clean.json`** keeps triage-mini's topology, dials, edge
bases, and `tick_tpw` byte-for-byte in shape, with cells 2 and 3 as
numeric value cells (`tally`, `digest_score`) — i.e. precisely the
integer shadows that rows 2/3 say are all that ever crosses — and a
single clean run event (an inject on cell 1). Because the shape is
unchanged, DOWNWARD §2's pre-computed standard-section sizes apply
verbatim and are asserted (check B3): dials 96 B, edges 40 B,
routing 6 B, ticks 16 B.

And triage-mini itself is not dodged: `quf_write.py` *subsets* any
input workflow — value cells and both-endpoints-clean edges are kept;
everything else is excluded **with a named reason in the sidecar
manifest** (check D2). For triage-mini the image is the 1-cell,
0-edge fabric, its hash still agreeing end-to-end (D4). Subsetting is
a reported act, never a silent one.

One cross-check worth naming: the reconstructed fabric's per-cell
hash for cell 1, `0x7dfe8368e40da141`, equals the hash printed in
DOWNWARD §3's emitter listing for triage-mini's cell 1 — the listing
and the binary image describe the same bound fabric. (Cell 2's hash
differs from the listing, by design: the listing's cell 2 is a prompt
cell, Charter type byte `0x02`; triage-clean's is a value cell,
`0x01`.)

## 2. What the spec pinned vs what had to be decided

**Pinned by QUF-SPEC and followed byte-for-byte:** the 16-byte fixed
header (§3); KV encoding and GGUF type numbering (§4); the standard
keys and their writer order (§4); the section-table entry format,
ascending aligned offsets, zero padding, file padded to `align`
(§5, §7); the four section payloads' byte layouts and size formulas
(§6.1–§6.4); `edge.k` = 8 within its 1..16 range; `tick_period` =
2^tpw derived from the ticks section; the opt-in `crc32` KV's
coverage (payload bytes, table order) and zlib convention (§12.2).
The reader implements the §5a checks that apply to parsing — gates
R1/R2, walk bounds R3/R4, the 4 GiB ceiling R5, front-matter overlap
R6, size formulas and present-count assertions R7/R8, alignment R9,
zero padding R11, KV length bounds R12, unskippable types R18, plus
§5's duplicate/ascending/overlap failures — each raising with its
reason code (asserted by mutants F1–F6).

**Decided here, because the spec leaves the byte underdetermined**
(every one named; none presented as spec):

- **D1 — Workflow-id → fabric-address binding.** QUF's `dials` rows
  are positional and its edge/routing addresses are u8; nothing in
  the spec binds a workflow-level id (u64 in the Charter's canonical
  serialization) to a row. Decision: fabric address = rank in
  ascending id order (0-based), and the binding is recorded in the
  SKETCH KV `lanesheet.cell_ids` (u64 array, row order). Consequence,
  tested (E3): without that KV a standard reader reconstructs the
  *same fabric in address space* — the binding is metadata, not
  state. Positional addressing also keeps the image coherent with
  the §9 loader's row-per-cell assumption.
- **D2 — Route set.** §6.3 pins the record shape and the v1 rule
  `via == dst`; it does not pin *which* routes a minimal image
  carries (the golden vector carries a dst-15 route among its 3).
  Decision: exactly one identity route per described cell.
- **D3 — Edge walk state.** §6.2's `mode`, `wh`, `age`, and bucket
  bytes exist in every record; the workflow source carries no values
  for them. Decision: bind-time image — mode 0 (ladder), wh 0,
  age 0, buckets zero. This matches the emitter's stated image point
  ("post-LOAD, pre-run"); a warm fabric's trained state is simply
  not something a lane sheet has to say.
- **D4 — Tick phases.** All zero. §6.4: phases are carried and
  ignored by the v1 fabric; the source carries none.
- **D5 — Edge record order.** Ascending (src address, slot); slots
  are per-src indices in source order (the emitter's LINK order).
  The spec pins record bytes, not their sequence.
- **D6 — The `steps` section (SKETCH).** 12-byte records: u32 step
  index, u32 first_tick, u32 op_count. An inject step is EFFECT+TICK
  = 2 ops and its tick window spans 1 tick (DOWNWARD §1b), so
  sequential windows give first_tick = step index. Only inject steps
  are representable; port-return steps are off-fabric answers and are
  excluded at subsetting (counted in the manifest).
- **D7 — `crc32` KV placement and the missing §12.1 digest.** §12.2
  pins the crc32's coverage and type, not its position among KVs;
  it sits after the standard keys. `quf.sha256` (§12.1) is *not*
  emitted: it is host-side and opt-in, and this image already names
  its source (`lanesheet.source_sha256`) and its state (the fabric
  hash) — a third digest would authenticate nothing new. Named
  here rather than omitted silently.
- **D8 — Producer string.** `quf.version` = `lanesheet-quf 0.1`;
  the spec asks only for "producer identification."

**Not in the image at all:** cell *names*. QUF has no field for them;
identity in the container is the id (via D1), and names live in the
source sheet, which the container references by sha256 — DOWNWARD
§2's "referenced, not carried," now built. The DOWNWARD §2 `lanes`
and `extern` SKETCH sections are likewise **not emitted**, for
different reasons: `lanes` because the workflow source format has no
lane structure to archive; `extern` because extern cells are
*excluded at subsetting with reasons* — a clean image must not
smuggle lossy constructs back in as metadata. The `extern` section
remains the right sketch for a future non-clean writer.

**Writer refusals (named, emitter-style):** no `tick_tpw` in the
source (a schedule will not be invented); >256 clean cells (u8 fabric
addressing); and everything `lanesheet_emit.validate` refuses
(floats anywhere, text fields, bad dials/bases/ids).

## 3. Extensibility behaviour (§8), as built and tested

The image's only non-standard bytes are four `lanesheet.*` KV pairs
and the `steps` section. Both ride on §8's own rules: unknown KV
keys are skipped by type-derived size (rule 1), unknown section
names are skipped via the table (rule 3), and neither bumps
`version` (rule 6). Tested, not just asserted: a reader ignoring
`steps` reconstructs bit-identical state (E1); a foreign `zzlab`
section appended by the writer parses and changes nothing (E2); the
`crc32` KV — spec-optional §12.2 — is verified by recomputation on
every parse (B14, F6). Layout property, deliberate: the standard
sections occupy the lowest offsets in spec order and the SKETCH
section trails them, so even a consumer that only streams the
standard sections front-to-back meets nothing unexpected first.

## 4. Falsifier status — what "loadable" does and does not mean here

**No HDL tooling ran.** `iverilog`, `yosys`, and `verilator` are not
installed on this machine (checked), and this note claims no
testbench, simulation, or silicon verification. What exists is:

1. **This reader, independent of the writer** (no shared tables;
   only the emitter's hash machinery is common, because that
   machinery *is* the contract), agreeing with the writer on every
   byte and hash, and rejecting mutants with the spec's reason
   codes.
2. **The shelf's own golden vector through this reader** (checks
   H1–H5): the §12.2 hex is byte-identical to the §11 vector (sha256
   matches the spec's published digest), and the reader reproduces
   its layout and contents exactly — two implementations of the
   format, written by different lanes, agreeing on a third party's
   pinned bytes. This is the strongest falsifier available short of
   the RTL itself.
3. **Static §9 loader-profile inspection:** names ≤ 255 bytes;
   `edge.k` a u32 in range; file < 4 GiB with zero u64 high words;
   length a multiple of `align`; standard sections byte-shaped per
   §6 with positional rows (§9's binding assumption); `crc32` per
   §12.2, which the loader gates DONE on when present (error 12) —
   computed here exactly as the spec prescribes and verified
   host-side, but **not** verified against the RTL's bit-serial CRC.
   One §9 nuance recorded: DONE asserts "after the last byte of the
   last known section"; the trailing SKETCH `steps` section sits
   after `ticks`, so a streaming host simply never feeds those bytes
   — consistent under the handshake reading, unproven under any
   other.

**Verdict: loadable-*shaped* for the §9 profile by static
inspection; not loaded, not simulated.** The real falsifier — a
`tb/quf_tb`-style load of this image through `rtl/q_uf_loader.v` —
remains future work, named as such. (One reading the golden vector
forced, recorded for the next lane: edge/routing endpoints are
fabric addresses in a space larger than the described cells — the
golden's own edge targets dst 2 and its routing dst 15 in a 2-cell
file. A reader that range-checked endpoints against `cell_count`
would reject the shelf's canonical file; this one doesn't.)

## 5. Scars — what went wrong in this build, unlaundered

- **Zero-size section, shared offset (writer + reader, fixed).**
  The first triage-mini image placed the empty `edges` section and
  `routing` at the *same* offset — legal under my reader's overlap
  check, illegal under §5's "strictly ascending by offset." Found by
  reading my own layout table against §5. Fix: the writer advances
  the cursor one alignment quantum past an empty section, the reader
  now enforces strict ascent, regression check D5.
- **Reader crashed on the golden vector (fixed).** First contact
  with §11's file threw an unhandled `IndexError`: endpoints beyond
  the described cells (§4 above). The reader now maps bound
  addresses to ids and leaves unbound ones as raw addresses.
- **Two checker expectations were transcription errors (checker
  fixed, code untouched).** H3: §11's edges commentary prints *byte
  sequences* (`4000` = bytes 40 00 → base 64), which I had read as a
  value; H5: §11's dials commentary prints *u16 values* (`0800` =
  2048), which I had byte-swapped. In both cases the sha256-pinned
  file sided with the reader. The spec's two commentary styles sit
  one page apart; the bytes are the arbiter.
- **One checker bug (fixed).** The first full run scored 38/39:
  check G3 fed the reader the F7 file — the crc-consistent mutant
  that is *designed to parse* — and reported the reader's correct
  acceptance as a failure. The reader was right; the check now uses
  the padding mutant it meant to use.
- **§5a check order is approximated, not litigated.** The reader
  raises the first failure *it* meets in its walk order, which
  follows §5a's phases but was not verified rule-by-rule against
  every mutant in the spec's regression list (only the seven in
  F1–F6, plus the golden's clean parse). `tools/quf.py` remains the
  shelf's hostile-input reference; this reader is a structural
  parser with the same reason codes, and says so in its docstring.

---

## Addendum (falsifier lane): D9 — the crc32 scope is underdetermined

Loading `triage-clean.quf` into the quilt-verilog RTL loader
(Icarus Verilog, `FALSIFIER.md` in this directory) isolated a ninth
underdetermination the static work could not see. QUF-SPEC §12.2
says the `crc32` digest covers "section data in table order"
without scoping it to *known* sections. The shelf's two readers
disagree: `tools/quf.py` digests **all** table sections (including
the §8-legal `steps` extension); `q_uf_loader.v` accumulates only
over its four payload states. This writer followed `quf.py` — and
the RTL loader therefore stops with err 12 (E_CRC) after consuming
882 bytes of an otherwise exact image. Patching the copy's KV to
the four-section value loads cleanly, and omitting the digest
loads cleanly: the digest is opt-in per §12.2 ("undigested files
load exactly as before"), so `quf_write.py` now offers
`--no-crc32`, and `triage-clean-nocrc.quf` is the booting image.
Neither default was flipped silently: which scope the spec means
is a ruling for the spec's owners, recorded here as **D9**. On any
file *without* extension sections the two readings coincide —
which is why the shelf never tripped over it.

---

*QUF-NOTES — SuperInstance downward lane 2. Built artefacts:
`quf_write.py`, `quf_read.py`, `run_quf_check.py` (45/45),
`triage-clean.quf`, `triage-mini.quf` and their manifests. No
personal names; the shelf is cited by repo path throughout.*
