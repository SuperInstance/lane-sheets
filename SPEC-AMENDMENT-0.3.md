# Lane Sheets 0.3 — Amendment: Iteration (the `each` mode)

**SuperInstance.** This amendment adds one mode to Lane Sheets 0.2
(SPEC.md + SPEC-AMENDMENT.md): a `sheet` cell may declare `each`,
naming one of its input ports, and the interior sheet then runs once
per element of the list piped to that port. Nothing else changes:
the conformance object is still the canonical trace, engines still
agree byte-for-byte or not at all, and every unsupported construct is
still a named refusal, raised identically by the interpreter and the
lifter. General iteration — while-loops, condition-controlled
repetition, recursion-as-looping — remains excluded, by name (§8).
What 0.3 adds is the one iteration form the paradigm already had the
shape for: **a sheet cell applied per element.** A spreadsheet does
not loop over a column; the formula *is* the column, evaluated per
row. An `each` cell is that: one interior sheet, evaluated per
element, the results collected in element order.

## 1. Versioning

- A sheet whose cells use `each` declares `"lanesheet": "0.3"`.
- A 0.1 or 0.2 document remains valid and unchanged in meaning. A
  `sheet` cell carrying `each` inside a document declaring `"0.1"`
  or `"0.2"` is refused (`UnsupportedVersion`): the mode is a 0.3
  construct and the document said it was not using any.
- An inner (referenced) sheet may declare any supported version,
  subject to the same rule applied to its own cells — exactly the
  0.2 rule, one mode further. A 0.3 outer sheet may fan out over a
  0.1 inner sheet; a 0.2 inner sheet containing an `each` cell of its
  own is refused when it declares 0.2, and fine when it declares 0.3.

## 2. The `each` mode

```json
{ "id": "fan.define", "kind": "sheet",
  "sheet": "leaf-define",
  "each": "words",
  "inputs": { "words": "input.words" },
  "bind": { "input.word": "words" },
  "output": "output.done" }
```

A `sheet` cell with `each` is an ordinary sheet cell (SPEC-AMENDMENT
§2 — every rule there applies) plus one field:

| Field | Meaning |
|---|---|
| `each` | The name of one of the cell's input ports. The value piped to that port must be a **list**; the interior sheet runs once per element of it. |

The `bind` map then divides into two roles, by port:

- **The element binding** — the one bind entry whose port is the
  `each` port. It designates the **element cell**: the interior
  `value` cell that receives each element in turn. Exactly one such
  entry must exist (§5).
- **Fixed bindings** — every other bind entry. They behave exactly
  as in a plain sheet cell: the piped value is bound into every
  invocation identically. A fixed binding is how an `each` cell
  shares context (a seed, a mode flag, a shared prefix) across its
  fan-out.

Port correspondence remains exact (0.2 §2), the `each` port
included: it is piped like any port, and bound — to the element
cell.

**The fan-out cap is 100 elements** (`runtime.MAX_EACH_ELEMENTS`).
The number is spec, set here and enforced identically by every
engine. Rationale: 100 is generous for the fan-outs a sheet
expresses — batch definition, per-item counting, per-element
framing over a working set a human assembled — while keeping one
cell's trace section a readable receipt and a lifted node's loop a
loop rather than a workload. A sheet that needs a larger fan-out
declares it as composition (an `each` inside an `each` multiplies
caps: two levels of 100 reach 10,000 element-runs, each one
auditable), rather than asking one cell's section to swallow it.
Raising the cap is a deliberate future version decision, never a
silent one; the refusal at 101 is the receipt that the line exists.

## 3. Semantics

An invocation of an `each` cell is a sequence of ordinary sub-sheet
invocations (0.2 §3), one per element, under these rules:

- **Element order is the order.** Invocations run in the list's
  order, and every collected result preserves it. There is no
  parallelism to specify: engines may schedule as they like
  internally, but the trace and the outputs are the sequential
  ones. (The reference engines are sequential.)
- **Each invocation is independent and complete.** Invocation *i*
  is a fresh run of the interior sheet with the fixed bindings plus
  element *i* at the element cell. Every interior cell computes
  exactly once per invocation, in the interior's canonical order —
  the run-to-completion rule, per element. Nothing is shared or
  cached between invocations; invocation *i* cannot observe
  invocation *j*.
- **The boundary output is the collection.** With `output` (one
  interior cell), the cell's output is the **list** of that cell's
  values, one per element, in element order. With `outputs` (a
  name → interior cell map), the output is the object
  `{name: [value per element], …}` — the map form transposed over
  the fan-out: each declared output becomes the list of its values.
- **An empty list is a legal fan-out.** Zero invocations run, no
  interior sections appear in the trace, and the output is the
  empty list (or, for `outputs`, the object of empty lists). A
  batch over nothing is nothing, collected — not an error.
