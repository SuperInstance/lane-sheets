# STUDY DOSSIER — The SuperInstance Polyformalism Shelf

*Read-only study, 2026-10-22. Sources: GitHub API via the Oracle gh route (SuperInstance org), the local corpus catalog at `~/workspace/superinstance-profile/` (CATALOG.md + INDEXES/, generated 2026-10-21, 5,297 repos), targeted AI-Writings file reads, and the local `~/workspace/beam-quilt`. Nothing built, nothing edited outside this file.*

*Evidence discipline: **verified** = a receipt in the artefact itself (test output, proof file, conformance run) that a reader can re-run; **described** = stated in a README/description/catalog, not independently receipted here; **absent** = looked for, not found.*

---

## 1. The substrate table

There are **two distinct conformance objects** on this shelf, and most confusion dissolves once they are separated:

- **Contract A — the cell-fabric contract** (the Charter's): a cell is 16 signed Q1.15 dials + a 64-bit id + a neighbor list; state is canonically serialized and hashed with FNV-1a 64. Byte-exactness is claimed — and receipted — *for this narrow contract only*.
- **Contract B — the VM contract**: the richer 5-opcode VM (effects with inverses, scheduler, subscribers, log) implemented in five languages and run against a shared 36-program corpus. Its own conformance repo documents **divergence**, not exactness (see the last row-block).

### 1a. Contract A ports — the cell-fabric polyformalism

The root document is `SuperInstance/quilt-claude-charts` → `QUILT_CHARTER.md`: *"A cell is a typed unit of state. A fabric is a graph of cells. A cell-fabric runtime is a function from context to value, advanced by a clock. The same model, expressed in 12+ languages, byte-exact compatible, canonically serialized, hash-verified."* Its language table (test counts as printed there):

| Language | Repo(s) | Implements | Byte-exact claim | Receipts as stated | Dates |
|---|---|---|---|---|---|
| Python 3 | quilt-cowboy; also quilt-foundation (VM, §1b) | cell fabric (charter reference telling) | test-cell hash | 7/7 tests (charter) | quilt-foundation 2026-08-25 |
| C99 | quilt-c ("bare metal, the mathematical core") | cell fabric | test-cell hash | "manual" (charter) — **no automated count stated** | — |
| Rust | quilt-rust, quilt-rust-vibe | cell-fabric runtime, std-only | FNV-1a hash | 6/6 (charter) | 2026-09-01–04 era |
| Go | quilt-go | cell-fabric runtime, stdlib only | FNV-1a hash | 7/7 (charter) | 2026-09-07 |
| Zig | quilt-zig | cell-fabric runtime, stdlib only | FNV-1a hash | 7/7 (charter) | — |
| JavaScript | quilt-cell (npm `@superinstance/quilt-cell`); quilt-live-canon | the cell as a library: 16-dial Q1.15 vectors, `bind`/`tick`, state hash | "byte-exact with Python/C/Rust/Verilog/VHDL" | self-test checks its hash against the Python implementation's byte-for-byte (in-repo test) | quilt-cell 2026-09-04 |
| TypeScript | live-canon-npm | cell fabric (streaming level) | test-cell hash | 5/5 (charter) | — |
| **Verilog-2005** | **quilt-verilog** | full fabric RTL: cells, Hebbian edges, tick (§3) | test-cell hash badge `0xe435d91d…` | **23/23 RTL benches, 34/34 behavioral sim, 6/6 formal proofs, real iCE40/ECP5 bitstreams** (§3) | created 2026-08-30, pushed 2026-10-01 |
| **VHDL-2008** | **quf-vhdl** | QUF port of the fabric runtime | "byte-exact with the Verilog reference" | "manual" (its own table) — **no automated count stated** | 2026-09-03 |
| Mojo | quilt-mojo ("cells as types") | reactive level of the charter | hash ✓ claimed | "ref" — **reference only, unreceipted** | 2026-08-20 |
| Julia | quilt-julia; QuiltEgg.jl; QuiltCanary.jl ("polyformalism canary") | cell / canary | — | described only | 2026-08-20 / 2026-09-30 |
| J | quilt-j | cell-fabric runtime, point-free | FNV-1a hash | described ("5-sigma polyformalism port") | 2026-09-08 |
| Forth | quilt-forth | cell-fabric runtime, stack-based | — | described ("5-sigma") | per catalog |
| Lua | quilt-lua | cell-fabric runtime, metatables | — | described ("5-sigma") | per catalog |
| Haskell | quilt-haskell | cell-fabric runtime, lazy | — | described ("5-sigma"); see also §1b | per catalog |
| C++ | quilt-cpp | "templates reveal the cell kind lattice" | — | described | 2026-08-20 |
| Chapel | quilt-chapel | distributed cell evaluation | — | described | 2026-08-20 |
| Metal | quilt-metal | GPU-evaluated cells | — | described | 2026-08-20 |
| COBOL | quilt-cobol | "the cell model is older than spreadsheets" | — | described | 2026-08-20 |
| Tutor (PLATO) | quilt-tutor | Quilt in Tutor | — | described | 2026-08-20 |
| Rust `no_std` (embedded) | quilt-timesfm-rust (the `time.cell` kind); quilt-esp32 (reactive runtime, ~3KB flash, sensors as cells) | cell kinds / fabric on microcontrollers | — | quilt-timesfm-rust calls itself the "**3rd polyformalism port**" (description) | 2026-09-01 / 2026-08-19 |
| Game engines | quilt-engine-ports | the 5+1 opcodes mapped to Godot, Unity, Unreal — cells as nodes, TICK as the frame, sheets as JSON | conformance *specified* | "Godot reference scaffold runs; Unity/Unreal specified" (description) | 2026-08-28 |

Cross-checks from the local catalog (descriptions, not re-run here): **quilt-arch** claims "Q32 bit-exact, JS==Python 0/10000 mismatches (cross-substrate)"; **xruntime-conformance** claims "the cell convention evaluated in two runtimes that never shared source: 23/23 per-cell digests agree." Both are the right *shape* of receipt for Contract A; both are **described, not verified** in this study.

**Counting honestly:** the charter headline says "12+ languages." Its own table lists 10 languages + 2 package forms (npm/PyPI). The org search finds well more than 12 language expressions if the described-only ports (Julia, J, Forth, Lua, C++, Chapel, Metal, COBOL, Tutor) are counted. The *receipted* core — automated test counts printed in the charter — is five: Python 7/7, Rust 6/6, Go 7/7, Zig 7/7, TypeScript 5/5, plus JavaScript's cross-check against Python. C, Verilog, VHDL are "manual" in that table (Verilog's real receipts live in its own repo, §3, and are far stronger than "manual" suggests).

