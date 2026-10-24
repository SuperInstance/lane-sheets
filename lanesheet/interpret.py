"""Reference interpreter for SuperInstance lane-sheets.

Executes a sheet with the deterministic stub providers from
`lanesheet.runtime` and emits the canonical execution trace -- one JSON
line per cell, in canonical order (SPEC section 6). The trace is the
conformance object: any other engine (the LangGraph lifter, a future
port) is correct exactly insofar as its trace matches this one
byte-for-byte.

Like a spreadsheet recalculating, every cell in the sheet computes
exactly once, whether or not anything downstream consumes it. Branch
cells select a value from two fully evaluated arms; the format has no
notion of a cell not running (SPEC section 5).

`sheet` cells (0.2, SPEC-AMENDMENT.md) run their referenced sheet as a
unit, one rung down: the trace shows the sheet cell as ONE line whose
inputs and output are the boundary values, followed immediately by the
interior sheet's trace section, its cell ids prefixed with the sheet
cell's id (`wrap.chain/reasoning.prompt`). The outer run's values
never contain interior values other than the declared boundary
output -- the interior is sovereign; only the piping crosses.

Usage: python -m lanesheet.interpret <sheet.json>
"""

import sys
from pathlib import Path

from . import common, runtime

_NO_OVERRIDE = object()


def evaluate_cell(cell, values, value_override=_NO_OVERRIDE):
    """Compute one cell's output from the already-computed values map.

    `value_override` is used only for `value` cells of a sub-sheet
    invocation whose constant was bound to a piped input: the cell
    computes the bound value in place of its constant.
    """
    kind = cell["kind"]
    inputs = {port: values[src] for port, src in cell.get("inputs", {}).items()}
    if kind == "value":
        output = cell["value"] if value_override is _NO_OVERRIDE else value_override
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


def _run(sheet, resolve, prefix, overrides):
    """Execute a validated sheet. Returns (trace lines, values).

    `prefix` is the accumulated sheet-cell path ("" at the top rung,
    "wrap.chain/" one rung down, and so on); every trace line's cell
    id carries it. `overrides` maps this invocation's bound interior
    `value` cells to the values piped in across the boundary.
    """
    values = {}
    lines = []
    for cell in common.canonical_order(sheet):
        cell_id = cell["id"]
        if cell["kind"] == "sheet":
            inputs = {port: values[src] for port, src in cell.get("inputs", {}).items()}
            inner = common.load_ref(resolve, cell["sheet"])
            inner_overrides = {
                target: inputs[port] for target, port in cell.get("bind", {}).items()
            }
            inner_lines, inner_values = _run(
                inner, resolve, prefix + cell_id + "/", inner_overrides
            )
            if "output" in cell:
                output = inner_values[cell["output"]]
            else:
                output = {
                    name: inner_values[target]
                    for name, target in cell["outputs"].items()
                }
            values[cell_id] = output
            lines.append(
                runtime.make_trace_line(prefix + cell_id, "sheet", inputs, output)
            )
            lines.extend(inner_lines)
            continue
        override = overrides.get(cell_id, _NO_OVERRIDE) if cell["kind"] == "value" else _NO_OVERRIDE
        inputs, output = evaluate_cell(cell, values, value_override=override)
        values[cell_id] = output
        lines.append(runtime.make_trace_line(prefix + cell_id, cell["kind"], inputs, output))
    return lines, values


def run_sheet(sheet, resolve=None):
    """Validate and execute a parsed sheet. Returns the trace lines."""
    common.validate_sheet(sheet, resolve=resolve)
    lines, _values = _run(sheet, resolve, "", {})
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m lanesheet.interpret <sheet.json>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    try:
        sheet = common.load_sheet(path)
        lines = run_sheet(sheet, resolve=common.local_resolver(path.parent))
    except common.LaneSheetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
