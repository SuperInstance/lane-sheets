"""The LangGraph lifter: lane-sheet -> standalone LangGraph module.

This is the upward compiler leg the shelf study found absent
(DOSSIER.md section 5c): lifts on the Quilt shelf are hand ports proven
equal by hash; here the lift is generated code, proven equal by trace.

The lifter validates the sheet first, with the same named refusals as
the interpreter -- an unsupported sheet produces NO module, never a
silently wrong one. The generated module:

  * embeds `lanesheet/runtime.py` verbatim, so the stub providers and
    the canonical trace format it runs against are the exact code the
    reference interpreter used;
  * builds a LangGraph StateGraph with one node per cell; cell values
    flow through the graph state (the piping), and each node appends
    its canonical trace line;
  * wires each node with a barrier edge over its trigger set -- its
    piped input sources plus its predecessor in canonical order -- so
    execution follows the sheet's canonical order (SPEC section 6)
    regardless of scheduler detail, exactly as the interpreter does;
  * for a `sheet` cell (0.2, SPEC-AMENDMENT.md), emits the referenced
    sheet as its own StateGraph unit -- one unit per invocation site,
    because port bindings are per-site -- and a node that invokes it
    with the bound values as seeds, takes the declared boundary
    output, and re-prefixes the interior trace lines with the sheet
    cell's id. The subgraph is opaque to the outer graph exactly as
    the interior sheet is opaque to the outer sheet: only seeds go in,
    only the boundary output and the prefixed trace come out.

Usage: python -m lanesheet.lift_langgraph <sheet.json> <out.py>
"""

import re
import sys
from pathlib import Path

from . import common


def _suffix(site_path):
    return re.sub(r"\W", "_", site_path)


class _Builder:
    """Accumulates the generated module, one graph unit per sheet site."""

    def __init__(self, resolve):
        self.resolve = resolve
        self.parts = []
        self.node_names = set()

    def _node_source(self, cell, site_path, bound):
        """Python source for one cell's LangGraph node function."""
        cell_id = cell["id"]
        kind = cell["kind"]
        qualified = f"{site_path}/{cell_id}" if site_path else cell_id
        name = common.node_name(qualified)
        if name in self.node_names:
            raise common.LaneSheetError(
                "NodeNameCollision",
                f"cell {qualified!r} collides as graph node name {name!r}",
            )
        self.node_names.add(name)
        inputs = cell.get("inputs", {})
        lines = [f"def {name}(state):", '    values = state["values"]']
        if inputs:
            pairs = ", ".join(f"{port!r}: values[{src!r}]" for port, src in inputs.items())
            lines.append(f"    inputs = {{{pairs}}}")
        else:
            lines.append("    inputs = {}")
        if kind == "value":
            if cell_id in bound:
                lines.append(
                    f"    output = values[{cell_id!r}] if {cell_id!r} in values "
                    f"else {cell['value']!r}"
                )
            else:
                lines.append(f"    output = {cell['value']!r}")
        elif kind == "prompt":
            lines.append(f"    output = render_template({cell['template']!r}, inputs)")
        elif kind == "llm":
            lines.append('    output = llm_complete(inputs["prompt"], inputs.get("system"))')
        elif kind == "tool":
            lines.append(f"    output = call_tool({cell['tool']!r}, inputs)")
        elif kind == "branch":
            marker = (True, cell["equals"]) if "equals" in cell else (False, None)
            lines.append(
                f"    output = select_branch(inputs['cond'], inputs['then'], "
                f"inputs['else'], {marker!r})"
            )
        elif kind == "sheet":
            sub = _suffix(qualified)
            seeds = ", ".join(
                f"{target!r}: inputs[{port!r}]"
                for target, port in cell.get("bind", {}).items()
            )
            lines.append(f"    _seeds = {{{seeds}}}")
            lines.append(f"    _inner_values, _inner_lines = run_sub_{sub}(_seeds)")
            if "output" in cell:
                lines.append(f"    output = _inner_values[{cell['output']!r}]")
            else:
                pairs = ", ".join(
                    f"{out_name!r}: _inner_values[{target!r}]"
                    for out_name, target in cell["outputs"].items()
                )
                lines.append(f"    output = {{{pairs}}}")
            lines.append(f"    line = make_trace_line({cell_id!r}, 'sheet', inputs, output)")
            lines.append("    _lines = [line]")
            lines.append("    for _l in _inner_lines:")
            lines.append("        _rec = json.loads(_l)")
            lines.append(f"        _rec['cell'] = {cell_id!r} + '/' + _rec['cell']")
            lines.append("        _lines.append(canonical_json(_rec))")
            lines.append(
                f'    return {{"values": {{{cell_id!r}: output}}, "trace_lines": _lines}}'
            )
            return "\n".join(lines)
        lines.append(f"    line = make_trace_line({cell_id!r}, {kind!r}, inputs, output)")
        lines.append(f'    return {{"values": {{{cell_id!r}: output}}, "trace_lines": [line]}}')
        return "\n".join(lines)

    def emit_unit(self, sheet, site_path, bound):
        """Emit one graph unit: subgraph units first, then nodes, build, run."""
        ordered = common.canonical_order(sheet)
        index_of = {c["id"]: i for i, c in enumerate(ordered)}

        for cell in ordered:
            if cell["kind"] == "sheet":
                inner = common.load_ref(self.resolve, cell["sheet"])
                sub_path = f"{site_path}/{cell['id']}" if site_path else cell["id"]
                self.emit_unit(inner, sub_path, frozenset(cell.get("bind", {})))

        for cell in ordered:
            self.parts.append(self._node_source(cell, site_path, bound))
            self.parts.append("")
            self.parts.append("")

        build_name = "build" if not site_path else f"build_sub_{_suffix(site_path)}"
        run_name = "run" if not site_path else f"run_sub_{_suffix(site_path)}"
        parts = self.parts
        parts.append(f"def {build_name}():")
        parts.append("    graph = StateGraph(SheetState)")
        for cell in ordered:
            qualified = f"{site_path}/{cell['id']}" if site_path else cell["id"]
            parts.append(
                f"    graph.add_node({cell['id']!r}, {common.node_name(qualified)})"
            )
        for i, cell in enumerate(ordered):
            if i == 0:
                parts.append(f"    graph.add_edge(START, {cell['id']!r})")
                continue
            triggers = {src for src in cell.get("inputs", {}).values()}
            triggers.add(ordered[i - 1]["id"])  # canonical-order predecessor
            if len(triggers) == 1:
                parts.append(f"    graph.add_edge({triggers.pop()!r}, {cell['id']!r})")
            else:
                ordered_triggers = sorted(triggers, key=lambda cid: index_of[cid])
                parts.append(
                    f"    graph.add_edge({ordered_triggers!r}, {cell['id']!r})"
                    "  # barrier: waits for all"
                )
        parts.append(f"    graph.add_edge({ordered[-1]['id']!r}, END)")
        parts.append("    return graph.compile()")
        parts.append("")
        parts.append("")
        parts.append(f"def {run_name}({'seeds' if site_path else ''}):")
        parts.append(f"    app = {build_name}()")
        if site_path:
            parts.append(
                '    final = app.invoke({"values": dict(seeds), "trace_lines": []}, '
                'config={"recursion_limit": 10000})'
            )
            parts.append('    return final["values"], final["trace_lines"]')
        else:
            parts.append(
                '    final = app.invoke({"values": {}, "trace_lines": []}, '
                'config={"recursion_limit": 10000})'
            )
            parts.append('    return final["trace_lines"]')
        parts.append("")
        parts.append("")


