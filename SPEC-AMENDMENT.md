# Lane Sheets 0.2 — Amendment: Sub-Sheet Composition

**SuperInstance.** This amendment adds one cell kind to Lane Sheets
0.1 (SPEC.md): the `sheet` cell, whose interior is a whole other
sheet. Everything in SPEC.md remains in force except where this
amendment says otherwise; in particular the conformance object is
still the canonical trace, engines still agree byte-for-byte or not
at all, and every unsupported construct is still a named refusal,
raised identically by the interpreter and the lifter before any
execution or code generation.

The design centre is the nesting doctrine of the wider programme:
quilts are embedded inside cells, the same way a house contains
people, people contain organs, organs contain cells. A sheet cell is
that nesting made literal. From the outer sheet's rung, the cell is
**opaque** — its interior is sovereign, and the only things that
exist between the interior and the outside are what cross on the
piping: named values in, one named value (or a small named set) out.
You lead from a rung; the sheet cell is how a workflow changes rungs
without breaking the paradigm that made the flat sheet work.

## 1. Versioning

- A sheet that uses `sheet` cells declares `"lanesheet": "0.2"`.
- A 0.1 document remains valid and unchanged in meaning. A `sheet`
  cell inside a document declaring `"0.1"` is refused
  (`UnsupportedVersion`): the cell is a 0.2 construct and the document
  said it was not using any.
- An inner (referenced) sheet may declare either version, subject to
  the same rule applied to its own cells: a 0.1 inner sheet simply
  contains no `sheet` cells.

## 2. The `sheet` cell

```json
{ "id": "wrap.chain", "kind": "sheet",
  "sheet": "linear-chain",
  "inputs": { "topic": "input.topic" },
  "bind": { "input.topic": "topic" },
  "output": "output.framed" }
```

Fields (no others are permitted — `UnexpectedKey` as in 0.1):

| Field | Meaning |
|---|---|
| `sheet` | The reference: a **bare library name** matching `[A-Za-z0-9][A-Za-z0-9_-]*`. It names a sheet document `<name>.sheet.json` in the library the host resolves against (in the reference implementation and the conformance suite: the directory of the sheet that carries the reference — a flat, fixture-local library at every rung). Path separators, traversal, and file extensions in a reference are refused (`InvalidSheetRef`). |
| `inputs` | The cell's ports, piped from outer cells exactly as for any other kind (SPEC §4). |
| `bind` | The input mapping: interior cell id → this cell's port name. Each bound interior cell must be a **`value` cell** (see §3). May be omitted or empty when nothing is piped in. |
| `output` | One interior cell id. The sheet cell's output is that cell's value, bare. |
| `outputs` | A name → interior cell id map. The sheet cell's output is the object `{name: value, …}`. |

Exactly one of `output` / `outputs` must be present (both:
`SheetOutputConflict`; neither: `MissingField`).

**Port correspondence is exact.** Every port named in a `bind` value
must be piped in `inputs` (`MissingPort`), and every piped port must
be bound to some interior cell (`UnexpectedPort`). A pipe into a
sub-sheet that lands nowhere is a value crossing the boundary to no
effect — the piping paradigm does not permit it. One port may feed
several bound interior cells (fan-out across the boundary is fine).

The interior sheet's own `outputs` list plays no role in invocation:
the boundary is declared by the sheet cell itself, in `bind` and
`output`/`outputs`.

## 3. Boundary semantics

An invocation of a sheet cell is a run of the referenced sheet, one
rung down, with these rules:

- **Parameters are constants awaiting values.** `bind` may target
  only interior `value` cells. When the interior sheet runs as an
  invocation, a bound `value` cell computes the piped value in place
  of its constant. Only a constant can be a parameter: binding is
  *replacing a value the interior sheet already declared*, not
  reaching into a computation. (Target missing: `UnknownBindCell`;
  target of any other kind: `BindTargetNotValue`.)
- **Every interior cell computes exactly once**, in the interior
  sheet's own canonical order, whether or not its value reaches the
  boundary — the same run-to-completion rule as the top rung (SPEC
  §5). There is no laziness at the boundary either.
- **The only value that crosses back** is the declared boundary
  output: the single cell named by `output`, or the object assembled
  from `outputs`. No other interior value enters the outer run's
  value map. An outer cell that pipes from an interior cell id (e.g.
  `wrap.chain/reasoning.prompt`) is refused (`UnknownInputCell`) —
  that id is not a cell of the outer sheet; it does not exist at
  this rung.
- **Invocations are independent.** The same referenced sheet used by
  two sheet cells (or twice by the same cell's sheet at different
  rungs) runs once per invocation, with that invocation's bindings.
  Nothing is shared or cached between invocations; reuse is the
  plugin shape, and a plugin does not remember its last host.
