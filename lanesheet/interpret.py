"""Reference interpreter for SuperInstance lane-sheets.

Executes a sheet with the deterministic stub providers from
`lanesheet.runtime` and emits the canonical execution trace -- one JSON
line per cell, in canonical order (SPEC section 6). The trace is the
conformance object: any other engine (the LangGraph lifter, a future
port) is correct exactly insofar as its trace matches this one
byte-for-byte.

Like a spreadsheet recalculating, every cell in the sheet computes
exactly once, whether or not anything downstream consumes it. Branch
cells select a value from two fully evaluated arms; lane-sheet 0.1 has
no notion of a cell not running (SPEC section 5).

Usage: python -m lanesheet.interpret <sheet.json>
"""

import sys

from . import common, runtime


def evaluate_cell(cell, values):
    """Compute one cell's output from the already-computed values map."""
    kind = cell["kind"]
    inputs = {port: values[src] for port, src in cell.get("inputs", {}).items()}
    if kind == "value":
        output = cell["value"]
    elif kind == "prompt":
        output = runtime.render_template(cell["template"], inputs)
    elif kind == "llm":
        try:
            output = runtime.llm_complete(inputs["prompt"], inputs.get("system"))
        except runtime.StubError as exc:
            raise common.LaneSheetError(exc.name, f"cell {cell['id']!r}: {exc}") from exc
    elif kind == "tool":
        try:
            output = runtime.call_tool(cell["tool"], inputs)
        except runtime.StubError as exc:
            raise common.LaneSheetError(exc.name, f"cell {cell['id']!r}: {exc}") from exc
    elif kind == "branch":
        marker = ("equals" in cell, cell.get("equals"))
        output = runtime.select_branch(inputs["cond"], inputs["then"], inputs["else"], marker)
    else:  # pragma: no cover - validation guarantees a known kind
        raise common.LaneSheetError("UnknownCellKind", f"cell {cell['id']!r}: {kind!r}")
    return inputs, output


def run_sheet(sheet):
    """Validate and execute a parsed sheet. Returns the trace lines."""
    common.validate_sheet(sheet)
    values = {}
    lines = []
    for cell in common.canonical_order(sheet):
        inputs, output = evaluate_cell(cell, values)
        values[cell["id"]] = output
        lines.append(runtime.make_trace_line(cell["id"], cell["kind"], inputs, output))
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m lanesheet.interpret <sheet.json>", file=sys.stderr)
        return 2
    try:
        sheet = common.load_sheet(argv[0])
        lines = run_sheet(sheet)
    except common.LaneSheetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
