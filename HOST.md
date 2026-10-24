# Lane Sheets — the Host Layer

Lane-sheet 0.1 names its providers and never binds them: an `llm`
cell carries only input ports, a `tool` cell only a name. The host
(`lanesheet/host.py`) is the binding layer: it resolves those names
to real providers, runs a sheet end-to-end against them, and emits
the same canonical trace format as the reference interpreter — plus a
header that keeps the two worlds unmistakable.

## The two-tier law, as it applies here

- **Tier 1 — conformance.** `run_conformance.py`, the fixtures, and
  the golden traces run on the deterministic stubs in
  `lanesheet/runtime.py` only. Byte-exact, reproducible, quarantined:
  the host never touches this path, and this path never sees a live
  model. It passes 14/14, untouched.
- **Tier 2 — live runs.** A host run is *evidence of a run*, not a
  conformance object. Live model output is nondeterministic, so no
  host trace is ever compared byte-for-byte with anything. Every host
  trace opens with a header record naming the run and every provider
  and model behind it:

  ```json
  {"bindings":{"llm":{"model":"MiniMax-Text-01","provider":"minimax"}},"kind":"host-header","live":true,"run":"live","sheet":"live-minimax"}
  ```

  A trace without this header is not a host trace; a header claiming
  `"live":true` while bound only to stubs is mislabelled and the
  checker rejects it. `run_host_check.py` validates a host trace
  *structurally*: header present and honest, records are exactly the
  run's cells in the interpreter's trace order (interior sections
  included), every `inputs_hash` recomputes, each cell's inputs equal
  what its piping sources produced earlier in the same trace, and a
  sheet cell's boundary output equals the interior output it
  declares. Structure, never content.

## Binding config

A JSON object with one `bindings` key. Keys are the names cells
carry: a tool cell's `tool` name, and the literal name `"llm"` for
llm cells — unless a binding is keyed by a specific cell id, which
wins for that cell. Each binding names a `provider`, an optional
`model`, and optional `params`. An unbound name is a named refusal
(`UnboundName`), never a silent default.

```json
{"bindings": {"llm": {"provider": "minimax", "model": "MiniMax-Text-01",
                      "params": {"max_tokens": 300, "temperature": 0.7}}}}
```

Providers in this build:

- **`minimax`** — llm cells, via the MiniMax connector's documented
  route: the stored `custom.minimax` credential is attached to the
  request as a surrogate by the connector's `dynamic_credentials`
  helper, restricted to `api.minimax.io`. No key is read, printed,
  logged, or written to any file by this code.
- **`stub`** — the runtime's deterministic stubs behind the provider
  interface; serves tool names, and llm cells for dry host runs
  (header then reads `"live":false, "run":"host-stub"`, and the body
  matches the conformance golden for the same sheet — the host
  exercises the piping without perturbing tier 1).

## The live example

```bash
python3 -m lanesheet.host examples/live-minimax.sheet.json examples/minimax.bindings.json
python3 run_host_check.py examples/live-minimax.trace.jsonl examples/live-minimax.sheet.json
```

`examples/live-minimax.sheet.json` is a four-cell sheet (value →
prompt → llm → prompt); `examples/live-minimax.trace.jsonl` is a
captured real run against MiniMax-Text-01. Re-running the first
command makes a fresh live call and will produce different llm
output — that is expected, and it is why the checker validates
structure rather than bytes.

## Nesting: `sheet` cells under the host

The host runs nested sheets with exactly the interpreter's
semantics — the recursion is the same shape, rung by rung:

- A `sheet` cell runs its referenced sheet as a unit. The trace
  shows ONE boundary line for the cell (its piped inputs, the
  declared boundary output), followed immediately by the interior
  section: the interior sheet's trace lines, cell ids prefixed with
  the sheet cell's id (`wrap.answer/reasoning.prompt`), prefixes
  accumulating per rung. With stub bindings, a host trace's body is
  byte-identical to the conformance golden for the same sheet.
- **The library convention.** References are bare names resolved
  against a sheet library of `<name>.sheet.json` files: by default
  the sheet's own directory (the interpreter CLI's convention), or
  the directory named by `--library DIR`:

  ```bash
  python3 -m lanesheet.host <sheet.json> <bindings.json> [--library DIR]
  ```

- **Bindings reach the interior.** An `llm` or `tool` cell inside an
  interior sheet resolves through the same host bindings, by the
  same rule: a binding keyed by cell id applies to that id in
  whichever sheet document declares it; otherwise the cell's name
  decides. The header names every binding the run resolves to at any
  rung, interiors included — a live provider used only two rungs
  down still marks the run `"live":true` and is named.
- **Refusals are the shared ones.** Validation is `common.py`'s,
  unchanged: a reference cycle is `RecursiveSheetRef`, a reference
  the supplied library cannot resolve is `UnresolvedSheetRef`, the
  depth cap is `SheetNestingTooDeep` — by name, before any cell
  runs, at every rung.

The nested live example (outer sheet invokes an inner sheet whose
`llm` cell binds to MiniMax):

```bash
python3 -m lanesheet.host examples/live-nested.sheet.json examples/minimax.bindings.json
python3 run_host_check.py examples/live-nested.trace.jsonl examples/live-nested.sheet.json
```

## Honest limits

- One provider serves llm cells (MiniMax); tool cells bind only to
  the stub provider in this build — no real tool bindings yet.
- No streaming: a cell's output is the provider's complete reply.
- No retries, no timeout policy beyond a single 120 s request
  timeout; a provider failure refuses the run with a named
  `ProviderError` and no partial trace is emitted.
- No concurrency: cells still execute one by one in canonical order,
  exactly as the interpreter does.
- Sheets are validated by the shared validator in
  `lanesheet/common.py` — tool names are still restricted to the
  stub catalogue (`search`, `wordcount`, `lookup`) until the spec
  grows real tool declarations.