- **Determinism is inherited.** The interior runs on the same stub
  providers; a trace that crosses a boundary is as reproducible as a
  flat one.

## 4. Trace shape

The trace remains one canonical JSON line per executed cell, in
execution order, with one structural addition:

1. A sheet cell contributes **one line at its own rung**, in the
   outer sheet's canonical order, with `"kind": "sheet"`, its
   `inputs` the boundary port→value map it actually received, and
   its `output` the boundary output value. This line is the whole
   truth about the cell *as far as the outer fold is concerned*.
2. **Immediately after it**, the invocation's interior trace
   section: every interior cell's line, in the interior sheet's
   canonical order, with the cell id **prefixed** by the sheet
   cell's id and a `/` separator (`wrap.chain/reasoning.prompt`).
   A sheet cell inside the interior contributes its own line and
   section the same way, so prefixes accumulate per rung
   (`nest.mid/inner.leaf/reasoning.prompt` is a cell two rungs
   down). The section is delimited by position (directly after its
   parent line, before the next line of the parent rung) and by the
   prefix (every line of the section, and only those lines, carries
   it).
3. A bound interior `value` cell's line shows `inputs: {}` — value
   cells take no inputs at their own rung; what was piped in crossed
   at the boundary and is recorded on the parent line — and its
   `output` is the bound value, so the landing is visible in the
   section.

Two engines agree on a nested sheet iff their full traces — boundary
lines and interior sections alike — are byte-identical. The
conformance suite checks exactly this, golden vs interpreter vs
lifted module.

## 5. Reference chains: recursion and depth

Sheet references form a graph, and the graph is checked whole at
validation time, following every reference transitively:

- **Recursion is refused.** A sheet that contains itself, directly
  or transitively (A references B, B references A), is refused
  (`RecursiveSheetRef`, with the cycle spelled out in the message).
  Composition is a DAG of sheets for the same reason piping is a
  DAG of cells: a run must be finite and single-pass, and a sheet
  that contains itself has no bottom rung to stand on.
  Reuse is not recursion: the same sheet referenced from two
  different cells, or from two different branches of a reference
  tree, is a diamond, not a cycle, and is legal.
- **Depth is capped.** A reference chain may descend at most **8
  edges** below the sheet handed to the engine. The edge that would
  exceed the cap is refused (`SheetNestingTooDeep`). The cap exists
  so a finite-but-absurd library cannot exhaust the engine by
  depth alone; it is a scope limit of 0.2, to be raised deliberately
  in a future version — never silently.
- **Unresolved references are refused.** A reference the host's
  library cannot supply — no library was provided, the file is
  absent, or it does not parse — is `UnresolvedSheetRef`, raised at
  validation, in both engines, before anything runs.

## 6. Refusals added by this amendment

All are `LaneSheetError`s with stable names, raised identically by
the interpreter and the lifter (SPEC §9 remains the taxonomy for
everything else):

| Refusal | Condition |
|---|---|
| `InvalidSheetRef` | `sheet` field is not a bare library name (separators, traversal, leading dot, empty handled as `MissingField`) |
| `UnresolvedSheetRef` | No library supplied, or the referenced document is missing/unparsable |
| `RecursiveSheetRef` | The reference closes a cycle in the reference graph |
| `SheetNestingTooDeep` | The reference chain exceeds 8 edges |
| `UnknownBindCell` | `bind` names an interior cell that does not exist |
| `BindTargetNotValue` | `bind` names an interior cell that is not a `value` cell |
| `UnknownSheetOutput` | `output`/`outputs` names an interior cell that does not exist |
| `SheetOutputConflict` | Both `output` and `outputs` are declared |

Reused from 0.1, applied at the boundary: `MissingPort` /
`UnexpectedPort` for port correspondence, `MissingField`,
`UnexpectedKey`, `UnsupportedVersion` (a `sheet` cell in a 0.1
document), `UnknownInputCell` (piping from an interior id),
`NodeNameCollision` (site-qualified node names in the lifter).

## 7. The lifter

The lifted module keeps the 0.1 shape (SPEC §10) and adds: for each
sheet-cell **invocation site**, the lifter emits the referenced
sheet as its own LangGraph `StateGraph` unit — node functions with
site-qualified names, its own barrier-wired build, and a
`run_sub_*` entry that takes seed values and returns the interior
values and trace lines. One unit per site, not per referenced sheet,
because bindings are per-site: two cells invoking the same sheet
with different bindings are two invocations and get two units (the
emitted code is larger; the semantics are the obvious ones).

