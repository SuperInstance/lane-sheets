# Lane Sheets × git.pp — the spike

**A lane sheet, carried as git.pp records: the sheet becomes declared
state, its state a fold, and installing it becomes landing records.**
SuperInstance. This note records the mapping decisions, what a
conflict means in this representation, and the plugin consequence.
What the check proves is separated from what is argument throughout —
the split is §5.

Code: `sheet_to_records.py` (sheet → records), `records_to_sheet.py`
(records → fold → sheet), `fold.py` (a labelled minimal port of the
fold's derive semantics, from `patchwork-quilt/git.pp-action`
`lib/fold.ts`, itself a byte-identical vendor of git.pp-ng
`src/fold.ts` @ `e296feab`), `run_spike_check.py` (the proof).
Records are emitted one per file into a records directory — the
`.gitpp/records` layout the git.pp App and Action already consume.

## 1. What a cell becomes

One record per cell, plus one genesis record per sheet:

| Sheet fact | Record | Effects (declared keys) |
|---|---|---|
| the sheet itself | `sheet-<sheet-id>`, kind `task`, no parents | `sheet.id`, `sheet.lanesheet`, `sheet.title`*, `sheet.outputs`*, `sheet.lanes` |
| a cell `<id>` | `cell-<cell-id>`, kind `task` | `cell.<id>.kind`, `cell.<id>.def`, `cell.<id>.inputs` |

\* only when the sheet carries them.

- `cell.<id>.def` is the kind-specific payload **only** — the cell
  object minus `id`, `kind`, and `inputs` (`value`, `template`,
  `tool`, `equals`, or for a `sheet` cell its `sheet`/`bind`/
  `output(s)`). Kind gets its own key so that a disagreement *about
  the kind alone* is a legible, separately contestable fact; the
  payload gets its own key so a redefinition is one contested value,
  not a smear across fields.
- `cell.<id>.inputs` is the port map `{port: source cell id}`,
  carried as data.
- `sheet.lanes` is the structure: `[{id, cells: [ids in order]}]`.
  Lane membership and lane order live here, as **data on the genesis
  record** — deliberately not in ancestry (see §2).
- A referenced sheet (a `sheet` cell naming `word-frame`) stays a
  **reference by name**. Its cells are not inlined into the outer
  sheet's records; in a full install its own genesis + cell records
  land alongside, as a separate record set converted by the same
  tool, and resolution stays by-name exactly as the lane-sheet
  library resolver already works. (In the spike's check, the
  interpreter resolves `word-frame` from the fixture library.)

Cell records are kind `task`: a definition is a decision that
carries intent, not an observation. That single choice is what makes
the conflict semantics of §3 land the way they do.

## 2. What parents mean here — the decision

**Parents are piping ancestry.** A cell record's parents are the
records of the cells it pipes from — its inputs' sources,
deduplicated and sorted — or the genesis record when it pipes from
nothing. Consequences, each deliberate:

- The record DAG is **isomorphic to the sheet's dataflow DAG**. The
  fold's machinery — ancestry dominance, the cleanliness tie-break
  counted over intent ancestors — therefore operates on the piping
  graph itself, not on an artificial chain laid over it.
- Cycle detection aligns: a piping cycle (already refused by the
  sheet validator as `CycleDetected`) is a parent cycle in records,
  whose members the fold holds as orphans. The two engines refuse
  the same shape for the same reason.
- The whole sheet is one closure rooted at genesis, matching the
  record layout git.pp repos already use.

The alternative — chaining each cell to the previous cell **in lane
order** — was rejected: lane adjacency is presentation, not
derivation. A cell does not *see* its lane neighbour; making it a
parent would fabricate ancestry and distort every tie-break the
fold later computes over these records. "Both" inherits the same
defect. Lane order is fully preserved — as the `sheet.lanes`
effect, where data belongs.

One honest seam: parents are a **set of ids**, so they cannot carry
the port map (two ports may draw from one source cell; the parent
appears once). The port-level truth therefore lives in the
`cell.<id>.inputs` effect, and the reconstruction reads it from
there. Parents say who a definition *saw*; the inputs effect says
what it *pipes*. In the base conversion the two agree by
construction; under contention (§3) they can diverge, and that
divergence is meaningful — an override may redefine a cell's
payload while leaving its piping record untouched, or vice versa.