### 1b. Contract B — the 5-opcode VM family and its honest ledger

| Repo | Language | What it is | Status per `quilt-conformance` (2026-08-25, updated 2026-08-29) |
|---|---|---|---|
| quilt-vm-typescript | TypeScript (Cordis-native) | the 5-opcode VM | 6/6 upstream tests; **0/36 corpus self-failures — "reference implementation in practice"** |
| quilt-vm-rust | Rust | the 5-opcode VM | `cargo test` **fails to compile** (BUG-1); 4 corpus self-failures; panics instead of catchable errors |
| quilt-vm-c | C | the 5-opcode VM ("closest to the metal") | 6/6 upstream; 6 corpus failures (`qvm_bind` appends instead of replacing) |
| quilt-vm-haskell | Haskell | the 5-opcode VM | does not build unpatched (patch in-repo); 3 corpus failures |
| (WASM pkg) | WASM | a shallower VM: no effect application, scheduler, subscribers, dispose, log | 51 divergences across 26 tests |
| **quilt-conformance** | — | shared 36-program corpus (JSON op sequences), 5-way diff, bug ledger, benchmarks | **5-way verdict: 7 MATCH / 29 DIVERGE**; 11 bugs filed in `results/BUGS.md`; gold bench (20 runs): C 0.70 ms, Rust 0.88, Haskell 1.49, TypeScript 20.4 |