The sheet cell's node seeds the subgraph's state with the bound
values (a bound interior `value` cell reads its seed if one is
present, else its constant — the same rule the interpreter applies),
invokes it, takes the declared boundary output, then emits its own
trace line followed by the interior lines re-prefixed with its cell
id, re-encoded canonically. The outer graph sees the node as one
node; the subgraph is as opaque to LangGraph as the interior sheet
is to the outer sheet.

## 8. Rung semantics — what the outer fold can and cannot see

State it in piping terms, because piping terms are the only terms
the paradigm allows across a boundary. A sheet cell's interior
sheet is a cell's interior, one rung up in scale and identical in
kind: **the outer fold can see exactly what crossed the piping, and
nothing else.** Inbound, it sees the values it itself sent — they
are its own `inputs`, recorded on its own trace line. Outbound, it
sees the one declared output value. That is the complete interface,
and it is complete *by construction*: the outer sheet's value map
never holds an interior value that did not cross as the boundary
output, and an outer cell cannot even *name* an interior cell in
its piping — the id does not resolve at this rung, and the attempt
is refused by name.

The trace deserves one careful sentence, because it looks like an
exception and is not. The interior section is present in the trace —
prefixed, attributable, auditable — but the trace is the run's
*record*, not its piping: no value flows from an interior line to
an outer cell. Reading the section is looking at the rung below
from outside it, the way you may read a ledger you did not write;
it changes nothing about what the outer fold could compute. An
engine that emitted only the boundary lines would fold the same
state and return the same outputs; it would merely have kept worse
receipts. The paradigm's rule — interiors are sovereign, only
effects cross — governs *computation*, and the interior section is
not computation crossing. It is the receipts, filed where they can
be checked.

What the outer rung cannot do, then: it cannot observe an interior
cell's value except the declared output; cannot address, pipe from,
branch on, or schedule an interior cell; cannot tell from its own
fold whether the interior was three cells or three thousand, or
whether the interior sheet is itself nested — depth below the
boundary is visible in the receipts and invisible to the fold,
which is exactly the position of anyone leading from a rung: the
levels below you are real, they are auditable, and they are not
yours to steer cell by cell. You steer at the boundary, in piping,
or you descend a rung and lead from there instead.

## 9. What is still excluded (named)

- **References beyond the local library.** No URLs, no package
  registries, no cross-repository imports, no version ranges: a
  reference is a bare name in one flat library. (Any such syntax is
  `InvalidSheetRef` or `UnresolvedSheetRef`.)
- **Dynamic references.** The referenced sheet is named by a string
  literal in the cell. A sheet whose reference is computed, piped,
  or selected by a `branch` does not exist in 0.2 — there is no
  syntax for it, and a `sheet` field that is not a string literal
  name is refused as above.
- **Binding non-`value` cells.** No overriding a prompt's template,
  a tool's name, or a branch's arms from outside (`BindTargetNotValue`).
  A sheet that wants a parameter declares a `value` cell for it.
- **Multiple sheets per cell, sheet-valued pipes.** A cell invokes
  exactly one sheet; a sheet's output crosses as a value, never as
  a runnable sheet. Sheets are not first-class values in 0.2.
- **Partial interior outputs.** `outputs` names whole interior
  cells. There is no path syntax into a value (`output.x.y`) —
  assemble the wanted shape with a `prompt` cell inside, or return
  the whole value.
- **Shared state between invocations.** No statics, no memoisation
  across sheet cells, no interior checkpointing or resume: each
  invocation is a fresh run, derived from its bindings alone (SPEC
  §5's rule, one rung down).
- **Cycles anywhere.** Piping cycles remain `CycleDetected`;
  reference cycles are `RecursiveSheetRef`. Both are refused, in
  both engines, before anything runs.

## 10. Fixtures

In `fixtures/`, beside the 0.1 corpus (which passes byte-identical
under the 0.2 engines):

- `sheet-once` — a sheet cell used once: `linear-chain` (itself a
  0.1 fixture) invoked with its topic bound from outside, its framed
  answer crossing back.
- `sheet-reused` — the plugin shape: `word-frame` invoked by two
  different outer cells with different bindings, the two results
  joined by a prompt. (`word-frame` is also a standalone fixture.)
- `sheet-nested` — two-level nesting: `mid-wrap` invoked from the
  outer sheet, `leaf-define` invoked from inside `mid-wrap`;
  prefixes in the golden trace accumulate to two separators deep.
  (`mid-wrap` and `leaf-define` are also standalone fixtures.)
- `negative-recursive` — a sheet that references itself; refused
  with `RecursiveSheetRef` by both engines.

---

*Lane Sheets 0.2 amendment — SuperInstance. Base specification:
SPEC.md; reference implementation: `lanesheet/`; conformance:
`run_conformance.py`.*
