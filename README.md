# Lane Sheets — SuperInstance

**Lane Sheets writes an agent workflow as one JSON sheet — lanes of
cells connected by piping only — so the same workflow can be read as a
spreadsheet, run by a reference interpreter, lifted to LangGraph code,
or hosted against a real model, with the deterministic paths agreeing
byte-for-byte.** For builders who want their agent workflows as
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
.venv/bin/pip install langgraph

.venv/bin/python run_conformance.py
# SUMMARY: 14/14 PASS   (interpreter vs golden vs lifted LangGraph,
#                        byte-for-byte, plus three named refusals)

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

- **The format (SPEC.md + SPEC-AMENDMENT.md).** Six cell kinds:
  `value`, `prompt`, `llm`, `tool`, `branch` (0.1) and `sheet` (0.2) —
  a cell whose interior is another sheet, bound only at its ports.
  Kinds are reduced from the nine of the SuperInstance `quilt` sheet
  runtime, whose agent-as-sheet mapping (`quilt-agent`) this format
  descends from; the lineage is cited construct by construct.
- **The interpreter and the lifter** (`lanesheet/`): a stdlib
  reference interpreter, and a lifter producing standalone LangGraph
  modules. Fourteen conformance fixtures: linear chains, branches, a
  tool feeding a prompt, two lanes joining, a sheet used once, the
  same sheet reused by two cells (the plugin shape), two-level
  nesting, and three refusals (cycle, listener kind, recursive sheet).
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
  QUF-NOTES.md. It is still not a compiler, and no HDL tooling has
  loaded these images — that claim is not made.

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

Lane sheets do **not** have: loops or cycles (refused), lazy
branching, stored run state or checkpointing, push cell kinds
(listeners, sensors), arbitrary code cells, parallel-scheduling
semantics, or predicates beyond equality and truthiness. The lifter
targets LangGraph only. The host binds one LLM provider (MiniMax)
and stub tools; no streaming, and failures surface as a named
`ProviderError` with no partial trace. The QUF images cover numeric
value cells, their edges, and sheet state — text and program cells
do not cross downward yet.

## Layout

- `SPEC.md`, `SPEC-AMENDMENT.md` — the format (0.1 + the `sheet` kind)
- `lanesheet/` — `runtime.py` (shared deterministic runtime, embedded
  verbatim into every lifted module), `common.py` (validation,
  canonical order, sheet resolution), `interpret.py`,
  `lift_langgraph.py`, `host.py` (binding layer)
- `fixtures/` — the conformance corpus: sheets + golden traces
- `examples/` — the live-host example sheet, bindings, captured trace
- `run_conformance.py`, `run_host_check.py` — the two checkers
- `HOST.md` — the binding layer and the two-tier law
- `downward/` — DOWNWARD.md (opcode mapping), `lanesheet_emit.py`
  (opcode listings), `quf_write.py` / `quf_read.py` /
  `run_quf_check.py` / QUF-NOTES.md (the QUF subset)
- `docs/SHELF-STUDY.md` — the survey of the SuperInstance substrate
  shelf (quilt in Verilog, VHDL, Rust, and a dozen more) this builds on
