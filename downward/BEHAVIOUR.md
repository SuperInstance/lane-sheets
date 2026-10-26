# BEHAVIOUR — the booted quilt fabric, driven

**SuperInstance · lane-sheets line · fabric behaviour spike**
Simulation only (Icarus Verilog 12.0 against `SuperInstance/quilt-verilog`
@ `68fb9b4`). Nothing here is a claim about silicon.

## Headline

**DIVERGES — at the run layer, in five named places. The fabric CAN be
driven** through the op sequence the downward mapping predicts (boot →
BIND → LINK → EFFECT/TICK → VIEW, all ACKed, bind-time state byte-exact),
**and the resulting state AGREES with the sheet-side expectation at the
bind layer** — post-boot and post-run dial readbacks are byte-identical
to the image rows, and the canonical fabric hash over the live state is
the image's own `0x96a40d5272fc5798`. **It DIVERGES at the run layer:**
the sheet's inject is silently dropped as mapped; the lowered sink cell
is a free-running oscillator that trains its neighbour once per tick;
activation and trained weight decay at the image's own dial values at
100%/tick and ×½/tick respectively; and even with all of that repaired
and pinned, the sheet's numbers cannot propagate (42 < 12000). The
canonical hash agrees throughout — because it cannot see any of the
state that moved.

## Vehicle and method

The falsifier lane's topology (one `quf_boot` + shadow RAMs) has no live
cores — it proves the image *lands*, and cannot run anything. This spike
uses the fabric's own intended composition instead: `q_serfabric_top`
with `SER_BOOT_QUF=1`, `NCELL=3` — one `quf_boot` per cell on a
broadcast QUF stream, live `q_cell` cores behind a serialized front
end. The testbench (`tb_lane_behaviour.v`) copies the harness shape of
the shelf's `tb/tb_serfabric.v` (byte sender, `packflit`, serialized
egress capture, `waitrun`) and the dial/bucket probe style of its A1
phase; ops are driven exactly as `tb/tb_fabric_smoke.v` drives them
(host src = `0xF` EXTID). Readback is two-legged: the fabric-native
VIEW op (act / wsum / dial rows) and hierarchical probes of the ladder
engines, which no op can reach.

Fixture: `triage-clean` — 3 value cells (workflow ids 1, 2, 3 at
fabric addresses 0, 1, 2 per QUF-NOTES D1), dials all zero except
dial 5 (THRESH): cell 1 = 12000, cell 2 = 8000, cell 3 = 0. Edges
1→2 and 2→3, base 16384 each. Run = one inject `{cell 1, dat 42}`,
`tick_tpw 6` (one tick per 64 cycles). Image: `triage-clean-nocrc.quf`
(928 bytes; the `--no-crc32` variant of QUF-NOTES D9 — the only one the
RTL loader accepts end-to-end).

Sheet-side expectation was computed independently of the simulation
(`expectation.py`, using `downward/quf_read.py`): canonical fabric
hash `0x96a40d5272fc5798`; per-cell `0x7dfe8368e40da141`,
`0x4d581b1d46d5c84c`, `0xa9215e5baf39d98f` (matches the image
manifest); naive step arithmetic per DOWNWARD §1b below.

## The op sequence driven, per workflow step

| Step | Mapping predicts | Driven (measured) |
|---|---|---|
| Load | QUF image | Broadcast byte stream + EOD → RUN, epoch latched, tpw = 6, err 0 |
| Bind cells | BIND ×3 | BIND ×3 (a0 = address); 3 ACKs (op 5, `OP_ACK`); core `cell_id` registers read 0, 1, 2 |
| Bind edges | LINK ×2 (one per edge) | **LINK ×4** — each directed edge needs a pairing at *both* endpoints (see D-B2) — plus **LINK ×1** for the port (D-B1). LINK ACKs are addressed to the LINK's src (the peer), so cell-to-cell links give the host no response; they were confirmed by wsum readback (16384 / 32768 / 16384) |
| Step 1: inject + tick window | EFFECT cell 1 dat 42; TICK | EFFECT src=EXTID dst=0 dat=42 — **silently dropped** as mapped (P5). With the port pairing installed it lands in 21 cycles, act(cell 0) = 42; the window's first tick erases it (P6) |
| Readback | VIEW | VIEW(0) act, VIEW(1) wsum, VIEW(2) dial — all answered ACK with the viewed cell as src |

One scale fact the table hides: by the time the inject landed,
**1,882 ticks** had elapsed since release. A serialized flit costs
≥ 40 cycles on the wire plus ring transit (~70–100 cycles per VIEW
round trip) against a 64-cycle tick — the host cannot pace ops to
tick windows; between any two host ops the fabric lives 1–3 ticks.