## 3. What a conflict looks like

A conflict in this representation is two records setting the same
`cell.<id>.def` (or `.kind`, or `.inputs`) to different values. The
fold decides it exactly as it decides any git.pp key, and the
reconstruction follows the fold — there is no second arbiter:

1. **Class first.** An `override`-kind record beats the `task`-kind
   cell record outright, ancestry regardless: overriding a cell is
   what the override class *is*.
2. **Ancestry within class.** A redefinition that **descends from**
   the original cell record — it saw the definition and built on
   it — dominates it. Because parents are piping, "descends from"
   here typically means the new record hangs off the cell it
   redefines (or off anything downstream of it).
3. **Tie-break.** Unrelated same-class redefinitions (two plugins
   both defining the cell, neither built on the other) fall to the
   cleanest chain: most intent ancestors, then fewest witness
   ancestors, then smallest record id. Deterministic, and — like
   every git.pp derivation — a statement about precedence, not
   correctness.

All three behaviours are **executed in the check**, not just
asserted here (probes 4–6 of `run_spike_check.py`): the override
wins and the reconstructed sheet carries its template; the
descendant wins by dominance; the sibling loses and is named as
loser in the conflict entry. The conflict itself is never hidden:
the fold reports `{key, winner, losers}` for every contested key,
and `records_to_sheet.py` prints them.

What a repo would see **today, with no new code**: the git.pp App's
advisory Check (`git.pp state`) renders whatever keys the records
carry — the folded `sheet.*` and `cell.*` values as the derived
state, and for a contested cell a conflict line naming the winner,
the losers, and the ancestry that decided. A repo whose records
carry a sheet would read, in its Check, as a sheet definition with
its contested cells listed — the qualifications line still attached:
mechanical resolution of labelled key conflicts only; a winner
means precedence, not correctness.

## 4. The plugin consequence, stated precisely

- **Installing a plugin sheet = landing its records.** The plugin's
  genesis + cell records join the repo's record set; the fold over
  the union *is* the installed state. There is no registry, no load
  order, no install step distinct from the records arriving.
- **Overriding one cell of an installed plugin = one override
  record** setting `cell.<id>.def` (kind `override`, parented on
  the plugin's cell record). It wins by class, it is attributable
  (the record is signed by its presence in git history like any
  other), and removing the override record restores the plugin's
  definition exactly — the fold re-derives; nothing was mutated.
- **Two plugins defining the same cell** is §3 case 3: a named
  conflict in the Check, resolved by the cleanest-chain tie-break,
  with the loser preserved in the report — never a silent overwrite
  and never an import-order accident.
- **Uninstalling is not a fold operation.** The fold has no
  deletion semantics (retraction remains an upstream design spike,
  git.pp-ng PR #16, undecided); today a plugin is removed by
  removing its record files — a git operation on the repo, outside
  the fold — or superseded cell-by-cell by overrides. This spike
  does not pretend otherwise.

## 5. Proven vs argued

**Proven by `run_spike_check.py` (11/11, executed):**

- Round-trip exactness on `linear-chain` and `sheet-reused`:
  sheet → records → fold → sheet′ canonical-equals the original
  (lane-sheets canonical JSON), and the interpreter's trace on
  sheet′ is byte-identical to each fixture's golden trace.
- Arrival-order independence: the same records fed shuffled derive
  the identical state.
- The uncontested conversions produce zero conflicts and zero
  orphans.
- The three conflict behaviours of §3, each as an executed probe
  with the reconstructed sheet checked, not just the fold state.

**Argument (sound, but not executed here):**

- Everything about the App's Check in §3's last paragraph: the
  renderer is key-agnostic and these keys are ordinary declared
  keys, but the spike did not post a live Check against a
  sheet-carrying repo.
- The plugin mechanics of §4 follow from the fold semantics + the
  probes (an override record is an override record), but no
  multi-plugin record set was folded in this spike.
- `fold.py` is a minimal port of derive's semantics, labelled as
  such; it is not verified against the upstream conformance corpus,
  and the spike's claims need only the ported subset (index,
  orphans, per-key winner, conflicts).

## 6. Running it

```bash
python3 sheet_to_records.py <sheet.json> <records-dir>
python3 records_to_sheet.py <records-dir> [out.sheet.json]
python3 run_spike_check.py        # SUMMARY: 11/11 PASS
```
