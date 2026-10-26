# Lane Sheets — SuperInstance

**Lane Sheets writes an agent workflow as one JSON sheet — lanes of
cells connected by piping only — so the same workflow can be read as a
spreadsheet, run by a reference interpreter, lifted to LangGraph or
LangChain code, or hosted against a real model, with the
deterministic paths agreeing byte-for-byte.** For builders who want their agent workflows as
portable data that outlives any one framework: LangChain wraps
LangGraph the way C wraps assembly; a lane sheet is the layer one step
below both, the way a hardware description sits below the languages
compiled from it. Run state is derived from the sheet, never stored in
it; cells touch only through named piping, never through each other's
interiors — and a cell can itself contain a whole sheet, opaque from
the rung above it.

## Run it (all commands executed, not illustrative)

```bash
python3 -m venv .venv
.venv/bin/pip install langgraph langchain-core

.venv/bin/python run_conformance.py
# SUMMARY: 27/27 PASS            (interpreter vs golden vs LangGraph)
# LANGCHAIN SUMMARY: 27/27 PASS  (the same corpus lifted to LangChain)

python3 downward/run_quf_check.py
# SUMMARY: 45/45 PASS   (QUF writer/reader for the clean subset:
#                        real bytes, round-trip, hash agreement)

python3 run_host_check.py examples/live-minimax.trace.jsonl examples/live-minimax.sheet.json
# HOST CHECK PASS       (structural validation of a real MiniMax run)
```

The 30-second shape of it:

```bash
python3 -m lanesheet.interpret fixtures/linear-chain.sheet.json
.venv/bin/python -m lanesheet.lift_langgraph fixtures/linear-chain.sheet.json /tmp/linear.py
.venv/bin/python /tmp/linear.py        # prints the identical trace
```

The trace is the conformance object: implementations agree by
producing identical traces, never by trusting each other.

## What's here

- **The format (SPEC.md + SPEC-AMENDMENT.md + SPEC-AMENDMENT-0.3.md).**
  Six cell kinds: `value`, `prompt`, `llm`, `tool`, `branch` (0.1) and
  `sheet` (0.2) — a cell whose interior is another sheet, bound only
  at its ports — and, since 0.3, a mode of the `sheet` cell: `each`,
  the interior applied once per element of a piped list, results
  collected in element order. Kinds are reduced from the nine of the
  SuperInstance `quilt` sheet runtime, whose agent-as-sheet mapping
  (`quilt-agent`) this format descends from; the lineage is cited
  construct by construct.
- **The interpreter and the lifter** (`lanesheet/`): a stdlib
  reference interpreter, and a lifter producing standalone LangGraph
  modules. Twenty-seven conformance fixtures: linear chains, branches,
  a tool feeding a prompt, two lanes joining, a sheet used once, the
  same sheet reused by two cells (the plugin shape), two-level
  nesting, iteration over three elements and over none, iteration
  inside a sheet and over interiors that themselves nest, a fan-out
  at the 100-element cap — and eight refusals (cycle, listener kind,
  recursive sheet, and the five `each` refusals).
- **The host (HOST.md).** A binding layer: `llm`/`tool` names in a
  sheet are bound by host config to real providers — MiniMax first.
  Live runs emit the same canonical trace behind a header that names
  the run live and the providers behind it; `run_host_check.py`
  validates a live trace structurally (hashes, order, value flow) —
  never byte-equality, because live output is nondeterministic. The
  two tiers never mix: conformance goldens are stub-only, and a live
  trace can never be mistaken for one.
- **The downward leg (`downward/`).** DOWNWARD.md maps ten workflow
  constructs onto the quilt fabric's opcodes (BIND/LINK/EFFECT/VIEW/
  TICK, and an argued ACK/NAK as the +1): 2 map cleanly, 6 with named
  losses, 2 not at all yet. For the clean subset there is now a real
  QUF writer and reader: actual container bytes per the QUF spec,
  round-trip reconstruction, and agreement by the fabric's canonical
  hash — 45 checks, including the spec's own published golden vector.
  Every byte the spec leaves open is decided and named in
  QUF-NOTES.md. It is still not a compiler — but the images are no
  longer merely loadable-shaped: `downward/FALSIFIER.md` records the
  quilt-verilog fabric's own RTL loader consuming one in Icarus
  Verilog simulation and the `quf_boot` testbench releasing the
  fabric from it (state RUN, dial row live). One blocker was found
  and isolated on the way: the spec's crc32 digest scope is
  underdetermined (QUF-NOTES **D9**) — the Python tooling digests
  all sections, the RTL loader only its four payload sections — so
  the writer grew a `--no-crc32` flag (the digest is opt-in per
  §12.2) and `triage-clean-nocrc.quf` is the image that boots.
  Simulation, not silicon. And behaviour has now been probed too
  (`downward/BEHAVIOUR.md`): driving the booted fabric through the
  mapped op sequence, its state **agrees at the bind layer** —
  dials byte-exact, canonical hash identical — and **diverges at
  the run layer in five named places**: an unpaired inject is
  silently dropped by the fabric, a directed edge costs two LINKs,
  a THRESH=0 sink oscillates and trains its own upstream synapse,
  metabolic decay at the image's dial values erases an activation
  in one tick, and the sheet's numeric regime never reaches the
  fabric's threshold. A compensation run shows which pins repair
  most of it; the seven-point list is what a real QUIL must do.
