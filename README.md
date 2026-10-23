# Lane Sheets — SuperInstance

**Lane Sheets writes an agent workflow as one JSON sheet — lanes of
cells connected by piping only — so the same workflow can be read as a
spreadsheet, run by a reference interpreter, or lifted to LangGraph
code, with all three agreeing byte-for-byte.** For builders who want
their agent workflows as portable data that outlives any one framework:
LangChain wraps LangGraph the way C wraps assembly; a lane sheet is the
layer one step below both, the way a hardware description sits below
the languages compiled from it. Run state is derived from the sheet,
never stored in it; cells touch only through named piping, never
through each other's interiors.

## The 30-second example (executed, not illustrative)

```bash
python3 -m venv .venv
.venv/bin/pip install langgraph

python3 -m lanesheet.interpret fixtures/linear-chain.sheet.json
.venv/bin/python -m lanesheet.lift_langgraph fixtures/linear-chain.sheet.json /tmp/linear.py
.venv/bin/python /tmp/linear.py        # prints the identical trace
```

The sheet (`fixtures/linear-chain.sheet.json`) is a value cell feeding
a prompt cell feeding an llm cell feeding a framing prompt. The
interpreter and the generated LangGraph module print the same
canonical trace — cell by cell: inputs, an inputs hash, and the output.
The trace is the conformance object: implementations agree by
producing identical traces, never by trusting each other.

Full suite — five positive fixtures (linear chain, two branches, a
tool feeding a prompt, two lanes joining) plus two negative fixtures
that must be refused by name:

```bash
.venv/bin/python run_conformance.py
# PASS branch-else (6 cells)
# PASS branch-on-value (6 cells)
# PASS linear-chain (4 cells)
# PASS tool-feeds-prompt (4 cells)
# PASS two-lanes-join (7 cells)
# PASS negative-cycle (refusal: CycleDetected)
# PASS negative-listener (refusal: UnsupportedCellKind)
# SUMMARY: 7/7 PASS
```

## The model in five minutes

- **Five cell kinds, deliberately.** `value`, `prompt`, `llm`, `tool`,
  `branch` — reduced from the nine kinds of the SuperInstance `quilt`
  sheet runtime, whose agent-as-sheet mapping (`quilt-agent`) this
  format descends from. `SPEC.md` cites the lineage construct by
  construct. Narrow on purpose: on the wider shelf, the narrow
  contracts are the ones that stayed portable.
- **Piping is the only interface.** A cell names its input ports and
  the cells they draw from. Nothing reads another cell's interior;
  what crosses the wire is all that exists between cells.
- **Branching is value selection**, spreadsheet-`IF()` style: both
  arms compute, the branch picks. Laziness and short-circuit are
  excluded by name, which is what lets a dataflow interpreter and a
  LangGraph scheduler produce identical traces.
- **Tools and LLMs are named, never bound.** A sheet carries a tool's
  name and argument ports; the host binds the name to a real tool.
  Sheets stay portable, network-free, and deterministic — the
  conformance suite runs entirely on stub providers.
- **Refusals are named and total.** A sheet the implementation cannot
  run exactly is refused with a specific error (`CycleDetected`,
  `UnsupportedCellKind`, `UnexpectedKey`, … — the full taxonomy is
  SPEC §9). Nothing is silently approximated.

## Honest limits (SPEC §8)

Lane Sheets 0.1 does **not** have: loops or cycles (refused), lazy
branching, sub-sheets, stored run state or checkpointing, push cell
kinds (listeners, sensors), arbitrary code cells, parallel-scheduling
semantics, or predicates beyond equality and truthiness. The lifter
targets LangGraph only. The downward direction — sheets toward the
quilt fabric's opcodes and the QUF container — is a mapped design
note with a small listing emitter (`downward/`), not a compiler: of
ten constructs, two map cleanly, six map with named losses, and two
(text payloads, general program cells) do not map at all yet.

## Layout

- `SPEC.md` — the lane-sheet 0.1 format, semantics, refusal taxonomy
- `lanesheet/` — `runtime.py` (shared deterministic runtime, embedded
  verbatim into every lifted module), `common.py` (validation,
  canonical order), `interpret.py` (reference interpreter, stdlib
  only), `lift_langgraph.py` (sheet → standalone LangGraph module)
- `fixtures/` — the conformance corpus: sheets + golden traces
- `run_conformance.py` — interpreter vs golden vs lifted, byte-for-byte
- `downward/` — the opcode/QUF mapping note and its emitter
- `docs/SHELF-STUDY.md` — the survey of the SuperInstance substrate
  shelf (quilt in Verilog, VHDL, Rust, and a dozen more) this builds on