The divergence is *published by the house itself*, with minimal repros — that is a receipt about honesty, and the correct reading is: **the narrow Contract A is the portable truth; the richer VM semantics had not converged across ports as of late August 2026.** Related layer work, described only: **quilt-types** ("Layer 2 of the polyformalism — the 5 opcodes as type-driven cell-graphs; 16 tests passing; JSON serializer + query API"), **quilt-polyformalism-dsl** (the 5 opcodes as language-level syntax in Python/Rust/Haskell), **quilt-gc** ("Layer 5 — a runtime/GC that uses the 5 opcodes as the garbage-collection boundary"), **quilt-substrate-meta** ("5 opcodes, mathematically derived, with a prover, a synthesizer, and 36 passing tests").

A second, older substrate line coexists and should not be conflated with the 5-opcode family: **quilt-substrate** (Python, 2026-08-24) implements **11-primitive cells** (tensor encoding, Schrödinger pattern, fog-of-war decay, convoy consensus, witness log), and **substrate-foundation** describes "11 opcodes + drift + canary." Different primitive count, different lineage.

---

## 2. QUF and the calculus

**Two encodings, two jobs — the corpus keeps them distinct:**

1. **The canonical per-cell serialization** (Charter §1) is the *hash input*: `type(1) || id(8 LE) || dials(32 LE) || neighbors(8·N LE)` = 41 + 8N bytes per cell (type `0x01` value cell, `0x02` formula cell as extension point). The state hash is FNV-1a 64 (offset `0xcbf29ce484222325`, prime `0x100000001b3`) over that byte sequence. The contract cell — id=1, dials=[1..16], neighbors=[2,3,4] — hashes to **`0xe435d91d6d92a1d8`**, the value on the badges of both HDL repos. The charter's doctrine in one line: *"The hash is the type system. The hash is the runtime check. The hash is the only truth that survives portability."*
2. **QUF — the Quilt Universal Format** (`quilt-verilog/docs/QUF-SPEC.md`, v1) is the *whole-fabric container*: "the GGUF of cellular silicon." A flat, little-endian binary file holding complete fabric state — dials, edges (with Hebbian walk counts), routing, and the tick schedule — that "loads into simulation (testbench), a soft core, or a real FPGA, identically." Layout deliberately mirrors GGUF: magic `'Q','U','F',0x00`, u32 version (=1), u32 endian (=1, little), a header of KV pairs using **GGUF's value-type numbering** (unknown keys are skipped, never fatal), then a section table (name, kind, offset u64, size u64; offsets aligned, default 32) over sections `dials / edges / routing / ticks`. Standard keys include `cell_count`, `edge_count`, `route_count`, `edge.k`, `tick_period`, and `quant.*` (dial format `Q1.15`). The reference writer **refuses to emit floats** ("quantized-by-default, no floats in fleet state"). Reference implementation `tools/quf.py` (stdlib-only Python); synthesizable consumer `rtl/q_uf_loader.v` (streaming parse of the v1 subset; unknown metadata skipped, never fatal).

**The calculus** is the 5+1 opcode model. The five are stable in every telling: **BIND** (set dials / bind a cell; idempotent), **LINK** (add an edge — in the RTL, "wiring as data": an edge slot := {peer, base weight}), **EFFECT** (propagate/train — in the RTL, a Hebbian train on the matched edge plus integration into activation), **VIEW** (read dials/activation — pure readout), **TICK** (advance the fabric — decay sweep, leak, fire test). **The "+1" is not stable across the corpus** — it is a different channel in different lineages:

- in quilt-verilog: **ACK/NAK**, the response channel (OP_ACK=5, OP_NAK=6) — "every bind/link/view … is answered — never left hanging";
- in quilt-engine-ports' telling: **FORGET**;
- in quilt-cell-router: **GHOST** appears in a BIND/LINK/GHOST/TICK engine.

