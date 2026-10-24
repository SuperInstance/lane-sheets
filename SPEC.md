# Lane Sheets 0.1 — Specification

> **0.2:** the `sheet` cell kind (sub-sheet composition) is specified
> in `SPEC-AMENDMENT.md`, which extends this document. Everything
> below is the 0.1 format and remains in force unchanged.
>
> **0.3:** the `each` mode of a `sheet` cell (iteration: the interior
> sheet applied per element of a piped list) is specified in
> `SPEC-AMENDMENT-0.3.md`, which extends both documents.

**SuperInstance.** Agent workflows as *sheet data*: one abstraction below
LangChain/LangGraph, the way Verilog sits below C and Python. A workflow
is a JSON document of lanes and cells. It is not code in any framework's
runtime; frameworks are lifts from it. The same sheet, executed by the
reference interpreter or lifted into LangGraph, produces the same
canonical trace — the trace is the conformance object, playing the role
the state hash plays for the Quilt cell fabric ("The hash is the only
truth that survives portability" — Quilt Charter, via the shelf study).

This document and its reference implementation are the **compiler leg**
the SuperInstance shelf study named as missing in both directions:
*"what doesn't exist: the lowering pass sheet→netlist"* (AI-Writings,
STEELMAN-SHEET-IS-THE-RUNTIME) and, upward, sheet → framework code had
"no artefact at all" (DOSSIER.md §5c). QUIL, the downward analogue on
the hardware side, is "design decided; compiler not yet built." This is
the upward leg, built, at the smallest size that is still honest.

Design law, learned from the shelf: **the narrow contract is the
portable truth.** The cell-fabric contract (16 dials, an id, neighbours,
one hash) crossed a dozen languages byte-exact; the richer 5-opcode VM
had not converged across ports (its own conformance corpus: 7 MATCH /
29 DIVERGE). Lane-sheet 0.1 is therefore deliberately tiny: five cell
kinds, one piping rule, one execution order, and a named refusal for
everything else.

---

## 1. Sources and lineage

Everything here is grounded in artefacts that already exist on the
SuperInstance shelf; citations are to repos and docs, quoted in the
study dossier (`~/workspace/lane-sheets-study/DOSSIER.md`):

- **SuperInstance/quilt** — *"A spreadsheet where every cell is a live,
  addressable capability. The grid is the runtime."* A sheet is a JSON
  document of typed cells with dependencies; the engine evaluates it.
  Its `docs/guide/cell-kinds.md` defines 9 cell kinds: `value`,
  `formula`, `api`, `program`, `sensor`, `listener`, `router`, `io`,
  `ai` (the `ai` kind is an LLM call with a `{{cell}}`-templated prompt).
- **SuperInstance/quilt-agent** — *"AI agents where every capability is
  a cell… the agent is a sheet."* Its mapping table: memory → `value`,
  tools → `api`, reasoning prompt → `formula`, reasoning step →
  `program`, output → `formula`, goals/alerts → `listener`. Cell ids
  are dotted paths (`input.task`, `tool.search`, `reasoning.prompt`);
  lane sheets keep that convention.
- **DOSSIER.md §2** — the calculus (BIND/LINK/EFFECT/VIEW/TICK) and the
  doctrine that state moves between substrates as bytes and agreement
  is proven by hash, never by trusting implementations. Lane sheets
  inherit the doctrine with the trace in the hash's role.
- **DOSSIER.md §4** — the two-tier law: *"byte-exact fabric runs never
  route through LLM inference… neural cells allowed only in a
  trace-labeled tier, never in conformance paths."* Lane-sheet
  conformance therefore runs against **deterministic stub providers
  only** (§7). A real LLM behind an `llm` cell is a host decision,
  outside conformance.

## 2. The format

A lane sheet is a single JSON object:

```json
{
  "lanesheet": "0.1",
  "id": "linear-chain",
  "title": "optional human title",
  "lanes": [
    { "id": "main", "cells": [ /* cell objects, in row order */ ] }
  ],
  "outputs": ["output.framed"]
}
```

- `lanesheet` — format version; 0.1 is the only version this spec
  defines. Any other value is refused (`UnsupportedVersion`).
- `id` — the sheet's name.
- `lanes` — a non-empty list of lanes. A **lane** is a row of cells: a
  named group with an order. Lane membership carries exactly one
  semantic weight — it feeds the tie-break in the canonical execution
  order (§6). Semantically a lane is a cell at a higher rung: what a
  lane *is* depends on where you are leading from; the sheet does not
  care.
- `outputs` — the cell ids a host should treat as the sheet's results.
  Metadata for hosts; execution does not depend on it (§5).

A **cell** is an object with `id`, `kind`, optional `inputs`, and
kind-specific fields (§3). Cell ids are unique across the whole sheet
and conventionally dotted (`reasoning.prompt`). `inputs` maps **port
names** to **cell ids**: `{"prompt": "reasoning.prompt"}` means "this
cell's `prompt` port is piped from the cell `reasoning.prompt`."

No other keys are permitted anywhere — not on the sheet, not on a lane,
not on a cell. An unrecognised key is refused (`UnexpectedKey`), never
ignored: a field the engine does not understand is a construct the
engine would silently mis-handle, and silent mis-handling is the one
failure this format exists to prevent.

## 3. Cell kinds

Five kinds. The table maps each to the shelf kind it descends from.

| Lane-sheet kind | Descends from | What it does |
|---|---|---|
| `value` | quilt `value`; quilt-agent memory/task cells | A constant. Carries one field, `value`: any JSON value. Takes **no inputs** — constants do not pipe. |
| `prompt` | quilt-agent's prompt-as-`formula`; quilt `ai` kind's prompt template | Assembles a string. Carries `template`, a string with `{{port}}` placeholders, each filled from the piped input of that port. Pure and deterministic. |
| `llm` | quilt `ai`; quilt-agent's LLM `api`/`program` cells | One call to the host's LLM provider. Ports: `prompt` (required), `system` (optional). Output: the provider's completion string. The sheet names no model, endpoint, or key. |
| `tool` | quilt `api`; quilt-agent tool cells | One call to a named host tool. Carries `tool` (the tool's name); its input ports become the tool's argument object. Output: the tool's JSON result. The sheet names no endpoint. |
| `branch` | quilt `router`, reduced to value selection | Selects between two piped values. Ports: `cond`, `then`, `else` (all required); optional field `equals`. Output: one of the arm values (§5). |

**How a tool cell differs from a prompt cell** — the distinction the
format turns on:

- A `prompt` cell is *interior work*: string assembly, inside the cell,
  deterministic, identical in every host forever. Its output is fully
  explained by its inputs.
- A `tool` cell is *piping to the outside*: the sheet declares only a
  name and arguments; what the name *does* is the host's business (an
  HTTP API in quilt's `api` kind; a function in the stub registry here).
  Same for `llm`: the cell is a port to a provider, not a computation.
  This is the shelf's piping paradigm stated as a type distinction:
  cells do not care what happened inside other cells — or inside a
  tool — unless it affected them, i.e. arrived as a value on a pipe.

## 4. Piping

Cells connect **only** through `inputs`. There is no other channel: no
shared variables, no globals, no ambient context, no call stack. A
cell's output is a single JSON value, available to any number of
downstream cells (fan-out) and combined only by a downstream cell
declaring several ports (fan-in — a join is just a cell whose ports
pipe from two lanes).

A sheet must be a **DAG**: piping cycles are refused (`CycleDetected`).
Ports pipe from cells anywhere in the sheet, across lanes freely; lane
boundaries are not firewalls, they are rows.

## 5. Execution semantics

A run is single-pass and run-to-completion, like a spreadsheet
recalculating:

- **Every cell computes exactly once**, in canonical order (§6),
  whether or not its value is ever consumed. There is no laziness and
  no notion of a cell "not running." (`outputs` names results for the
  host; it does not prune the run.)
- **Run state is derived, never stored.** The sheet contains no state;
  a run produces values and a trace, and the sheet is byte-identical
  before and after. State lives in the run the way quilt state lives
  in the fold: as the consequence of the records, not in them.
- **`value`** → its constant. **`prompt`** → the template with each
  `{{port}}` replaced by the string form of that port's value (strings
  as-is; any other JSON value in canonical JSON, §6). A placeholder
  naming a port the cell does not pipe is refused at validation
  (`TemplateError`). **`llm`** → the provider's completion for the
  `prompt` (and `system`) input; a non-string prompt is refused at run
  time (`NonStringPrompt`). **`tool`** → the named tool called with the
  argument object built from its ports. **`branch`** → value selection:
  if the cell carries `equals`, the `then` value is selected iff `cond`
  deep-equals it (compared by canonical JSON, so `1` and `true` never
  conflate); without `equals`, `then` is selected iff `cond` is
  neither `false` nor `null` — the only two falsy values 0.1
  recognises. **Both arms are always fully evaluated** — a branch is
  `IF()` in a spreadsheet, not a control-flow jump; the unselected
  arm's tool and llm calls happen and appear in the trace. This is a
  deliberate v0.1 semantics, named here so no reader mistakes it for
  laziness (see §8).

## 6. Canonical order and the trace

Execution order must be reproducible by any engine, so it is defined
from the sheet alone:

1. A cell's **level** is 0 if it pipes from nothing, else 1 + the
   maximum level of its sources.
2. Cells execute level by level; within a level, **sheet order**
   decides (lane order, then cell order within the lane).

Every executed cell appends one **trace line**: a JSON object in
canonical encoding (keys sorted, `,`/`:` separators, UTF-8),

```json
{"cell":"reasoning.answer","inputs":{"prompt":"Explain the active ledger in one sentence."},"inputs_hash":"b535d76ba35d7e6ae81f89f77f4d63e01780151d6ebd493bf72368eff3fd8e6c","kind":"llm","output":"[stub-llm:7f39acc0] Explain the active ledger in one sentence. -> noted"}
```

with `inputs` the port→value map the cell actually received and
`inputs_hash` the SHA-256 of its canonical encoding. **The trace is the
conformance object**: two engines agree on a sheet iff their traces are
byte-identical. This mirrors the shelf's discipline — agreement proven
by the canonical artefact, not by trusting an implementation — with the
FNV state hash of the cell fabric replaced by a per-cell trace because
a workflow's truth is its steps, not only its final state.

## 7. Providers (hosts and stubs)

`llm` and `tool` cells name providers; sheets never bind them. A host
supplies: one LLM completion function (inputs: prompt, optional system;
output: string) and a registry of named tools (each with named,
string-typed required argument ports; input: argument object; output:
any JSON value).

The reference implementation ships **stub providers** (`lanesheet/
runtime.py`), deterministic pure functions — a fake LLM whose reply is
a digest-stamped echo of the prompt's last line, and three fake tools
(`search`, `wordcount`, `lookup`). Conformance runs only against the
stubs: per the two-tier law (§1), byte-exact paths never route through
real inference. A host that binds a real model or real APIs gets the
same sheet semantics and *no* trace guarantee against the stubs — that
is the correct trade, and it is stated rather than hidden.

## 8. What is deliberately NOT in 0.1

Each exclusion is a named refusal. The interpreter and the lifter run
the same validation, so an unsupported construct is refused identically
in both, before any execution or code generation.

| Excluded construct | Refusal |
|---|---|
| Loops, cycles, iteration, recursion — sheets are DAGs, single-pass | `CycleDetected` |
| Lazy/short-circuit branching — arms are eagerly evaluated (§5) | (semantics, not a construct: there is no syntax for it) |
| Formula/expression language (quilt `formula`) — prompt templates interpolate only; no arithmetic, no logic in templates | a template is a string; anything beyond `{{port}}` is literal text |
| Push and ambient kinds: quilt `listener`, `sensor`, `io` — no events, no polling, no streams | `UnsupportedCellKind` |
| quilt `api` as a kind — endpoints are host bindings, not sheet data (§7) | `UnsupportedCellKind` |
| quilt `program` as a kind — no arbitrary code cells; code is how sheets get *lifted*, not what they contain | `UnsupportedCellKind` |
| quilt `router`, `ai` as kinds — subsumed by `branch` and `llm` respectively | `UnsupportedCellKind` |
| Sub-sheets / nested sheets / sheet imports — composition is a future version's problem | `UnexpectedKey` (no such field exists) |
| Stored run state, checkpointing, resume — state is derived per run (§5) | (no field exists; `UnexpectedKey` if attempted) |
| Parallel scheduling as semantics — execution order is canonical (§6); hosts may parallelise only where the trace cannot tell | (the canonical order is the contract) |
| Conditions beyond equality/truthiness in `branch` — no predicates, no expressions | `UnexpectedKey` / `UnexpectedPort` for anything else |

## 9. Refusals (error taxonomy)

All refusals are `LaneSheetError`s carrying a stable `name`; the name
is the spec, the message is for humans.

- **Shape:** `SheetNotObject`, `MissingField`, `UnexpectedKey`,
  `UnsupportedVersion`, `DuplicateLaneId`, `DuplicateCellId`,
  `ReservedCellId` (`START`/`END`), `NodeNameCollision`,
  `UndeclaredOutput`.
- **Kinds and ports:** `UnknownCellKind`, `UnsupportedCellKind` (a real
  Quilt kind, not in 0.1), `MissingPort`, `UnexpectedPort`,
  `ValueCellInputs`, `UnknownInputCell`, `TemplateError`,
  `UnknownTool`.
- **Structure:** `CycleDetected`.
- **Run time:** `NonStringPrompt`, `ToolArgument` — raised identically
  by the shared runtime both engines embed.

## 10. The lifter

`lanesheet/lift_langgraph.py` compiles a validated sheet into a
standalone Python module using LangGraph's `StateGraph`:

- one node per cell; values flow through the graph state keyed by cell
  id; each node appends its canonical trace line to the state's trace;
- each node is wired with a **barrier edge** over its trigger set — its
  piped input sources plus its predecessor in canonical order — so the
  lifted graph executes in exactly the canonical order and its printed
  trace is the interpreter's trace, byte-for-byte (verified by
  `run_conformance.py` against golden traces);
