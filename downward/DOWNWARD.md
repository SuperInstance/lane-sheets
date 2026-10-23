# DOWNWARD — lane sheets toward the substrate

**A design note (with one small built proof) from the SuperInstance
lane-sheets spike, 2026-10-22.** It maps the lane-sheet workflow format
*down* — toward the Quilt VM opcodes and the QUF container — and says
exactly where the mapping holds, where it loses something, and where it
stops. Companion to the shelf study at
`~/workspace/lane-sheets-study/DOSSIER.md`.

**Labels used throughout, kept strict:**

- **SPEC** — pinned by a document on the shelf, cited by repo path.
- **SKETCH** — proposed here; consistent with the spec's own
  extensibility rules, but nobody's standard.
- **BUILT** — exists and was run in this spike, with the output shown.

**Sources read directly for this note:** `SuperInstance/quilt-verilog`
(README, "The 5+1 opcode model" and "The Law") and its
`docs/QUF-SPEC.md`; `SuperInstance/AI-Writings/docs/QUIL-HLS-RFC.md`;
`SuperInstance/quilt-engine-ports` (README);
`SuperInstance/quilt-cell-router/cell_router.py`. The Charter and
`quilt-agent` cell taxonomy are cited via the DOSSIER (§2, §4), which
read them on the same day.

---

## 0. The target, stated precisely

The fabric's entire instruction set is one 3-bit opcode field
(**SPEC**, `quilt-verilog` README):

| op | code | what it does (RTL telling) |
|---|---|---|
| BIND | 0 | first bind sets `cell_id` and binds the cell; later binds write one dial |
| LINK | 1 | edge slot := {peer, base weight} — "wiring as data" |
| EFFECT | 2 | if src matches a valid edge: Hebbian-train that edge, read the weight back, integrate `act += sat((w·dat)>>>15)`; unknown src dropped silently |
| VIEW | 3 | read `act` / `wsum(edges)` / a dial; the response flit carries the value |
| TICK | 4 | decay sweep over all valid edges, leak `act`, fire test (`act ≥ thresh ∧ refr = 0`) → fanout effects to every linked peer |
| ACK / NAK | 5 / 6 | the +1 in this telling: every bind/link/view is answered — never left hanging |

Two cautions before any mapping is built on this:

1. **There are two tellings of the five.** The behavioral Python lane
   glosses them more simply (EFFECT = "propagate dial[0] to
   neighbors"; TICK = "advance all dials by 1"). This note maps
   against the **RTL telling**, because that is the one with receipts
   (23/23 benches, 6/6 formal proofs, silicon — DOSSIER §3).
2. **The richer VM family (Contract B) has not converged.** The
   house's own `quilt-conformance` ledger records 7 MATCH / 29 DIVERGE
   across its five ports (DOSSIER §1b). Where Contract B gestures at
   semantics this mapping would love to borrow (subscribers, effects
   with inverses), this note flags the gesture and does not build on
   it.

The workflow side of the mapping is the lane sheet as it exists on the
shelf: `quilt-agent`'s taxonomy — value cells (memory), API/tool
cells, program cells (reasoning), listener cells (goals), and the
prompt as a formula cell over the conversation — plus the graph
constructs any LangGraph-shaped workflow needs: lanes, edges with
branches, joins, and the sheet's state as a whole.

---

## 1. The mapping table

**Verdicts: 2 clean · 6 with loss · 2 do not map** (10 constructs).

| # | Lane-sheet construct | Fabric image | Verdict |
|---|---|---|---|
| 1 | **Lane** (a named path/region of the workflow) | A subset of cells + their LINKs + routing entries. No opcode names a lane; nothing in fabric state can answer "which lane is this cell in." Lanehood survives only as container metadata (§2's `lanes` section, SKETCH) and compiler bookkeeping. | **Maps with loss** — the loss is identity and boundary: at runtime there is no lane, only cells. |
| 2 | **Prompt cell** (formula cell assembling a prompt from dependencies; `quilt-agent`) | A formula-type cell (Charter type `0x02`) + LINK wiring for its dependencies + a black-box port for the text itself (QUIL `propose`; fabric Law 4's generic IO contract). What crosses into the fabric is an integer shadow — a score, a count, a handle — never the prompt. | **Maps with loss** — the loss is the content. The wiring and the dependency shape survive whole; the text does not cross, by grammatical quarantine (QUIL §1.5). |
| 3 | **Tool cell** (API cell: dispatch a call, await the result) | An egress/ingress port (Law 4: "any IO can enter a cell; adapters are thin and dumb") whose completion is disciplined by the response channel: result word + ACK, refusal/timeout + NAK. | **Maps with loss** — payloads collapse from text/JSON to one 16-bit `dat` word per EFFECT; latency moves off-fabric (§1b); the error taxonomy collapses to NAK. |
| 4 | **Value cell, numeric** (a scalar the workflow holds) | BIND writes dials; the Charter's canonical type byte `0x01` is literally "value cell." A datum in flight rides as an EFFECT `dat` word. | **Maps cleanly** — inside the Q1.15 / u16 envelope the fabric's dials and `quant.*` declarations speak of (`quf.py` refuses floats; state is pre-saturated fixed-point). Outside that envelope the same cell drops to lossy — the boundary is stated, not hidden. |
| 5 | **Value cell, text / JSON / growing history** (e.g. `quilt-agent`'s conversation cell) | None. There is no string type anywhere in the stack: QUF state is 16 u16 dials per cell; QUIL's only type is `int<PW>` — "no floats, no strings, no pointers." | **Does not map** — the cell's *shadow* (length, hash, last-score) can be bound as dials, but the value itself lives in the sheet layer, referenced by hash (§2). |
| 6 | **Program cell** (a reasoning step: arbitrary transform of inputs; `quilt-agent`'s reasoning chain) | A bound cell — and nothing else. No opcode loads code; the fabric's only "program" is the fixed integrate → decay → threshold-fire behaviour of `q_cell_core`. | **Does not map** in general. The subset of programs that *are* weighted integration plus a threshold (scoring, aggregation, voting) is real but is exactly rows 7–8's machinery, not a program lowering. Contract B's richer EFFECT semantics might someday widen this; its conformance ledger says not yet (§0, caution 2). |
| 7 | **Branch / edge** (A→B, possibly conditional) | The wire: LINK — clean, it is "wiring as data." The condition: the tick fire test, `act ≥ thresh ∧ refr = 0`, and on fire the fanout goes to **every** linked peer; selectivity must be arranged through weights and thresholds, not stated. And a seam with no workflow analogue: **traversal trains.** EFFECT is a Hebbian train on the matched edge, so a fabric wire's weight is a function of its traffic history. A workflow edge is inert; a fabric edge learns. | **Maps with loss** — predicate language collapses to threshold-on-activation (plus refractory gating); fanout is unconditional-on-fire; and the wire is not neutral — using it changes it, unless the lowering pins weights or accepts a workflow that learns its own routing. |
| 8 | **Join** (wait for several upstreams, combine) | EFFECT integration is native summation into `act` — an accumulating, OR-flavoured join is the fabric's home behaviour. An AND-join (fire only when *all* upstreams delivered) has no barrier primitive; it must be encoded as threshold arithmetic over expected contributions. | **Maps with loss** — barrier semantics, per-upstream provenance (VIEW exposes `wsum`, an aggregate), and join timeouts are all lost. What survives: the sum, and the fire. |
| 9 | **Listener / goal cell** (`quilt-agent`: goals as listener cells) | Pull form: VIEW — clean as far as it goes. Push form: wire the listener to fire on the watched cell's fanout (a threshold arrangement). There is no subscription object and no event payload; the "event" is an activation crossing. (Contract B tellings mention subscribers — unconverged, §0.) | **Maps with loss** — the subscription as a first-class, inspectable thing is lost; notification carries no payload beyond the `dat` word. |
| 10 | **Sheet state** (the workflow's whole state; checkpoints) | QUF: the whole-fabric binary container — dials, edges with walk counts, routing, tick schedule — plus the canonical serialization and FNV-1a hash as the state's identity. A checkpoint *is* a QUF image; two substrates agree on state by comparing hashes (DOSSIER §2). | **Maps cleanly** — as a container discipline, for the fabric-resident shadow of the state. The content state (rows 2, 5) is not *in* the checkpoint; it is referenced from it by hash (§2). The §5a hostile-input rules (honest counts, zero padding, reject-or-skip with reason codes) come with the format, free. |

Three seams deserve to be said plainly, because they are where a
lowering would quietly lie if nobody named them:

- **The fabric is metabolic; workflow state is not.** Every TICK runs
  a decay sweep and leaks activation, whether or not the workflow did
  anything. A lane sheet lowered naively has state that *rots between
  steps*. The lowering must pin the decay-governing dials (the
  `q_dialfile` map, QUF-SPEC §6.1) to neutral for workflow cells, or
  price decay into the mapping — there is no third option.
- **The fabric answers operations, not questions about operations.**
  There is no opcode for "is cell X in lane Y," "which upstream
  contributed," or "why did this fire." A lowered workflow's
  observability is VIEW of dials and aggregates — the explanation
  layer stays in the sheet runtime, above the fabric.
- **Silence is a defined behaviour in exactly one place, and it is
  the dangerous one.** EFFECT from an unknown src is *dropped
  silently* (README). Everywhere else the fabric answers. A lowered
  sheet must bind every sender of record, or accept that some of its
  messages can vanish without a trace — the emitter in §3 encodes
  this as a loader obligation.

---

## 1a. Which +1 does the workflow world actually need?

The five are stable everywhere; the sixth opcode is a different
channel in each lineage that has one (DOSSIER §2). The three
candidates are not three spellings of one idea — they are three
different *kinds* of thing, and the workflow constructs vote
differently on each:

- **ACK/NAK** (`quilt-verilog`): a **response channel** — a claim
  about *operations*. Every bind/link/view is answered, and the
  property is not a courtesy: "every op terminates and every op is
  answered" is formal proof #5 in that repo. NAK already carries the
  workflow-shaped meaning "understood, but not serviceable" — the
  v1 fabric NAKs the cosine VIEW readout it cannot yet serve.
- **FORGET** (`quilt-engine-ports`): a **teardown operation** — a
  claim about *state handed out*. In that telling it is bound up with
  grant-tracking: what was granted must be revocable and accounted.
  The format side agrees on the placement: `QUF-FORGETTING-V1.md`
  makes forgetting a property of *epochs* — sealed archives, demotion
  instead of destruction — i.e. a storage/lifecycle concern, drafted
  as a format, with no RTL (DOSSIER §2).
- **GHOST** (`quilt-cell-router/cell_router.py`): a **staleness
  audit** — a claim about *time and integrity*. GHOST finds cells
  that are old-and-unrouted or whose integrity fell below threshold
  and *marks* them (`is_stale`); the beachcomber does not answer
  operations and does not itself delete. Tellingly, that engine runs
  GHOST **inside** its TICK reconcile pass — an audit the runtime
  performs periodically, not a channel an operation waits on.

Now argue from the constructs. A lane sheet's step machine spends its
life issuing operations against things it does not own: tool cells
dispatch calls to the outside (row 3), prompt cells await a model
(row 2). The defining uncertainty of a workflow step is therefore
*operational*: **did the outside answer, and with what?** A lowered
workflow that cannot represent "outstanding" and "refused" cannot
represent a tool call at all — its runs would hang in exactly the way
the RTL's proof #5 exists to forbid. Only ACK/NAK speaks about
operations. The tool call awaiting its result *is* an unanswered op;
the fabric's answer discipline is the only +1 that gives it a
representation, and it arrives with the strongest receipt on the
shelf (a machine-checked proof, not a convention).

The other two needs are real — but they are not the step machine's
need, and the shelf has already placed both:

- **The dropped branch is mostly not FORGET.** A branch not taken is
  normally *not an event*: no EFFECT crosses the wire, nothing was
  granted, nothing needs revoking. Genuine retraction — a cancelled
  run, pruned memory, an expired checkpoint, a tool grant withdrawn —
  does occur in workflow life, but it is rare and epoch-shaped:
  exactly where `QUF-FORGETTING-V1` puts it (archives and demotion at
  the format layer) and where `quilt-engine-ports` exercises it (at
  bind/teardown time, with grant-tracking). FORGET is the lifecycle
  layer's opcode, not the step's.
- **GHOST is the run supervisor's tool, and it composes rather than
  competes.** Long-running workflows do accumulate stale outstanding
  calls and low-integrity intermediate state, and somebody must sweep
  for them. But the sweep *marks*; it does not answer. In the one
  engine that has it, GHOST runs inside TICK — which is where the
  workflow mapping wants it too: an audit phase of the runtime's
  tick, downstream of the ACK/NAK discipline that tells it what
  "outstanding for too long" means.

**Conclusion:** the workflow world's +1 is **ACK/NAK**. Its open
question is asked of the outside world — *did it answer?* — and
ACK/NAK is the only candidate that is answer-shaped. FORGET retires
to the epoch/format layer the shelf already drafted for it; GHOST
retires to the audit sweep inside TICK. A lane-sheet dialect should
say so explicitly, because the corpus's three-way split on the sixth
opcode is precisely the kind of seam that otherwise gets papered over
by picking whichever telling was read last.

## 1b. Time: what a workflow step becomes in tick terms

LangGraph-shaped workflows are step-driven: nodes execute in steps
(super-steps, in the Pregel model underneath), a node's writes land
at the step boundary, and the next step reads them. External waits —
a tool call, a model call — happen *inside* a node's execution, in
wall-clock time.

The fabric's time is a different animal. TICK is global, periodic
(the header's `tick_period` is the semantic period `2^tpw`, QUF-SPEC
§4/§6.4), and **non-deferrable**: a pending tick suppresses ingress
until serviced, proven under permanent ingress flood (DOSSIER §3).
At each tick: decay sweep, leak, fire test, fanout. Traversing one
edge costs one tick (NQ-C3's semantics carry a one-tick edge delay —
QUIL-HLS-RFC §3.1).

The mapping that respects both clocks:

> **A workflow step becomes a tick window.** The interval between two
> tick boundaries in which (1) the step's ops are issued and each is
> closed by ACK/NAK, (2) internal propagation runs at one edge per
> tick — so a chain of depth *d* inside one logical step costs *d*
> ticks — and (3) the step *commits* at the closing boundary:
> cross-step visibility happens only at fanout, never mid-window.

This is less forced than it looks. The super-step already *is* a
barrier discipline: messages sent in one super-step are read in the
next. The tick is the same barrier with physics attached. The two
models even agree on the depth tax — a Pregel chain also advances one
node per super-step.

What does not survive the translation, named:

1. **Housekeeping the step never asked for.** The tick decays and
   leaks on every period, active workflow or not (§1's metabolic
   seam). Step-time is event order; tick-time is a metronome that
   also *edits the state*. The lowering owes the workflow pinned
   decay dials, or the sheet's semantics drift with idle time.
2. **Wall-clock latency has no tick address.** A tool call takes
   seconds to minutes; a tick period is `2^tpw` cycles. The wait
   therefore cannot live *inside* a tick — it lives **between tick
   windows**, at the port: the step's op is issued, the lane presents
   no further ops, and the window closes when the port's ACK/NAK
   lands. The fabric never waits; a lane can. The container already
   half-anticipates multi-rate lanes — the `ticks` section carries
   per-cell phase offsets, ignored by the v1 single-clock fabric and
   "carried for v2 metronome cells" (QUF-SPEC §6.4). Anticipated by
   the format is not implemented by the loader; label accordingly.
3. **Two clocks must both be kept.** The sheet layer keeps the step
   log (event order — the workflow's own history, its active log).
   The fabric keeps tick count. A run's record names the tick window
   each step committed in; neither clock substitutes for the other,
   and a lowering that collapses them will misreport both latency
   and ordering.

---

## 2. A compiled lane sheet inside a QUF-style container — SKETCH

**Status: SKETCH throughout, except where marked SPEC.** The claim is
narrow: a compiled lane sheet *is* a fabric image plus lane-sheet
metadata, and QUF's own rules already make room for exactly that —
unknown KV keys are skipped (§8 rule 1), unknown section names are
skipped via the table (§8 rule 3), and new keys/sections do **not**
bump `version` (§8 rule 6). A v1 QUF reader — including the RTL loader
profile — would load the fabric below and skip everything
lane-shaped. Byte-level statements below are byte-level only where
QUF-SPEC pins them.

**Fixed header (SPEC, QUF-SPEC §3):** 16 bytes — magic
`51 55 46 00` (`'Q','U','F',0x00`), `version` u32 = 1, `endian` u32 =
1, `kv_count` u32.

**Header KV (SPEC encoding, §4: u32 name_len, name bytes, u32
GGUF-numbered value type, value).** The standard keys, in the order
writers emit them, for the worked example of §3 (3 cells, 2 edges,
tpw = 6):

| key | type | value (example) | status |
|---|---|---|---|
| `quf.version` | string (8) | producer id, e.g. `lanesheet-emit 0.1 (spike)` | SPEC key |
| `cell_count` | u32 (4) | 3 | SPEC, required with `dials` |
| `edge_count` | u32 (4) | 2 | SPEC |
| `route_count` | u32 (4) | 3 | SPEC |
| `edge.k` | u32 (4) | 8 | SPEC (1..16) |
| `tick_period` | u32 (4) | 64 (= 2^6, from the ticks section) | SPEC |
| `quant.dials` | string (8) | `Q1.15` | SPEC |
| `quant.edges` | string (8) | `Q1.15` | SPEC |
| `quant.routing` | string (8) | `u8` | SPEC |
| `align` | u32 (4) | 32 | SPEC (default) |
| `lanesheet.version` | string (8) | dialect version of the lane-sheet format | SKETCH key |
| `lanesheet.name` | string (8) | `triage-mini` | SKETCH key |
| `lanesheet.source_sha256` | string (8) | sha256 of the source sheet (which lives in git beside the container) | SKETCH key |
| `lane_count` | u32 (4) | number of lanes in the `lanes` section | SKETCH key |
| `step_count` | u32 (4) | number of steps in the `steps` section | SKETCH key |

Present counts are assertions, not hints (§5a R8): a writer that
emits `cell_count` wrong has produced a rejectable file, not a hint
with typos. A lane-sheet writer inherits the whole §5a discipline —
honest counts, zero padding (R11), the 4 GiB ceiling (R5) —
unchanged.

**Sections (table format SPEC, §5: name, kind u32, offset u64, size
u64; offsets ascending, `align`-multiples, non-overlapping, zero
padding).** The four standard sections carry the fabric image; their
size formulas are pinned (SPEC, §6) and are computed here for the
example:

| section | content | size formula (SPEC) | example |
|---|---|---|---|
| `dials` | per-cell dial register image, 16 u16 per cell, row-major | `cell_count × 32` | 96 B |
| `edges` | Hebbian edge records: src, dst, mode, slot, base, wh, age, K bucket bytes | `edge_count × (12 + K)` | 2 × 20 = 40 B |
| `routing` | {dst u8, via u8} next-hop records | `route_count × 2` | 6 B |
| `ticks` | u32 tpw + per-cell u32 phase | `4 + 4 × cell_count` | 16 B |
| `lanes` | **SKETCH.** Per lane: name (len-prefixed), cell count, that many u64 cell ids. This is where row 1's lost lanehood is archived — metadata, honestly labelled, not state. | from the records | — |
| `extern` | **SKETCH.** Per external cell: u64 cell id, u8 port kind (spike-local: 1 = prompt, 2 = tool), binding name (len-prefixed). Names only — endpoints, prompt text, and credentials never enter the container; the port is a black box (QUIL §1.5) and its binding lives in the sheet layer. | from the records | — |
| `steps` | **SKETCH.** Per step: u32 step index, u32 first_tick, u32 op_count. The schedule only — the op stream itself is reproducible from the source sheet plus the §1 mapping (the §3 emitter is the existence proof), so the container carries the schedule, not a second copy of the program. | `step_count × 12` | — |

Two deliberate non-choices, stated so nobody has to guess:

- **The source sheet is referenced, not carried.** A `sheet` cargo
  section would be legal under §8 (readers skip it), but the house's
  own §5a rationale cuts against files carrying payloads their
  loaders disclaim (R11's side-channel argument), and the
  polyformalism's habit is agreement by hash, not by embedding
  (DOSSIER §2). The sheet lives in git; the container names its hash.
- **The dials section carries only the quantized shadow.** That is
  not a limitation of this sketch; it is QUF's doctrine
  (quantized-by-default, the writer refuses floats, §4). Prompt text,
  tool payloads, and conversation history are in the sheet layer or
  nowhere — §1 rows 2 and 5 are the reason this section can be
  honest about it.

---

## 3. The emitter — BUILT, small, and honest about its size

**Status: BUILT and run in this spike.** `lanesheet_emit.py` (Python,
stdlib only) takes a trivial workflow description (JSON) and emits
the opcode sequence §1's mapping predicts: a LOAD program (BIND/LINK,
with the fabric's answer annotations), a RUN program (EFFECT/TICK/
VIEW plus explicitly-marked off-fabric PORT lines), and the canonical
hash of the bound fabric image. It is a compiler-shaped *listing
generator* — it does not simulate execution, lower to Verilog, or
write QUF bytes, and it does not pretend to.

Why even this much is honest: the mapping's load-time half is fully
pinned by spec (BIND/LINK semantics; the Charter's canonical
serialization), so the emitter's hash half can be checked against the
shelf's own contract vector rather than against itself:

```
$ python3 lanesheet_emit.py --selftest
selftest: contract cell hash 0xe435d91d6d92a1d8 (expect 0xe435d91d6d92a1d8) -- PASS
```

(The contract cell — id 1, dials [1..16], neighbours [2,3,4] — and
its hash are the Charter's, carried on both HDL repos' badges;
DOSSIER §1a/§2.)

The emitter also enforces §1's hardest seam instead of waving at it:
a workflow cell carrying text payload (`prompt_text`, `template`,
`code`, …) is **refused**, and floats are refused anywhere in the
input (the QUF writer's own doctrine):

```
$ python3 lanesheet_emit.py bad-sheet.json
EMIT-REFUSED: cell 'x' carries 'prompt_text': text cannot enter the
fabric (no string type in QUF state; QUIL S1.5 quarantines content
off-fabric). Name the cell; keep its text in the sheet layer.
```

### Worked example

`triage-mini.json`: a value cell (`inbox`, with a THRESH dial), a
prompt cell (`summarize`), a tool cell (`post_digest`), two edges,
and a three-event run (a reading arrives; the prompt port answers
with an integer shadow; the tool port completes). The emitted listing
— the mapping of §1, executed:

```
; lanesheet_emit spike -- workflow 'triage-mini'
; LOAD program (mapping: DOWNWARD.md S1). Response annotations are the
; fabric's own discipline (quilt-verilog README, 5+1 table): BIND/LINK/VIEW
; are answered ACK/NAK; EFFECT and TICK carry no response promise.

; --- LOAD: bind cells ---
BIND   cell 1   ; first bind sets cell_id (value cell 'inbox')  -> ACK
BIND   cell 1   dial[5] THRESH <- 12000  -> ACK
BIND   cell 2   ; first bind sets cell_id (prompt cell 'summarize')  -> ACK
BIND   cell 2   dial[5] THRESH <- 8000  -> ACK
EXTERN cell 2   'summarize' ; NOT AN OPCODE -- a black-box port (QUIL propose / fabric Law 4).
       ; the cell's text and behaviour stay in the sheet layer; only an integer
       ; shadow and the ACK/NAK discipline cross into the fabric.
BIND   cell 3   ; first bind sets cell_id (tool cell 'post_digest')  -> ACK
EXTERN cell 3   'post_digest' ; NOT AN OPCODE -- a black-box port (QUIL propose / fabric Law 4).
       ; the cell's text and behaviour stay in the sheet layer; only an integer
       ; shadow and the ACK/NAK discipline cross into the fabric.

; --- LOAD: link edges (wiring as data) ---
LINK   cell 1   slot 0 := {peer 2, base 16384}  -> ACK
LINK   cell 2   slot 0 := {peer 3, base 16384}  -> ACK

; --- RUN: one pass, per the time mapping (DOWNWARD.md S1b) ---
; A workflow step = a tick window: ops issued and answered, propagation at
; one edge per TICK, the step commits at a tick boundary (super-step shape).
; STEP 1
EFFECT cell 1   src PORT dat 42  ; ingress flit (Law 4 generic IO contract).
       ; EFFECT is not answered; an unbound src is dropped silently
       ; (README), so the sheet's loader binds the port as the src of record.
TICK   ; decay sweep, leak, fire test on cell 1: if act >= THRESH and REFR = 0,
       ; fanout EFFECT -> cell 2 (one-tick edge delay: the step's effect
       ; is visible downstream only from this boundary)
; STEP 2
PORT-IN cell 2   ; NOT AN OPCODE -- the prompt port 'summarize' answers: integer shadow dat 23144,
       ; closed by ACK (a refusal / timeout is NAK and the step aborts). The wait
       ; happened off-fabric, between tick windows; the fabric never waits.
TICK   ; fanout from cell 2 to cell 3 at this boundary
; STEP 3
PORT-IN cell 3   ; NOT AN OPCODE -- the tool port 'post_digest' answers: completion only, no payload word,
       ; closed by ACK (a refusal / timeout is NAK and the step aborts). The wait
       ; happened off-fabric, between tick windows; the fabric never waits.
VIEW   cell 3   ; read act / wsum(edges) / a dial -- response flit carries the value  -> ACK

; --- Bound fabric image (post-LOAD, pre-run) ---
; cell 1   canonical hash 0x7dfe8368e40da141
; cell 2   canonical hash 0x4c10052d26fa9835
; cell 3   canonical hash 0x6d21ffca1d2ae306
; fabric hash (spike convention: FNV-1a over cells concatenated in ascending
; id order; the Charter pins the per-cell bytes, not this composition)
; = 0xa7267a0a56b3e07a
```

Read the listing the way the mapping intends: the opcodes are the
minority of the lines. The annotations — where the fabric answers,
where it is silent, where the workflow's real life (text, waiting)
happens off-fabric between tick windows — are the mapping's actual
content. A lowering that emitted only the opcodes would be lying by
omission about most of what a workflow is.

Files: `lanesheet_emit.py`, `triage-mini.json`, `triage-mini.ops.txt`
(the captured run above), all in `~/workspace/lane-sheets-build-spike/`.

---

## 4. What QUIL would have to be

QUIL, as the shelf designed it (`AI-Writings/docs/QUIL-HLS-RFC.md`,
2026-09-04; "design decided; compiler not yet built"), is a language
whose grammar cannot express nondeterminism — cells and `int<PW>` as
the only state and type, `tick` as the only writer, views as pure
functions of the journal prefix, `propose` quarantined to black-box
ports that may suggest but never gate — so that determinism is a
*lowering artifact*, and its acceptance gate is NQ-C3: one
hand-lowered circuit, bit-exact, that the language must reproduce by
construction or fail honestly. Restated for workflows, a QUIL for lane
sheets would have to be the same discipline aimed one level up: a
sheet language in which a workflow's *control* semantics are total
and replayable — every op answered (the §1a discipline made
syntactic, so an unanswered tool call is a parse error, not a hung
run), every step a tick window with a named commit boundary, every
external thing a `propose`-shaped port whose text and timing never
enter the deterministic region — and whose lowering emits, alongside
the fabric image of §2, the one artefact this spike could only
annotate by hand: the proof-shaped listing in which every line that
is *not* an opcode is labelled as such, so that what the fabric
guarantees and what the sheet merely hopes are never printed in the
same typeface. NQ-C3 was that compiler's falsifier on the hardware
side; its workflow twin would be a small LangGraph-shaped sheet —
value, prompt, tool, one branch, one join — lowered, run against the
framework itself, and required to agree step-for-step and
hash-for-hash, with any divergence booked as a scar rather than
tuned away. Until a builder lane picks it up, this note and its
emitter are the survey stakes for that compiler: the mapping, the
container, the +1 ruling, and the two clocks, all marked where they
are spec, where they are sketch, and where they stop.

---

*DOWNWARD — SuperInstance lane-sheets spike. Design note; the only
built artefact is `lanesheet_emit.py` and its captured output. No
personal names; the shelf is cited by repo path throughout.*