Forgetting has its own format draft: `docs/QUF-FORGETTING-V1.md` proposes making forgetting a *format property* of QUF — sealed epoch archives (HMAC-SHA256 under a distinct archive key), demotion instead of destruction. **Status: draft, no RTL changes.**

**How state moves between substrates:** as bytes, never as behaviour. A fabric's complete state is exported to QUF (or hashed via the canonical serialization), and any other substrate loads/computes over the identical bytes; agreement between substrates is established by comparing hashes, not by trusting implementations. The Verilog repo's benches make this concrete: `tb_quf_loader` pins a 576-byte QUF file by SHA-256 with byte-exact round-trip; `tb_serfabric` proves "QUF serialized boot byte-exact (2 cells)" with serial and parallel egress streams cycle-locked. The charter's streaming level is the same idea at the top of the stack: cells as JSON, fabric as a state hash, opcodes as REST endpoints (the live canon worker).

---

## 3. The Verilog line specifically

`SuperInstance/quilt-verilog` (created 2026-08-30, default branch `master`, last push 2026-10-01) is the most heavily receipted artefact on the shelf. Its README states the position: *"The bottom layer of the quilt, in silicon logic… pure, generic Verilog-2005 (IEEE 1364-2005): no vendor primitives, no IP cores, no SystemVerilog, no floats. Every module is parameterized, fixed-point, and streaming."*

**What exists (verified-in-artefact: the repo carries the benches, proof files, and dated run records):**

- **RTL**: a cellular learning fabric — Hebbian edges, power-law forgetting, dial state, fabric-wide tick — executed by `q_cell_core` as a cooperative run-to-completion FSM, one interpreter per cell, events serialized as flits with ACK/NAK responses. The tick is non-deferrable: a pending tick suppresses ingress until serviced.
- **Simulation**: `make test` → **23/23 benches PASS** (suite emits its own machine-derived summary; README re-run dated 2026-09-03). Behavioral Python lane over the same QUF: `make sim` → **34/34 OK**.
- **Formal**: `make formal` → **6/6 SymbiYosys proofs PASS** (docs/FORMAL-PROOFS.md): (1) the flit slice is an ideal 2-deep FIFO; (2) **fabric conservation — the two-cell ledger conserves credit** (a PDR referee note records this closing *unbounded*, beyond k-induction); (3) the echo gate brackets every trace into its dyadic octave; (4) non-deferrable time — tick deadlines survive permanent ingress flood; (5) every op terminates and every op is answered; (6) the same FIFO contract proven unbounded. The proofs are load-bearing, not decorative: their first runs found **two real RTL defects** (a multi-driven register simulators accepted but Yosys rejected; a one-cycle ingress-drop hole under a pending tick), both fixed and regression-guarded.
- **Silicon**: open-tool flow only (Yosys / nextpnr / icepack from oss-cad-suite). iCE40 HX8K-CT256: 7,596/7,680 LC (98%), **44.43 MHz post-route**, 135,100-byte bitstream, tracked in-repo. Smallest device: UP5K, 1 cell, 80.1% LC, 16.78 MHz. ECP5 ladder: LFE5U-25F, 8 cells at **63.7 MHz**. `docs/SYNTHESIS-RESULTS.md` carries reproduce commands and corrects two earlier fmax numbers that had been quoted from post-placement estimates — provenance discipline inside the artefact.
- **Hostile inputs**: `corpus/mutants/` holds ~26 mutated QUF files (bad magic, truncations at six lengths, endian lies, kv-count lies, section-count extremes) — the format is tested against lying files, and the loader benches cover warm-start, corrupt-header fallback, and truncation fallback.

**Count strata, honestly:** the numbers grew and the documents preserve the layers — the AI-Writings research paper 66 (Aug 2026) records the flow being built (its own count notes: 18/18 benches, then 21/21 at commit `37e206f` in audit round 13/14, Sept 3), and the README's later stratum says 23/23. Quote the stratum, not a single "true" count.

**What's aspirational in this line:**