- the module embeds `lanesheet/runtime.py` **verbatim**, so the stub
  providers and canonical trace format it runs against are the very
  code the interpreter used — the lift carries its conformance basis
  with it, the way a QUF file carries the fabric's state as bytes.

The lifter refuses what the interpreter refuses (§8, §9) — validation
runs first, and an unsupported sheet produces no module.

## 11. Worked example

`fixtures/linear-chain.sheet.json` — a topic, a prompt built from it, an
llm answer, a framed output:

```json
{
  "lanesheet": "0.1",
  "id": "linear-chain",
  "lanes": [
    { "id": "main", "cells": [
      { "id": "input.topic", "kind": "value", "value": "the active ledger" },
      { "id": "reasoning.prompt", "kind": "prompt",
        "template": "Explain {{topic}} in one sentence.",
        "inputs": { "topic": "input.topic" } },
      { "id": "reasoning.answer", "kind": "llm",
        "inputs": { "prompt": "reasoning.prompt" } },
      { "id": "output.framed", "kind": "prompt",
        "template": "Answer: {{answer}}",
        "inputs": { "answer": "reasoning.answer" } }
    ] }
  ],
  "outputs": ["output.framed"]
}
```

Its full trace is `fixtures/linear-chain.golden.jsonl`; four more
fixtures (branch selection on each arm, a tool cell feeding a prompt
cell, two lanes joining into one prompt) and two negative fixtures (a
`listener` cell, a piping cycle) ship beside it.

---

*Lane Sheets 0.1 — SuperInstance. Reference implementation:
`lanesheet/` (interpreter, lifter, shared runtime); conformance:
`run_conformance.py`.*
