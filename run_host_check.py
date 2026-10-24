#!/usr/bin/env python3
"""Structural validation of a lane-sheet HOST (live-run) trace.

A host trace is evidence of a real run, not a conformance object:
live model output is nondeterministic, so nothing here compares
outputs against goldens or against the stub interpreter. What this
checker DOES establish, from the trace and the sheet alone:

  1. the trace opens with a host header record (kind "host-header")
     marking the run live, naming the sheet, and naming every
     provider (and model) that produced it -- a trace without this
     header is not a host trace, and a header claiming "live" while
     every resolved binding is the stub is mislabelled. A sheet tree
     with no provider cells (no llm/tool anywhere, interiors
     included) honestly resolves no bindings: its header must name
     none, and the checker verifies that claim against the sheet;
  2. the remaining records are exactly the run's cells, in the
     interpreter's trace order: the sheet's cells in canonical order
     (SPEC section 6), with each `sheet` cell's boundary record
     followed immediately by its interior section (interior cell ids
     prefixed by the sheet cell's id, rung by rung). A `sheet` cell
     in `each` mode (0.3) is followed by one interior section per
     element, in element order, prefixed `<cell>[<i>]/`. Every record
     carries exactly the keys {cell, inputs, inputs_hash, kind,
     output};
  3. every inputs_hash recomputes from its inputs (SHA-256 over the
     canonical encoding, lanesheet.runtime.inputs_hash);
  4. value flow is internally consistent: each record's inputs are
     exactly the outputs its piping sources produced earlier in this
     same trace; a sheet cell's boundary output equals the interior
     output it declares, and each bound interior `value` cell's
     recorded output equals the value the boundary record piped in.

Usage: python3 run_host_check.py <trace.jsonl> <sheet.json>
Exit 0 and "HOST CHECK PASS" when every check holds.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lanesheet import common, runtime  # noqa: E402

TRACE_KEYS = {"cell", "inputs", "inputs_hash", "kind", "output"}


def _tree_has_provider_cells(sheet, resolve):
    """True iff the sheet tree (transitively) contains llm/tool cells.

    Decides what an honest header may claim: a run of a provider-free
    sheet resolves no bindings, so its header names none -- and must
    name none. Any other sheet's run resolves at least one.
    """
    for cell in common.canonical_order(sheet):
        if cell["kind"] in ("llm", "tool"):
            return True
        if cell["kind"] == "sheet":
            inner = common.load_ref(resolve, cell["sheet"])
            if _tree_has_provider_cells(inner, resolve):
                return True
    return False


def _consume(sheet, resolve, prefix, records, idx, problems):
    """Match records[idx:] against this sheet's expected trace section.

    Returns (next unconsumed index, values) where values maps this
    rung's cell ids to the outputs the trace records for them. A
    `sheet` cell consumes its boundary record, then its interior
    section (recursion, prefix accumulated), then has its boundary
    claims checked against the interior values it produced.
    """
    values = {}
    for cell in common.canonical_order(sheet):
        cell_id = cell["id"]
        where = f"record {idx} (cell {prefix + cell_id!r})"
        if idx >= len(records):
            problems.append(f"trace ends early: missing {where}")
            return idx, values
        record = records[idx]
        idx += 1
        if not isinstance(record, dict) or set(record) != TRACE_KEYS:
            problems.append(f"{where}: keys are not exactly {sorted(TRACE_KEYS)}")
            continue
        if record["cell"] != prefix + cell_id or record["kind"] != cell["kind"]:
            problems.append(
                f"{where}: trace has cell {record['cell']!r} kind {record['kind']!r} "
                "-- not the interpreter's trace order"
            )
            continue
        if record["inputs_hash"] != runtime.inputs_hash(record["inputs"]):
            problems.append(f"{where}: inputs_hash does not recompute")
        sources = cell.get("inputs", {})
        if all(src in values for src in sources.values()):
            expected_inputs = {port: values[src] for port, src in sources.items()}
            if record["inputs"] != expected_inputs:
                problems.append(
                    f"{where}: inputs do not match the outputs its piping sources produced"
                )
        else:
            problems.append(f"{where}: a piping source produced no record earlier in this trace")
        values[cell_id] = record["output"]
        if cell["kind"] == "sheet":
            inner = common.load_ref(resolve, cell["sheet"])
            if "each" in cell:
                idx = _consume_each(cell, inner, resolve, prefix, record, records, idx, problems, where)
            else:
                idx, inner_values = _consume(
                    inner, resolve, prefix + cell_id + "/", records, idx, problems
                )
                for target, port in cell.get("bind", {}).items():
                    if target in inner_values and inner_values[target] != record["inputs"].get(port):
                        problems.append(
                            f"{where}: bound interior cell {target!r} recorded "
                            f"{inner_values[target]!r}, but the boundary piped "
                            f"{record['inputs'].get(port)!r} in"
                        )
                if "output" in cell:
                    targets = [cell["output"]]
                    expected_output = inner_values.get(cell["output"])
                else:
                    targets = list(cell["outputs"].values())
                    expected_output = {
                        name: inner_values[target]
                        for name, target in cell["outputs"].items()
                        if target in inner_values
                    }
                if all(t in inner_values for t in targets) and record["output"] != expected_output:
                    problems.append(
                        f"{where}: boundary output does not equal the interior output it declares"
                    )
    return idx, values


def _consume_each(cell, inner, resolve, prefix, record, records, idx, problems, where):
    """Match the per-element sections of an `each` cell (0.3).

    The boundary record is already consumed. What follows must be one
    interior section per element of the list the boundary record
    piped into the `each` port, in element order, ids prefixed
    `<cell>[<i>]/`. Each section is checked like any interior
    section; the bound element cell's recorded output in section i
    must equal element i, the fixed bindings must match the boundary
    record's inputs, and the boundary output must equal the declared
    interior outputs collected in element order.
    """
    cell_id = cell["id"]
    each_port = cell["each"]
    elements = record["inputs"].get(each_port)
    if not isinstance(elements, list):
        problems.append(
            f"{where}: 'each' port {each_port!r} was piped a non-list "
            f"({type(elements).__name__}); no sections can be matched"
        )
        return idx
    bind = cell.get("bind", {})
    element_targets = [t for t, p in bind.items() if p == each_port]
    element_target = element_targets[0] if element_targets else None
    fixed = {t: p for t, p in bind.items() if p != each_port}
    runs = []
    for i, element in enumerate(elements):
        idx, inner_values = _consume(
            inner, resolve, f"{prefix}{cell_id}[{i}]/", records, idx, problems
        )
        for target, port in fixed.items():
            if target in inner_values and inner_values[target] != record["inputs"].get(port):
                problems.append(
                    f"{where}: bound interior cell {target!r} in element {i} recorded "
                    f"{inner_values[target]!r}, but the boundary piped "
                    f"{record['inputs'].get(port)!r} in"
                )
        if (
            element_target is not None
            and element_target in inner_values
            and inner_values[element_target] != element
        ):
            problems.append(
                f"{where}: element cell {element_target!r} in element {i} recorded "
                f"{inner_values[element_target]!r}, but element {i} is {element!r}"
            )
        runs.append(inner_values)
    if "output" in cell:
        targets = [cell["output"]]
        complete = all(cell["output"] in run for run in runs)
        expected_output = [run[cell["output"]] for run in runs] if complete else None
    else:
        targets = list(cell["outputs"].values())
        complete = all(t in run for run in runs for t in targets)
        expected_output = (
            {name: [run[target] for run in runs] for name, target in cell["outputs"].items()}
            if complete
            else None
        )
    if complete and record["output"] != expected_output:
        problems.append(
            f"{where}: boundary output does not equal the interior outputs "
            "it declares, collected in element order"
        )
    return idx


def check(trace_path, sheet_path):
    problems = []
    sheet = common.load_sheet(sheet_path)
    resolve = common.local_resolver(Path(sheet_path).parent)

    raw = Path(trace_path).read_text(encoding="utf-8").splitlines()
    if not raw:
        return ["trace is empty"]
    try:
        records = [json.loads(line) for line in raw]
    except json.JSONDecodeError as exc:
        return [f"trace line does not parse as JSON: {exc}"]

    # 1. header
    header, body = records[0], records[1:]
    if not isinstance(header, dict) or header.get("kind") != "host-header":
        problems.append("first record is not a host header (kind != 'host-header')")
        header = {}
    else:
        if header.get("sheet") != sheet["id"]:
            problems.append(f"header names sheet {header.get('sheet')!r}, sheet id is {sheet['id']!r}")
        bindings = header.get("bindings")
        if not isinstance(bindings, dict):
            problems.append("header names no bindings")
            bindings = {}
        elif not bindings and _tree_has_provider_cells(sheet, resolve):
            problems.append("header names no bindings, but the sheet resolves provider cells")
        elif bindings and not _tree_has_provider_cells(sheet, resolve):
            problems.append("header names bindings, but the sheet resolves no provider cells")
        for key, desc in bindings.items():
            if not isinstance(desc, dict) or "provider" not in desc:
                problems.append(f"binding {key!r} does not name a provider")
            elif desc["provider"] != "stub" and "model" not in desc:
                problems.append(f"binding {key!r} (provider {desc['provider']!r}) does not name a model")
        if header.get("live") is True and all(
            d.get("provider") == "stub" for d in bindings.values() if isinstance(d, dict)
        ):
            problems.append("header claims a live run but every binding is the stub provider")

    # 2./3./4. body records: consume the expected trace shape,
    # recursing into interior sections rung by rung.
    consumed, _values = _consume(sheet, resolve, "", body, 0, problems)
    if consumed < len(body):
        problems.append(
            f"trace has {len(body) - consumed} record(s) beyond the run's expected trace shape"
        )
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python3 run_host_check.py <trace.jsonl> <sheet.json>", file=sys.stderr)
        return 2
    try:
        problems = check(argv[0], argv[1])
    except common.LaneSheetError as exc:
        print(f"HOST CHECK FAIL: sheet refused: {exc}")
        return 1
    if problems:
        for problem in problems:
            print(f"HOST CHECK FAIL: {problem}")
        return 1
    print("HOST CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