def lift(sheet, resolve=None):
    """Validate a parsed sheet and return the generated module source."""
    common.validate_sheet(sheet, resolve=resolve)
    runtime_src = Path(__file__).with_name("runtime.py").read_text(encoding="utf-8")

    parts = [
        f'"""GENERATED by lanesheet.lift_langgraph -- do not edit by hand.\n\n'
        f"Lane sheet: {sheet['id']!r} (lane-sheet {sheet['lanesheet']}).\n"
        f"Standalone LangGraph module. Running it with the embedded stub\n"
        f"providers reproduces the sheet's canonical execution trace.\n"
        f'"""\n',
        "# --- embedded lanesheet runtime (verbatim) ---",
        runtime_src.rstrip("\n"),
        "# --- end embedded runtime ---\n",
        "import operator",
        "from typing import Annotated, TypedDict",
        "",
        "from langgraph.graph import END, START, StateGraph",
        "",
        "",
        "def _merge_values(a, b):",
        "    merged = dict(a or {})",
        "    merged.update(b or {})",
        "    return merged",
        "",
        "",
        "class SheetState(TypedDict):",
        "    values: Annotated[dict, _merge_values]",
        "    trace_lines: Annotated[list, operator.add]",
        "",
        "",
    ]
    builder = _Builder(resolve)
    builder.emit_unit(sheet, "", frozenset())
    parts.extend(builder.parts)
    parts.append('if __name__ == "__main__":')
    parts.append("    for _line in run():")
    parts.append("        print(_line)")
    parts.append("")
    return "\n".join(parts)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python -m lanesheet.lift_langgraph <sheet.json> <out.py>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    try:
        sheet = common.load_sheet(path)
        source = lift(sheet, resolve=common.local_resolver(path.parent))
    except common.LaneSheetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    Path(argv[1]).write_text(source, encoding="utf-8")
    print(f"lifted {sheet['id']!r} -> {argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