- **QUIL** (`AI-Writings/docs/QUIL-HLS-RFC.md`, 2026-09-04): a high-level-synthesis *pseudolanguage* for the quilt — `cell` / `int<PW>` / `tick` / `view` / `bind` / `link` / `propose` constructs that map 1:1 onto fabric concepts and lower to synthesizable Verilog. Its thesis: determinism as a *lowering artifact* — the grammar cannot express nondeterminism; the neural side (`propose`) is grammatically quarantined ("proposals, never gates"). Status, in its own header: **"design decided; compiler not yet built."** Implementation is assigned to land in quilt-verilog when a builder lane picks it up. The inverse direction — lifting — is present as a compiler *check*: trace-hash PW-invariance (simulate at two widths, require identical trace hash), not as a decompiler.
- **DPC++ note** (`AI-Writings/docs/QUILT-DPCPP-NOTE.md`, 2026-09-04): design note for compiling the same cell/tick/view/bind abstractions to SYCL kernels (GPU/FPGA via oneAPI) with the journal in device buffers. **Design note; implementation undecided.**
- The cosine/vMF readout of edge weights is mathematically defined but its dedicated RTL readout path is "reserved for v1" (README law 3) — VIEW of that kind NAKs today.

---

## 4. The sheet line

**The claim, in the corpus's own words.** `SuperInstance/quilt` (2026-08-17): *"A spreadsheet where every cell is a live, addressable capability. The grid is the runtime."* Its README expands: a cell is "a value, a formula, a listener, an API call, an AI call, a sensor, a router, a program, or a vector store"; a **sheet is a JSON document of cells with dependencies**; an engine evaluates the sheet reactively ("your entire system is a JSON document… there's nothing else"). Self-reported badges: 115 tests, 25 repos in the ecosystem (described, not re-run here). The charter's use-case #1 agrees on the origin: "Reactive spreadsheets — the original use case, the Quilt was designed for sheets."

**Addressing.** Cells address each other **by id inside the fabric** (BIND gives a cell its id; LINK names peers; VIEW/EFFECT name a target), and at the sheet level by cell reference in formulas — the spreadsheet-moment pattern of shells in a grid addressing each other by location, with the sheet as data (JSON/YAML) rather than as code. `quilt-agent` (2026-08-19) is the purest agent-interaction expression: **the agent is a sheet** — memory = value cells, tools = API cells, reasoning = a chain of program cells, goals = listener cells, conversation history = a growing value cell, the prompt = a formula that depends on the conversation. A worked research-agent sheet ships in its README as one YAML file.

**Bookkeeping inside the sheet.** `quilt-spreadsheet` (2026-09-23, runnable Python): cells as runnable programs with hooks, and "**double-entry bookkeeping** — every pull/push pair is recorded as a ledger pair (same UUID, same timestamp)"; per-cell color namespaces; backend porting across scales; distributed clocks with skew tolerance ("confidence rises with shared events").

**The git-shaped sheet.** `gitpp-sheet` (2026-10-17): *"A fold already IS a spreadsheet"* — state = the cells, setters = cell provenance, order = dependency order, conflicts = the audit trail — plus the one thing a fold lacks: per-cell confidence, propagated through the fold's decisions (Jev-scored claims about *relations* — "r2 outranks r7 for k0" — not about records). `synoptic-sheet` (2026-10-13): one real sheet, rows written by agents in order — "tasks propose and do, witnesses watch and sign, and an override settles a contested key. Nothing is ever deleted. The state at the bottom of the page is a fold of everything that was said — including the claims that lost."