- **The list shape and the cap are data checks.** Whether the
  `each` port was piped a list, and whether it is within the cap,
  are properties of a *value*, known only when the value arrives.
  Both are checked when the cell is reached, **before any element
  invocation runs**, identically in every engine
  (`runtime.each_elements`): a fan-out never starts and then
  discovers it should not have. Because traces are all-or-nothing —
  a refused run emits no trace — these refusals have the same
  standing as validation refusals: same names, both engines, no
  partial receipts.

Composition is unrestricted within the existing caps: an `each`
cell's interior may contain plain sheet cells and further `each`
cells; an `each` cell may sit inside a sheet cell's interior.
Element invocations do not consume reference-chain depth — the
chain is a property of references, not of runs — so the 0.2 nesting
cap (8 edges) is unchanged, and recursion stays refused: a sheet
that transitively contains itself is `RecursiveSheetRef` whether
the cycle passes through an `each` cell or not.

## 4. Trace shape

The 0.2 trace shape extends by indexing:

1. An `each` cell contributes **one boundary line at its own
   rung**, in the outer sheet's canonical order, `"kind": "sheet"`,
   its `inputs` the boundary port→value map it actually received —
   the full list included, at the `each` port — and its `output`
   the collected boundary output (the list of outputs, or the
   object of lists for `outputs`). The fan-out is fully pinned by
   this line alone: the element count is the length of the list in
   `inputs`, its content is pinned by `inputs_hash`, and the
   collected outputs are printed in full — as every boundary line
   prints its values in full (0.2 §4). An engine that emitted only
   boundary lines would fold the same state.
2. **Immediately after it**, the per-element interior sections,
   in element order. Element *i*'s section is the interior sheet's
   trace for invocation *i*, every cell id prefixed
   `<cell id>[<i>]/` — the 0.2 prefix with the element index in
   brackets between the cell id and the separator
   (`fan.define[0]/reasoning.prompt`). Sections are delimited both
   by position (consecutive, directly after the boundary line) and
   by the indexed prefix (every line of section *i*, and only those
   lines, carries `[i]` for this cell).
3. Prefixes accumulate exactly as in 0.2, the index riding its
   segment: an `each` cell one rung down shows
   `wrap.batch/fan.define[1]/input.word`; a sheet cell inside an
   element's interior shows the index before the deeper segments —
   `fan.plus[0]/inner.leaf/reasoning.answer` is a cell inside the
   sheet cell `inner.leaf`, inside element 0 of `fan.plus`.
4. A bound interior `value` cell's line shows `inputs: {}` and its
   `output` is what it was bound — the element itself, in the
   element cell's section; the fixed bindings' values, in every
   section — the landing recorded per invocation, as in 0.2.

Two engines agree on a sheet using `each` iff their full traces —
boundary lines and indexed sections alike — are byte-identical. The
conformance suite checks exactly this, golden vs interpreter vs
lifted module.

Cell ids containing a bracketed index segment (e.g. a literal id
`fan[0]`) would make prefixes ambiguous to a reader; the format
does not mint such ids in its corpus and engines do not refuse
them — the prefix grammar is positional, and conformance compares
whole lines, so agreement is unaffected. Authors should not name
cells that way.

## 5. Refusals added by this amendment

All are named refusals with stable names, raised identically by the
interpreter and the lifter (and by the host, §7). Validation-phase
refusals fire before any execution or code generation, as in 0.1
and 0.2; the two run-phase refusals fire when the `each` cell is
reached, before any element invocation (§3).

| Refusal | Phase | Condition |
|---|---|---|
| `EachPortNotPiped` | validation | `each` names a port that is not among the cell's piped inputs |
| `EachElementUnbound` | validation | No bind entry maps an interior cell to the `each` port — the interior declares no designated element cell for this fan-out |
| `EachElementConflict` | validation | Two or more bind entries map interior cells to the `each` port; exactly one element cell may be designated (pipe inside the interior if two cells need the element) |
| `EachInputNotList` | run | The value piped to the `each` port is not a list |
| `EachTooManyElements` | run | The list's length exceeds the cap of 100 |

Reused from earlier versions, applied at the element boundary: the
element cell is a bind target like any other, so a missing target
is `UnknownBindCell` and a non-`value` target is
`BindTargetNotValue`; port correspondence reuses
`MissingPort`/`UnexpectedPort`; the version gate reuses
`UnsupportedVersion`; a non-string `each` is `MissingField`.

**Why the element designation is singular.** A fan-out lands each
element on one declared constant. Two designated cells would make
the element binding a second, hidden fan-out *inside* the boundary
rule — and it buys nothing: an interior that needs the element in
two places declares one element cell and pipes from it, in the
open, where the interior's own trace shows the flow. The refusal
keeps the boundary auditable at a glance: one list, one landing
cell, one index per section.

## 6. The lifter

