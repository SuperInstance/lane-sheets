# Downward Falsifier — a lane-sheets QUF image in the quilt-verilog fabric's own flow

**SuperInstance.** The lane-sheets QUF writer's output was, until now,
"loadable-shaped by static inspection only — not loaded, not simulated"
(QUF-NOTES.md). This lane ran the real falsifier: the fabric's own RTL
loader and boot wrapper, in simulation, against the shipped image.

## Headline outcome: LOADED — and the fabric BOOTS on it, with one named precondition

The shipped image (`downward/triage-clean.quf`, md5
`e4e6a2eff8a5e574f83b043d664a0efa`, byte-identical to the copy tested)
is **rejected by the RTL loader as shipped** — error **12 (payload
digest mismatch, QUF-SPEC §12.2)** — because of a genuine spec
underdetermination: §12.2's digest coverage is read two different ways
by the shelf's own two reference consumers once a §8 extension section
is present (diagnosis below; proposed as QUF-NOTES item **D9**).

With the **opt-in** crc32 KV omitted — a variant the spec explicitly
provides for ("undigested files load exactly as before", §12.2) — a
regenerated image **loads end-to-end and boots the fabric**:

- `LANE_TB PASS: 928-byte QUF loaded, dial + edge readback byte-exact`
  (the fabric's `q_uf_loader` + `q_dialfile`, stock harness shape)
- `LANE_BOOT PASS: lane-sheets QUF warm-start boots the fabric — RUN
  reached, epoch latched, dial + edge readback byte-exact`
  (the fabric's `quf_boot` wrapper: fabric released from reset, tick
  period latched, the runtime dial port live in RUN, a dial write
  attempted during LOAD refused)

Every other byte of the image — header, all KVs (including the
`lanesheet.*` keys and the `cell_ids` array), the five-section table,
all four standard payloads — is consumed by the fabric's own code
exactly as shipped. The digest was the only blocker.

This is **simulation** (Icarus Verilog, event-driven RTL simulation).
It is not synthesis, not timing closure, and not silicon.

## Environment facts (measured, not assumed)

| | This VM | Oracle (`147.224.38.131`, aarch64 Ubuntu) |
|---|---|---|
| iverilog / yosys / verilator in PATH | none | none initially |
| apt candidates | iverilog 12.0-2build2, yosys 0.33, verilator 5.032 | iverilog 12.0-3 |
| install | **blocked**: the session's own backgrounded `apt-get update` held the `/var/lib/apt/lists` lock for the duration; not forced | `sudo -n apt-get install -y iverilog` → **Icarus Verilog 12.0**, used for every run below |

- Fabric source: `SuperInstance/quilt-verilog` at
  `68fb9b4c01fe9449739fa22cd6e96befbc7c7dab` (2026-09-27), cloned from
  the public repo on both machines.
- All simulations ran on Oracle with the system iverilog above. The
  repo's scripts prepend an oss-cad-suite path that does not exist in
  either environment; the flows below were invoked directly with the
  system toolchain instead (invocation adapted, images untouched).

## The flow

The fabric's load path (QUF-SPEC §9, the RTL loader profile) is
`tools/quf.py` (full-spec host tool) + `tb/quf_tb.v` streaming a
byte-per-line hex image into `rtl/q_uf_loader.v` with `rtl/q_dialfile.v`
as the state target, and `tb/tb_quf_boot.v` streaming bytes into
`rtl/quf_boot.v` for the full boot behaviour. The stock assertions are
golden-image-specific, so two variant testbenches were derived from the
stock ones — harness tasks byte-identical, only the input file and the
expected values changed (both variants live in this workdir:
`tb_lane_load.v`, `tb_lane_boot.v`). Expectations for address 0 come
from the image itself via the lane-sheets reader: dial row
`[0,0,0,0,0,12000,0,…]`, edge `{base 0x4000, dst 1, mode 0}` at slot 0,
identity routes, `tpw 6`.

Runs, in order:

1. **Control (stock golden):** `quf.py selftest` PASS; `quf.py create
   tb/quf_tb.json` → stock TB → **`QUF_TB PASS: 576-byte QUF loaded,
   dial + edge readback byte-exact`**. The harness and environment are
   sound.
2. **Their host tool on our image:** `quf.py info` decodes it fully —
   15 KVs (the four `lanesheet.*` keys and the `cell_ids` array
   included) and all 5 sections at the offsets/sizes our manifest
   claims. `quf.py verify` exits 1 — see "Second defect" below.
3. **Our image, loader TB:** the stock-shaped run hangs (global
   timeout). A diagnostic variant (`tb_lane_diag.v`, per-word stall
   watchdog + hierarchical state probe) shows why: the loader consumes
   **882 bytes** — header, all 15 KVs, the section table, and all four
   known payloads (ticks ends at byte 880) — then raises **`err=12`
   (E_CRC)** and stops accepting words (`done` never asserts).
4. **Coverage experiment:** our crc32 KV (1674213041) is zlib CRC-32
   over **all five** section payloads in table order. CRC over only
   the four standard sections is 271056174. Byte-patching a *copy* of
   the image's KV to that value (no other byte changed) →
   **`LANE_TB PASS`** with every content assertion byte-exact. The
   loader's coverage reading is thereby proven, not inferred.
5. **Writer fix + regenerated image** (below) → `quf.py hex` →
   **`LANE_TB PASS`** on the unpatched regenerated image.
6. **Boot:** the regenerated image streamed byte-wise into `quf_boot`
   (WARM-case variant) → **`LANE_BOOT PASS`** as quoted above.

## The defect: §12.2 digest coverage is underdetermined for extension sections (proposed D9)

QUF-SPEC §12.2: digests cover "PAYLOAD bytes only (section data in
table order)". It never scopes "section data" to the sections a given
consumer knows. The shelf's consumers diverge exactly there:

