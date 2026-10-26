# The LangChain lift — SuperInstance lane-sheets

`lanesheet/lift_langchain.py` is the second upward target for a lane
sheet (the first is `lift_langgraph.py`). It generates a standalone
Python module built from **LangChain runnables — langchain-core
1.7.0, the LCEL core only, not the full `langchain` package** — that
prints the sheet's canonical execution trace, byte-identical to the
reference interpreter and to the LangGraph lift. The generated
module embeds `lanesheet/runtime.py` verbatim, exactly as the
LangGraph lifter does, and imports nothing beyond the standard
library (via the embedded runtime) and `langchain_core.runnables`
— verified by running a generated module in an environment with
langchain-core installed and langgraph absent.

## Why the chain looks different from the graph

LangGraph's model is isomorphic to a sheet's: a DAG of nodes, edges
for piping, subgraphs for sub-sheets. LCEL's model is a **pipeline**:
one value flowing through composed stages. A sheet therefore lifts
to LangChain as its *canonical linearization* (SPEC section 6): the
flowing value is the sheet state — `{"values": {...},
"trace_lines": [...]}` — and each cell is one stage of a
`RunnableSequence`, in canonical order. The trace is the judge: the
linearization is execution-equal to the DAG, or the bytes say
otherwise.

## The mapping, construct by construct

- **`value` / `prompt` / `llm` / `tool` cell → one `RunnableLambda`
  stage** over the state dict. The stage body calls the embedded
  runtime's own functions (`render_template`, `llm_complete`,
  `call_tool`, the value constant) — the same bodies the LangGraph
  nodes call. LCEL contributes sequencing and composition; the
  runtime contributes cell semantics. The division of labour is the
  LangGraph lift's, one framework over.
- **`branch` cell → `RunnableBranch`.** The apparent mismatch is
  laziness: LCEL branches are control flow and evaluate only the
  selected arm, while a lane sheet evaluates everything eagerly.
  It dissolves on inspection — a branch cell's arms are not
  computations, they are *upstream cells*, already computed by
  their own stages before the branch stage runs. What remains at
  the branch stage is pure selection, which is exactly what
  `RunnableBranch` dispatches: the condition runnable applies
  `runtime.select_branch`'s own rule (canonical-JSON equality for
  `equals`, false/null falsiness otherwise) to sentinel arms, and
  each arm runnable appends the trace line with its value
  selected. Laziness skips nothing, because there is nothing left
  to skip.
- **A multi-source cell (a join) → an ordinary sequence stage.**
  `RunnableParallel` is deliberately *not* used, and the reason is
  semantic, not convenience: a parallel composition fans one input
  snapshot into independent branches and returns a keyed dict of
  branch outputs. Sheet piping is a shared, evolving state — any
  later cell may draw from any earlier cell in any lane, at mixed
  dependency levels (`two-lanes-join`'s join prompt pipes a tool
  cell from one lane and an llm cell from another; `sheet-reused`
  joins two sub-sheet invocations). No partition into snapshot
  branches expresses that in general, and forcing one would betray
  the piping to save a combinator. The join is carried by the
  cell's position in the canonical sequence, where both sources
  are already in state.
- **`sheet` cell → an adapter `RunnableLambda` invoking the
  interior sheet's own `RunnableSequence` unit** — one unit per
  invocation site, because port bindings are per-site. Composition
  of runnables is LCEL's native nesting, and the boundary
  discipline is the interpreter's: bound values go in as the
  unit's seed state, only the declared boundary output and the
  re-prefixed interior trace come out, and interior values never
  enter the outer state. This is the direct analogue of the
  LangGraph lifter's node invoking its subgraph unit.