- **Sheets as git.pp records (`gitpp/`).** A converter pair plus a
  minimal fold port proves the round trip: sheet → records in the
  `.gitpp/records` layout → reconstruction *by the fold alone*
  (arrival order shuffled, state identical) → interpreter trace
  byte-identical to the golden. Conflict behaviour is executed, not
  argued: an override record wins a cell's definition, a descendant
  redefinition dominates its ancestor, an equal-class sibling loses
  and is named. Installing a plugin sheet is landing its records;
  uninstall is honestly not a fold operation yet (GITPP-SPIKE.md).
  The live proof exists too (`gitpp/DOGFOOD.md`): the public repo
  `patchwork-quilt/gitpp-dogfood-sheet` carries the sheet-reused
  records, and the released `gitpp-action` derived them in real
  GitHub CI — its state agreeing with the spike's independent
  local fold on all 20 keys, zero divergences.

## The model in five minutes

- **Piping is the only interface.** A cell names its input ports and
  the cells they draw from. Nothing reads another cell's interior;
  what crosses the wire is all that exists between cells. A `sheet`
  cell's interior is a whole run of the same paradigm one rung down —
  the outer sheet sees only what the cell's ports carry.
- **Branching is value selection**, spreadsheet-`IF()` style: both
  arms compute, the branch picks. Laziness is excluded by name, which
  is what lets a dataflow interpreter and a LangGraph scheduler
  produce identical traces.
- **Bindings are per invocation site.** Two cells invoking the same
  inner sheet with different bound values are two invocations, not
  one shared interior — parameters are interior `value` cells, and
  only those can be bound from outside. You cannot override a
  computation through a port.
- **Refusals are named and total.** A sheet that cannot run exactly
  is refused with a specific error (`CycleDetected`,
  `RecursiveSheetRef`, `BindTargetNotValue`, `UnexpectedKey`, … —
  SPEC §9 plus the amendment's taxonomy). Nothing is silently
  approximated, including in the QUF writer, which excludes
  non-clean constructs with named reasons in a sidecar manifest.

## Honest limits

Lane sheets do **not** have: general loops or cycles (refused) —
iteration is exactly the `each` mode, a pre-existing list mapped
through one interior sheet, capped at 100 elements per cell — lazy
branching, stored run state or checkpointing, push cell kinds
(listeners, sensors), arbitrary code cells, parallel-scheduling
semantics, or predicates beyond equality and truthiness. The lifters
target LangGraph and LangChain (LCEL, langchain-core only). The host binds one LLM provider (MiniMax)
and stub tools; no streaming, and failures surface as a named
`ProviderError` with no partial trace. The QUF images cover numeric
value cells, their edges, and sheet state — text and program cells
do not cross downward yet.

## Layout

- `SPEC.md`, `SPEC-AMENDMENT.md`, `SPEC-AMENDMENT-0.3.md` — the
  format (0.1 + the `sheet` kind + the `each` mode)
- `lanesheet/` — `runtime.py` (shared deterministic runtime, embedded
  verbatim into every lifted module), `common.py` (validation,
  canonical order, sheet resolution), `interpret.py`,
  `lift_langgraph.py`, `lift_langchain.py` (the second lift target —
  mapping and verdict in LANGCHAIN.md), `host.py` (binding layer)
- `fixtures/` — the conformance corpus: sheets + golden traces
- `examples/` — the live-host example sheet, bindings, captured trace
- `run_conformance.py`, `run_host_check.py` — the two checkers
- `HOST.md` — the binding layer and the two-tier law
- `downward/` — DOWNWARD.md (opcode mapping), `lanesheet_emit.py`
  (opcode listings), `quf_write.py` / `quf_read.py` /
  `run_quf_check.py` / QUF-NOTES.md (the QUF subset), FALSIFIER.md
  (the RTL load record), `hdl/` (the variant testbenches)
- `gitpp/` — GITPP-SPIKE.md, `sheet_to_records.py`,
  `records_to_sheet.py`, `fold.py`, `run_spike_check.py`
- `docs/SHELF-STUDY.md` — the survey of the SuperInstance substrate
  shelf (quilt in Verilog, VHDL, Rust, and a dozen more) this builds on