## Where it agrees

- **Bind layer, byte-exact.** All 45 stored dials (3 cells × 15; dial
  13 is a live FTRACE probe, excluded) read back over VIEW identical
  to the image rows — after boot (P2) and again after the run (P8).
  Edge bases read back exactly via wsum. The canonical hash over the
  live post-run state therefore equals the image hash above.
- **The step's fire outcome.** Both models say nothing propagates:
  the naive sheet arithmetic gives act = (16384·42)>>>15 = 21 < 12000;
  the fabric, repaired and pinned, gives 42 < 12000. The chain is
  quiescent in both — for different numbers (D-B5).

## Where it diverges (all measured)

**D-B1 — the inject has no mechanism as mapped.** An EFFECT is
integrated only if the receiving cell's edge table holds a pairing
for the flit's src (`q_cell_core` ST_EFFT); otherwise it is dropped
with **no NAK, no egress, no state change** (P3 negative probe and P5,
the sheet's own inject: act stays 0, response count unchanged). The
mapping's "the sheet's loader binds the port as the src of record"
names no fabric operation that does this. The minimal repair is a
fifth LINK (dst 0, src EXTID, slot 1) whose base is a units decision
the sheet never made; this spike used base 32768 (0x8000, identity:
dat crosses unscaled). With it, the inject lands — and the fabric's
train-then-integrate order makes act = ((32768+256)·42)>>>15 = **42**,
not the naive 21.

**D-B2 — a directed edge is two LINKs, not one.** The image stores
each edge once, at its source; the live core integrates on the
*receiving* cell's synapse-for-src and fans out on the *sending*
cell's table. Source-only links (the mapping's count) leave every
EFFECT unmatched at its destination. The lowering pass must emit
both pairings and must name state the sheet doesn't have: an
intermediate cell's incoming pairing takes a second slot (cell 1:
slot 0 = peer 0 from the image's record, slot 1 = peer 2).

**D-B3 — the sink cell is an oscillator, and it trains its
neighbour.** Cell 3's dial row is all zeros, which the sheet reads
as an inert value cell. In the fabric THRESH = 0 means *fire every
tick*: act 0 ≥ thresh 0, REFR 0. Each fire fans out dat 0 to cell 2,
and every received EFFECT trains the receiving synapse — so cell 1's
slot-for-2 bucket vector fills at exactly one train per tick,
reaching the steady state [1,1,1,1,1,1,1,1] by tick 8 and holding it
at tick 16 (P4). Corroborated three ways: the bucket fill rate, cell
2's FTRACE probe reading 65535 against 0 for the other cells (P2/P8),
and 5 trains counted in bucket 0 during the compensation run's pin
traffic (P9). With no input at all, wsum(cell 1) moved from 32768
(bases) to 33022 within 16 ticks of the links landing, and read
33278 at a later late-phase sample. **The lowered workflow's state
changes autonomously.**

**D-B4 — metabolic decay, measured.** At the image's own dial values
(KA = 0, HL = 0 — both are authored zeros in the sheet's rows):

- *Activation:* leak is `act − (act>>>KA)`; at KA = 0 that is total.
  The inject's act 42 read **0 after exactly one tick** (P6). An
  activation's lifetime at the authored dials is one tick window,
  whether or not it fires.
- *Trained weight:* HL = 0 makes the ladder shift every tick (the
  RTL comment says HL ≥ 1 "by dial contract"; the image violates
  it), so a single train's readout increment halves per tick:
  256 → 128 → … → 2, **extinct at the 8th shift**. The P7 series
  entered mid-decay and halved cleanly across six consecutive
  sampled ticks (32, 16, 8, 4, 2, 0); the port edge's wsum returned
  to bases-only (49152) by the end of the window.
- *Equilibrium under retraining:* the oscillator-fed edge of D-B3
  holds bucket vector [1×8], but its wsum *sample* depends on the
  phase within the tick: early-window buckets [0,1,1,1,1,1,1,1]
  (post-shift, pre-train) read increment **254**; late-window
  [1,1,1,1,1,1,1,1] (post-train) reads **510** (P4/P4b/P7 samples:
  33022 and 33278 for the same steady state). A readback of a live
  edge is a phase sample, not a value.

**D-B5 — the numeric regimes never meet.** dat and THRESH live in
one s16 arithmetic on the fabric. The sheet authored a small data
integer (42) against large thresholds (12000, 8000): the largest
contribution any single EFFECT can make at dat 42 is
(65535·42)>>>15 = 83, two orders below the first threshold. No
decay pin changes this (P9: still no propagation). The models agree
on the outcome and disagree on the arithmetic — the lowering pass
never reconciled the units.

**D-B6 — the canonical hash is blind to all of it.** The Charter
serialization covers id + dials + neighbours. act, ladder buckets,
wh — the entire run layer — are outside it, and outside the QUF
image's post-boot representation too (its walk-state fields are
bind-time zeros, QUF-NOTES D3). Post-run, the hash "agrees" because
the run is invisible to it. Agreement-by-hash certifies the bind-time
image, full stop. A related observability gap: bucket-level state
has **no op-level readback at all** — VIEW exposes act, wsum and
dials only; the bucket numbers above exist because simulation
allows hierarchical probes.

