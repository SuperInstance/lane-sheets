# DOGFOOD — a lane sheet as git.pp records, derived by the public gitpp-action in CI

**Run conclusion: SUCCESS.** The public Action derived the sheet's records in real GitHub CI, and its derived state agrees with the spike's local fold on **20 of 20 keys, zero divergences**.

## The artefacts

- **Repo:** https://github.com/patchwork-quilt/gitpp-dogfood-sheet (public, `main` @ `c9e333c`)
  - `.gitpp/records/` — 6 records generated fresh by the spike's `sheet_to_records.py` from the `sheet-reused` fixture in SuperInstance/lane-sheets: genesis `sheet-sheet-reused` + `cell-input.a`, `cell-input.b`, `cell-use.first`, `cell-use.second`, `cell-join.summary`. Parents are piping ancestry, per the spike mapping.
  - `README.md` — what the records encode and what the Action's report should show, written as a prediction *before* the first run.
  - `.github/workflows/gitpp.yml` — on push: `actions/checkout@v4`, then `patchwork-quilt/gitpp-action@v0.3.1` with `records-dir: .gitpp/records`, `project: sheet-reused`, default (summary) mode, per the Action's own README.
- **Workflow run:** https://github.com/patchwork-quilt/gitpp-dogfood-sheet/actions/runs/40361763003 — id `40361763003`, status completed, **conclusion: success**, 14 s, on push of `c9e333c`.
- **Local comparison fold:** the spike's `fold.py` (the labelled minimal Python port of `deriveLegacy` semantics) over exactly the generated record files, run before the push: 6 records → 20 state keys, 0 conflicts, 0 orphans.

## The Action's report (quoted in full from the run log)

```text
# git.pp state — sheet-reused
> Advisory — a mechanical derivation under the fold's rules, not an approval. A winner means precedence, not correctness or authorisation. This report never gates a merge.
> How a winner is chosen: kind first (override beats task beats witness); within a kind, a record that descends from a rival supersedes it; any remaining tie breaks on ancestry — ancestors are all transitive ancestors, counted once each, excluding the record itself: most intent ancestors (task and override records) wins, then fewest witness ancestors, then smallest id. A record's reason is its author's note, never an input to the fold.

Commit `c9e333c` · 6 records · 20 keys · 0 conflict(s) · 0 orphan(s)

## State

- `cell.input.a.def` = {"value":"the active ledger"}
- `cell.input.a.inputs` = {}
- `cell.input.a.kind` = value
- `cell.input.b.def` = {"value":"only the piping is public"}
- `cell.input.b.inputs` = {}
- `cell.input.b.kind` = value
- `cell.join.summary.def` = {"template":"A: {{first}} | B: {{second}}"}
- `cell.join.summary.inputs` = {"first":"use.first","second":"use.second"}
- `cell.join.summary.kind` = prompt
- `cell.use.first.def` = {"bind":{"input.text":"text"},"output":"output.report","sheet":"word-frame"}
- `cell.use.first.inputs` = {"text":"input.a"}
- `cell.use.first.kind` = sheet
- `cell.use.second.def` = {"bind":{"input.text":"text"},"output":"output.report","sheet":"word-frame"}
- `cell.use.second.inputs` = {"text":"input.b"}
- `cell.use.second.kind` = sheet
- `sheet.id` = sheet-reused
- `sheet.lanes` = [{"cells":["input.a","use.first"],"id":"first"},{"cells":["input.b","use.second"],"id":"second"},{"cells":["join.summary"],"id":"join"}]
- `sheet.lanesheet` = 0.2
- `sheet.outputs` = ["join.summary"]
- `sheet.title` = The same inner sheet used by two outer cells: reuse is the plugin shape

> Mechanical resolution of labelled key conflicts only; the fold does not settle semantic conflicts. Digests authenticate content, not authorship. Arrival order is never an input. An orphan is a record whose parent is missing or did not itself derive.
```

## Fold-agreement verdict

**AGREEMENT — exact.** The Action's 20 printed state values were extracted from the run log and compared mechanically against the local fold's state (strings compared bare, objects/arrays as canonical compact JSON): **20/20 keys identical, 0 mismatches**; the counts line (6 records · 20 keys · 0 conflicts · 0 orphans) matches the local fold exactly. The prediction in the repo README held in full.

One nuance, recorded precisely: the qualifications line's three core sentences appear **verbatim** as predicted. The v0.3.1 renderer appends one further sentence to that line — *"An orphan is a record whose parent is missing or did not itself derive."* — a glossary addition from the legibility work, not present in the older qualifications text the prediction quoted. It changes no derived value; it is a renderer wording superset, flagged here because the prediction claimed verbatim closure of the line.

## Legibility — the workflow reads off the report

A reader who has never seen the sheet can reconstruct the workflow from the State section alone:

- Structure: `sheet.lanes` gives the three lanes and their cell order; `sheet.outputs` names the terminal cell.
- The reuse — the point of the fixture — is plain on the page: `cell.use.first.kind` = `sheet` and `cell.use.second.kind` = `sheet`, both defs naming `"sheet":"word-frame"` with `"output":"output.report"`, differing only in what they pipe in (`cell.use.first.inputs` = `{"text":"input.a"}` vs `cell.use.second.inputs` = `{"text":"input.b"}`) and in their bound source values (`"the active ledger"` vs `"only the piping is public"`).
- The join is one line away: `cell.join.summary` is a `prompt` whose inputs are exactly the two sheet cells' outputs and whose template is `A: {{first}} | B: {{second}}`.

## Proven vs argued

**Proven by this run:** a real lane sheet — nested, with one inner sheet invoked at two sites — can live in a public repository as nothing but git.pp records, and the *public* gitpp-action (the released v0.3.1 tag, running on GitHub's runners) derives from those records a state that (a) agrees key-for-key with the spike's independent local fold of the same records, and (b) is legible as the workflow it encodes. Sheet-as-records is not a local-spike claim any more; the artefact chain fixture → records → CI derivation is live and inspectable end to end.

**Not proven, and not part of this lane:** the gitpp-app surface path (Mapping B — a declared surface on a `gitpp/state` branch, proposals previews, the `git.pp surface` check) deriving these records; the Action's check mode (this run used summary mode only); and any claim about *executing* a workflow from the derived state — the fold yields the sheet's definition, and this dogfood shows the definition survives the records representation and CI derivation. Running it remains the lane-sheets interpreter/host's job, upstream of the fold.

*SuperInstance. Companion files in this directory: `local-fold.json` (the pre-push local fold), `run-40361763003.log` (the full Actions log), `comparison.json` (the mechanical diff result).*