**The external-thesis audit — part of the record, and it cuts both ways.** An inbound document titled "The Sheet is the Runtime" was audited claim-by-claim against live registries (`AI-Writings/docs/AUDIT-SHEET-IS-THE-RUNTIME.md`, 2026-09-03): roughly a third of its authority was fabricated or name-collided infrastructure, a third real names with stretched capabilities. The companion steelman (`STEELMAN-SHEET-IS-THE-RUNTIME.md`) keeps what survives *because the house already lives it*: layer collapse (QUF named as the doc's best idea already running as a shipping artefact), and the **two-tier law** — *"byte-exact fabric runs never route through LLM inference… neural cells allowed only in a trace-labeled tier, never in conformance paths"* — independently derived by an outsider, booked as the doctrine's strongest external validation. The steelman's honest ladder, verbatim in substance: browser tier exists (quilt-live), edge tier exists (quilt-rust), silicon tier exists as a *fixed cellular architecture*, and **"what doesn't exist: the lowering pass sheet→netlist. NQ-C3 is the first hand-lowered stone across that creek"** — NQ-C3 being a connectome-derived subgraph implemented independently in Python and Verilog, agreeing bit-exact across 100 ticks, synthesized to a 1,566-cell netlist. Hand-lowered, once, with receipts — not a compiler.

**Earlier sheet-shaped agent coordination** (pre-Quilt branding, from the catalog): `spreadsheet-cells` (2026-05-17, cell architecture with oscillator/RNG for multi-agent fleet coordination), `spreadsheet-engine` (2026-06-08, 7 cell types, A2A protocol), `Spreadsheet-ai` / `polln` (2026-03, agents deconstructed into spreadsheet tiles). The spreadsheet-as-agent-medium line is the oldest stratum on the shelf.

---

## 5. Closing map — the shelf against three reference points

### (a) The active log / active ledger anatomy

The two-active-items anatomy — (1) a perspectival **active log** of dated readings, no God's-eye view; (2) an **active ledger** of sends and receives whose *agreement* mints shared state — is not an analogy imposed on this shelf; it is already built on it, three times over:

- **`quilt-rooms`** (2026-10-08; local tree `~/workspace/quilt-rooms`) states it in almost the same words: ACTIVE-LOG.md is the intra-room log ("every internal event, sequenced, hash-chained" — one room's perspective, its own time), ACTIVE-LEDGER.md is the inter-room ledger ("agreed links with dual timestamps"). A send is recorded as **A:47 = B:23 = U:101** — A's sequence, B's sequence, and a *negotiated* universe time; a link stays pending until both sides converge. Its template scripts (say/send/receive/agree) are marked "tested end-to-end: send → receive → agree produces matching ledger entries in both rooms; disagreement detection works." That is the ledger-mints-shared-state mechanism as a working room protocol, including the fog: each room keeps its own time and its own log, and only the agreed links are shared.
- **The synoptic sheet** is the same anatomy rendered as one page: the log is the rows (append-only, losers preserved), the state is a fold of the log — no stored state anywhere, exactly the log-side of the anatomy with the fold standing where agreement would be checked.
- **In silicon**, the ledger is not a metaphor but a *proven invariant*: formal proof #2 in quilt-verilog is "the two-cell ledger conserves credit," closed unbounded by PDR; and `quilt-spreadsheet`'s double-entry pairs (same UUID, same timestamp on pull and push) are the ledger habit inside the sheet runtime.

Where the shelf is *thinner* than the anatomy: the anatomy's per-observer staleness/prediction layer (readings ageing, extrapolation from the wake) has only partial expressions here — quilt-substrate's "fog-of-war decay" (described) and quilt-spreadsheet's skew-tolerant clocks ("confidence rises with shared events"). The dated-reading tensor with a vector is **absent** as a named artefact in the substrate family surveyed.

### (b) BEAM-style process engines

`~/workspace/beam-quilt` is a design study (README + SPEC.md + nine short chapters + FOUNDATIONS.md), and it names the BEAM kinship itself: *"Like processes on the BEAM virtual machine, patches share no state; influence is only ever a proposal sent across a seam, and the receiver's own transition decides."* Its engine shape: the minimal unit is a **transmission** (state → algorithm → state; four endings: mutate, move, copy, project); a **patch** is anything honouring that contract standalone; between two patches sit **two judges** (sender-side and receiver-side Jev) with a deadband between go and no-go; coordination emerges at seams — "a quilt is what *emerges* when enough good patches exist — a consequence, never a blueprint." Supervision and receiver sovereignty are chapter 3's subject ("influence without relocation; sovereignty of the receiver; supervision").

Read against the Verilog fabric, the BEAM shape is visible one level down: each cell is a process-like unit with private state (dials), a mailbox discipline (flits, serialized per cell, run-to-completion FSM — the actor loop), message responses that are never left hanging (ACK/NAK, *proven*: "every op terminates and every op is answered"), and no shared memory — a cell can only be touched through the opcodes, i.e. by message. This is also where the negative-space-objects observation has its concrete footing *(interpretation, flagged as such)*: neither BEAM processes nor quilt cells are objects — no classes, no inheritance — yet **id + private state + named neighbours + a fixed message vocabulary** carves out object-shaped behaviour in the negative space. The cell is an object the way a BEAM process is: by addressability and encapsulation, not by type.

What's absent on the BEAM axis: no Erlang/Elixir implementation of the quilt cell model was found in the org search, and beam-quilt itself is a study, not a running engine — the *running* actor-shaped artefact is the RTL fabric and the sheet engines, not a BEAM runtime.

### (c) The lane-sheets thought

The thought: agent-workflow graphs as **sheet data**, one abstraction below LangGraph — the way HDL sits below C/Python — liftable into LangGraph or another framework the way a hardware description is synthesized or simulated at higher levels. Against the shelf, three of its four legs already exist as artefacts, and the fourth is a named, dated absence:

1. **The workflow-as-sheet-data leg exists.** quilt-agent expresses an entire agent — memory, tools, reasoning chain, goals, prompt — as one declarative sheet (YAML/JSON of typed cells). spreadsheet-engine and the 2026-03/05 spreadsheet line express multi-agent coordination the same way. A "lane sheet" would not be a new kind of object on this shelf; it would be a dialect of one that has existed since August.
2. **The below-frameworks leg exists, with receipts.** Contract A is precisely a framework-neutral description whose identity survives every lift: the same cell model in 12+ tellings, with the *hash* as the lift invariant. The polyformalism's own five levels (imperative / reactive / logic / streaming / itself) are a worked example of one description living at several abstraction heights without changing its truth condition.
3. **The git-native leg exists** in the neighbouring programme: gitpp-sheet shows a fold rendered as a spreadsheet with provenance and confidence; the synoptic sheet shows agent writes as rows with the state as their fold. Records-in-git, state-as-fold, conflicts preserved — the lane sheet's storage and audit shape is already demonstrated there.
4. **The compiler leg is the absent one — in both directions, and the corpus says so itself.** QUIL is the downward compiler (sheet-like language → Verilog) as a *decided design with no compiler built*; the steelman records that sheet→netlist lowering does not exist beyond one hand-lowered, bit-exact example (NQ-C3). The upward direction (sheet → a running framework's code, e.g. LangGraph Python) has **no artefact at all** in the surveyed corpus: lifts on this shelf are hand ports proven equal by hash, not generated code. What the shelf offers the lane-sheets design instead of a compiler is its *verification discipline*: pre-registered conformance (a corpus + a hash), the two-tier law (the deterministic sheet never routes through LLM inference; proposals from the neural side are data until verified), and the audit habit — the house audited an outsider's version of this exact thesis and kept only what receipted.

**One-line map:** the active log/ledger is the sheet's *semantics of agreement*, the BEAM shape is its *semantics of isolation*, the Verilog line is its *proof that the bottom level is real*, and the lane sheet would be the same object aimed at agent workflows — with the compiler between sheet and framework as the one genuinely unbuilt piece, exactly where QUIL sits unfinished on the hardware side.

---

*End of dossier. Companion artefacts cited inline by repo path; the local catalog cross-check is `~/workspace/superinstance-profile/INDEXES/LANGUAGE.md` (generated 2026-10-21) and `CATALOG.md` entries for quilt-verilog (line 4242), quf-vhdl (line 489), quilt-cell (line 33838).*