## The compensation run (P9) — what pinning buys, measured

Fresh boot, same links, then BIND dial writes pin KA = 15 and
HL = 65535 on all cells and THRESH = 32767 on the sink cell:

- Oscillator stopped: wsum(cell 1) and bucket 0 **identical before
  and after 16 ticks** (34300, bucket0 = 5 — the 5 are pre-pin
  trains, counted, not hidden).
- Activation retained: act(cell 0) = **42 after 8 ticks** (leak
  42>>>15 = 0), against 1-tick erasure unpinned.
- Weight retained: one train's increment read **+256 unshifted
  after 8 ticks**; wsum(cell 0) = 49408, exactly 16384 + 32768 + 256.
- Propagation: still none (D-B5 is not a decay problem).

## What a real QUIL must compensate for

1. **Emit the port pairing, and own its base as a units decision.**
   Without it the inject is dropped *silently* — the fabric returns
   no error, so a QUIL runtime cannot detect the drop; it must be
   right by construction (D-B1).
2. **Emit both endpoint pairings per edge**, and treat the
   intermediate incoming slot as lowering-owned state (D-B2).
   Confirm links by wsum readback; the op stream itself confirms
   nothing to the host.
3. **Pin the decay dials in the image, or design a refresh
   discipline.** KA and HL are semantics, not tuning: at the
   authored zeros, activation lives 1 tick and trained weight 8.
   The pins are cheap (one BIND each) and measured to work — but
   they must be *in the lowering*, because the sheet's rows as
   authored specify a fabric that forgets everything (D-B4).
4. **Pin THRESH (or REFR) on every lowered value/sink cell.** An
   all-zero row is not inert; it is a 1-fire-per-tick training
   source that rewrites its neighbours' weights autonomously
   (D-B3).
5. **Schedule in ticks, not ops, and sample at a named phase.**
   The metabolic clock outruns the host (~1.9k ticks across this
   spike's preamble; 1–3 ticks between host ops), and wsum-class
   readbacks of live edges carry ±1 train of phase fuzz (254 vs
   510). Conformance comparisons must freeze ticks, fix a phase,
   or budget the fuzz (D-B4).
6. **Reconcile numeric regimes at lowering time** — dat scale
   against threshold scale — because no run-time pin repairs a
   step whose maximum possible contribution is 83 against a
   threshold of 12000 (D-B5).
7. **Give run state its own conformance surface.** The canonical
   hash cannot certify behaviour (D-B6); a QUIL conformance story
   needs act/wsum snapshots at named ticks — and bucket-level
   fidelity is unavailable through the op set at all.

## Receipts

- Testbench: `tb_lane_behaviour.v` (this directory; also on the
  simulation host at `~/lane-hdl/behaviour/` and in the clone at
  `tb/tb_lane_behaviour.v`). Result: **LANE_BEHAVIOUR PASS**, zero
  check failures; every number above is an OBSERVE line of the run.
- Run log: `run.log` (this directory).
- Expectation: `expectation.py` (hash + dial rows + naive step
  arithmetic, from `downward/quf_read.py` against the shipped
  image).
- Prior lanes: `downward/DOWNWARD.md` (the mapping under test),
  `downward/QUF-NOTES.md` (D1 addressing, D3 walk-state zeros, D9
  crc scope), `downward/FALSIFIER.md` (the boot this spike builds
  on).
- Reproduce: generate `tb/run/triage-nocrc.hex` (count-first hex of
  `triage-clean-nocrc.quf`), compile with the suite RTL list plus
  the serfabric set (`q_uf_loader`, `quf_boot`, `q_tick_sched_rt`,
  `q_boot_gate`, `q_serfabric_top`), run under `vvp`.

*SuperInstance — lane-sheets downward line. Simulation only; no
silicon was involved, and none is claimed.*