The lifted module keeps the 0.2 shape and adds: for an `each`
cell, the lifter emits the referenced sheet as its site unit
exactly as for a plain sheet cell (one unit per invocation site,
bindings per site). The cell's node validates the fan-out through
the embedded runtime (`each_elements` — the same code, so the same
refusal names and the same cap), then invokes the site unit once
per element, in element order, seeding the fixed bindings plus
the element at the element cell. It collects the boundary outputs
into the list (or the object of lists), assembles its boundary
line, and appends the per-element sections re-prefixed with the
indexed site prefix. A run-phase refusal inside the generated
module surfaces as the embedded runtime's `StubError` carrying the
same refusal name — the module exits non-zero with the name in its
output, and prints no trace. The conformance suite's run-phase
negatives check exactly this.

## 7. The host

The host runs `each` cells as it runs sheet cells: the same
recursion, the same bindings rule at every rung (an interior
`llm`/`tool` cell resolves its binding per element invocation,
identically), the same run-phase refusals re-named as host errors
with the same names. A stub-host run of a sheet using `each`
produces a body byte-identical to the conformance golden, header
aside — the two tiers stay separate exactly as before.

`run_host_check.py` validates `each` traces structurally: one
interior section per element, in order, under the indexed
prefixes; each section's element cell output equal to its element;
the fixed bindings equal to the boundary record's inputs; and the
boundary output equal to the declared interior outputs collected
in element order.

One checker rule deserves its sentence, because the 0.3 corpus is
the first to exercise it: a sheet tree containing **no provider
cells at all** (no `llm`/`tool` anywhere, interiors included)
honestly resolves no bindings, so its host header names none. The
checker verifies that claim against the sheet — empty bindings are
accepted iff the tree is provider-free, and a header naming
bindings for such a sheet fails. (In 0.1–0.2 every runnable sheet
tree happened to contain a provider cell, so the case never
arose; `echo-item` and `each-at-cap` are provider-free by design.)

## 8. What is still excluded (named)

- **General loops.** No while-loops, no condition-controlled
  repetition, no iterate-until, no recursive sheet invocation as a
  looping device. Repetition in 0.3 is exactly: a list that already
  exists, mapped through one interior sheet. If the list does not
  exist yet, no `each` cell will invent it.
- **Data-dependent fan-out shape.** The list must arrive whole, as
  one piped value. There is no streaming, no lazy enumeration, no
  generating elements from inside the interior, and no early exit:
  every element runs its full interior, even if a downstream cell
  will only read the first result.
- **Multiple element ports.** One `each` port per cell — no zip of
  two lists, no product of lists. Compose two `each` cells
  (nested, or in sequence through an intermediate sheet) instead.
- **Element-dependent references.** The interior sheet is the
  literal reference named in the cell, for every element. A
  per-element choice of interior (dispatch on the element) does
  not exist in 0.3, as dynamic references did not exist in 0.2.
- **Cross-element state.** No accumulators, no running totals, no
  element observing a sibling's run. Folding a fan-out's results
  together is ordinary piping *after* the cell: pipe the collected
  list into a prompt, a tool, or another sheet.
- **Nested lists as elements — not excluded, just data.** An
  element may itself be a list (an inner `each` cell's input, say);
  the format does not inspect elements. `EachInputNotList` judges
  only the piped value's own shape.

## 9. Fixtures

In `fixtures/`, beside the 0.1–0.2 corpus (which passes
byte-identical under the 0.3 engines):

- `each-define` — the headline shape: three words fanned out over
  `leaf-define` (a 0.1 sheet with a stub `llm` inside), the
  definitions collected into one list and framed by a prompt.
- `each-empty` — an empty list: zero invocations, zero sections,
  an empty list out.
- `batch-wrap` — the `outputs`-map form over two elements (also a
  library sheet for `each-in-sheet`): the boundary output is
  `{done: [...]}`.
- `each-in-sheet` — an `each` cell one rung down: the outer sheet
  invokes `batch-wrap` as a plain sheet cell; prefixes accumulate
  through the boundary and the fan-out alike.
- `each-of-sheets` — an `each` whose interior itself nests:
  `define-plus` (a 0.2 wrapper around `leaf-define`) run per
  element; the golden shows index-then-rung prefixes two segments
  deep. (`define-plus` is also a standalone fixture.)
- `each-at-cap` — exactly 100 elements over `echo-item`, the cap
  boundary itself, passing: 203 trace lines. (`echo-item` is also
  a standalone fixture.)
- Negatives: `negative-each-nonlist` (a string at the `each`
  port → `EachInputNotList`, run phase), `negative-each-overcap`
  (101 elements → `EachTooManyElements`, run phase),
  `negative-each-unbound` (no element designation →
  `EachElementUnbound`), `negative-each-conflict` (two
  designations → `EachElementConflict`),
  `negative-each-version` (the mode in a 0.2 document →
  `UnsupportedVersion`).

---

*Lane Sheets 0.3 amendment — SuperInstance. Base specification:
SPEC.md; composition: SPEC-AMENDMENT.md; reference implementation:
`lanesheet/`; conformance: `run_conformance.py`.*