- `tools/quf.py` — writer **and** verify: CRC over **every section in
  the table** (`parsed["table"]`, no name filter). Its own files never
  carry extension sections, so the question never arises on its corpus.
- `rtl/q_uf_loader.v`: the CRC accumulator sees "payload-state bytes
  only" — the four standard sections it has states for. An extension
  section's bytes never enter its digest.

A §8-legal container that carries both an extension section (our
`steps`) and a crc32 KV is therefore digest-valid to one reference
consumer and digest-invalid to the other. Our writer followed the
Python reference's reading (all sections). Neither reading contradicts
the spec text. **Classification: spec underdetermination, not a writer
bug and not a loader bug** — it needs a spec ruling (either "digest
covers standard sections only" or "extension sections must be
digest-covered and loaders must stream them through the accumulator").

### Fix applied (workdir copy only; nothing committed anywhere)

`writer-fix/quf_write.py` gains a `--no-crc32` flag: the opt-in digest
KV is omitted, which §12.2 explicitly supports ("covers ONLY
containers that carry the KV — undigested files load exactly as
before"). Default behaviour is unchanged, and the lane-sheets
conformance suite still passes **45/45** in the patched copy. The
regenerated image is 928 bytes with an identical section layout
(kv_count 14; the header shrinks into the same alignment padding).
The known-sections-coverage alternative was demonstrated (run 4) but
**not** adopted as a default: it would make `quf.py verify` flag the
file instead. Shipping either default silently would be picking the
spec's ruling unilaterally; the flag keeps both artefacts honest
until the spec rules.

## Second defect (theirs): `quf.py verify` cannot round-trip array header KVs

`quf.py verify` fails on our image with `array value must be
(elem_type, list)` — before any CRC question. Decisive isolation:
`quf.py create` on the golden document plus one plain-list extra
header key emits a file carrying `test.arr array [1, 2, 3]` (their
`info`), and **their verify fails on that file with the identical
error**. Their verify re-encodes the parsed document, and their parser
stores array values as plain lists, discarding the element type the
encoder demands — so verify rejects *any* file with an array header
KV, including their own writer's output. Our `lanesheet.cell_ids`
(a u64 array) is §4-legal: their `info` decodes it correctly and the
RTL loader skips it correctly (it is consumed en route to byte 882 in
run 3). Not our defect; recorded here because it blocks using their
verify as an oracle for foreign files with array KVs.

## What remains unproven, even with the PASSes above

1. **Simulation only.** Icarus Verilog event simulation of the RTL —
   no synthesis, no place-and-route, no timing, no silicon. The
   repo's published iCE40/ECP5 results are for the fabric's own
   images, not this one.
2. **Per-cell profile.** The §9 loader loads the row and edges of
   `i_mycell` only; the readbacks here verify address 0's row and
   edges. The payloads for addresses 1–2 were *consumed* (the loader
   streams every row; the CRC gate in run 4 confirms byte-level
   transit) but not *read back* from an address-1/2 seat.
3. **Boot ≠ behaviour.** The fabric boots on the image and the dial
   port is live, but no workflow *ran*: no flit was injected, no
   tick-driven computation observed. The `steps` section (the
   workflow's run events) is skipped by the loader by design; a
   fabric that executes sheet semantics is the QUIL question, still
   unbuilt.
4. **Only the WARM boot case** was adapted. The corrupt-header,
   truncation, and epoch-latch cases were not re-run against this
   image.
5. **D1 stands.** The workflow-id→fabric-address binding (rank order)
   is still the writer's convention; the fabric is address-based and
   treats `lanesheet.cell_ids` as skippable metadata — nothing in the
   fabric validates the binding.
6. **D9 is a proposal, not a ruling.** Until QUF-SPEC scopes §12.2,
   any digest-carrying container with extension sections is a coin
   flip between the shelf's two consumers.

## Artefacts in this workdir

- `FALSIFIER.md` — this report
- `tb_lane_load.v` — loader-TB variant (lane expectations)
- `tb_lane_diag.v` — diagnostic variant (stall watchdog + state probe)
- `tb_lane_boot.v` — boot-TB variant (WARM case, lane expectations)
- `triage-clean.quf` — the shipped image (md5-identical to the repo's)
- `triage-clean-crc4.quf` — the byte-patched coverage-experiment copy
- `writer-fix/` — the patched writer (+ reader, checker, sources);
  `writer-fix/triage-clean-nocrc.quf` is the regenerated image that
  loads and boots; its `.json` sidecar is the regenerated manifest
- `quilt-verilog/` — the fabric clone used for source reading
  (all runs executed in the Oracle-side clone of the same commit)