- **`sheet` cell in `each` mode → the fan-out carried by
  `RunnableEach`** (`RunnableLambda(...).map()`). The stage first
  validates the piped list through the embedded runtime
  (`runtime.each_elements` — the interpreter's own named refusals,
  `EachInputNotList` / `EachTooManyElements`, raised before any
  element runs), then maps the interior unit over the elements
  with the fixed bindings closed over and the element bound per
  item, then assembles the boundary line and the indexed interior
  sections. `RunnableEach` returns its results in element order;
  on `each-at-cap` (100 elements, 203 trace lines) the generated
  module's output was byte-identical to the interpreter's across
  repeated runs.
- **Unit head → `RunnablePassthrough`.** Each generated unit (the
  top-level sheet, and one per sub-sheet site) opens with the
  identity runnable: the state enters the unit unchanged, and the
  unit's input contract — a state dict in, a state dict out — is
  stated by its first stage rather than implied.

## The refusal boundary

The lifter validates first, with the shared taxonomy
(`CycleDetected`, `RecursiveSheetRef`, `EachElementConflict`, … —
the same names the interpreter and the LangGraph lifter refuse
with, checked for all eight negative fixtures below). Its own
refusal is **`UnliftableToLangChain`**, naming the construct: any
cell kind with no expression in the mapping above produces no
module. On the 0.3 corpus it never fires — `common.validate_sheet`'s
kind set and this lifter's mapping cover the same six kinds — and
that is stated plainly rather than dressed as a split: the refusal
is the contract for format growth (a future kind lands here first,
by name, instead of being silently approximated), and the runner's
refusal leg stands ready with its sidecar convention
(`fixtures/<name>.langchain.json`, recording the expected refusal
and the construct). Zero sidecars exist, because zero fixtures are
refused.

## Results (this workdir, venv with langgraph 1.2.17 +
langchain-core 1.7.0)

```
SUMMARY: 27/27 PASS            (interpreter vs golden vs LangGraph — unchanged)
LANGCHAIN SUMMARY: 27/27 PASS  (19 positives byte-identical + 8 negatives refused by name)
```

All 19 positive fixtures lift to LangChain byte-identically —
including both branch fixtures (as `RunnableBranch`), the join and
the reused-sheet fixtures (as sequence stages), two-rung nesting,
and every `each` composition (`each-define`, `each-empty`,
`each-at-cap`, `each-in-sheet`, `each-of-sheets`, `batch-wrap`).
All 8 negative fixtures are refused with the identical names: the
six validation-phase refusals from the lifter itself, and the two
runtime-phase refusals (`EachInputNotList`, `EachTooManyElements`)
from the running generated module, exiting non-zero with the name
in its output. The 0.3 fixtures and goldens are byte-identical to
the shipped repository's; the pre-existing two legs still read
27/27.

## The verdict on the plural-lift claim

**Proven, for the 0.3 format, in full.** One sheet now has three
execution-equal readings — the reference interpreter, a LangGraph
graph, and a LangChain chain — proven by the same conformance
object (the canonical trace) on every fixture the format's corpus
contains. The original claim — a sheet lifts to LangGraph *and*
LangChain the way an HDL description lifts to many targets — holds
for both named targets, with no fixture left as an exception.

**Bounded, in character.** The two lifts are not the same kind of
artefact. The LangGraph module *shows the sheet's shape*: nodes for
cells, barrier edges for fan-in, a subgraph for a sub-sheet — the
piping topology survives translation. The LangChain module shows
the sheet's *schedule*: a pipeline of stages in canonical order,
with fan-in absorbed into sequence position and topology visible
only in the trace it reproduces. A reader auditing structure
should read the graph; a reader embedding the workflow in an LCEL
ecosystem gets a chain that is native there. Both are the sheet;
neither is a simulation of the other.

**Bounded, in scope.** The proof covers the constructs the 0.3
format has. The format's own refusals (cycles, push kinds,
unbounded iteration) have no lift anywhere, LangChain included.
And within LCEL, the mapping's combinators are sequence,
selection, per-element map, and unit composition; a future
construct whose control structure is none of those meets
`UnliftableToLangChain` by name. Conformance, as with every lift
here, is proven against the embedded stub runtime — binding real
providers remains the host layer's job (`HOST.md`), unchanged by
this lift.
