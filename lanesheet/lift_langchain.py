"""The LangChain lifter: lane-sheet -> standalone LangChain module.

The second upward target for the same sheet (the first is
lift_langgraph.py). Where LangGraph models the sheet's piping DAG
directly -- one node per cell, barrier edges for fan-in -- LangChain's
LCEL runnables model a *pipeline*: one value flowing through composed
stages. The lift therefore threads the sheet state (the values map
plus the trace lines) through a RunnableSequence in the sheet's
canonical order (SPEC section 6): the chain IS the canonical
linearization of the DAG, and the trace proves it execution-equal to
the interpreter and to the LangGraph lift, byte-for-byte.

Construct mapping (LANGCHAIN.md argues each line):

  * value / prompt / llm / tool cell -> one RunnableLambda stage
    over the state dict, its body the embedded runtime's own
    functions -- the same bodies the LangGraph nodes call;
  * branch cell -> RunnableBranch. LCEL's branch is lazy control
    flow, but a lane-sheet branch is *selection over two already
    computed arm values* (both arms are upstream cells, eagerly
    evaluated by their own stages), so laziness skips nothing: the
    condition runnable applies runtime.select_branch's rule, the
    two arm runnables each append the identical trace line with
    their arm's value selected;
  * a multi-source cell (a join) -> an ordinary stage. Runnable-
    Parallel is deliberately NOT used: its branches snapshot one
    shared input and return a keyed dict, while sheet piping lets
    any later cell draw from any earlier cell in any lane at mixed
    dependency levels -- there is no parallel decomposition of a
    shared-state DAG, and forcing one would betray the piping;
  * sheet cell -> an adapter RunnableLambda invoking the interior
    sheet's own RunnableSequence unit (one unit per invocation
    site, because port bindings are per-site), seeded with the
    bound values, taking the declared boundary output, and
    re-prefixing the interior trace -- the exact analogue of the
    LangGraph lifter's subgraph invocation;
  * sheet cell in `each` mode -> the fan-out carried by
    RunnableEach (RunnableLambda(...).map()): the stage validates
    the list via the embedded runtime (runtime.each_elements --
    the interpreter's own named refusals, raised before any
    element runs), maps the interior unit over the elements, and
    assembles the boundary line plus the indexed interior
    sections in element order.

The lifter validates the sheet first, with the same named refusals
as the interpreter. A construct with no LCEL expression in this
mapping is refused by name -- UnliftableToLangChain, with the
construct named -- and produces NO module, never a silently wrong
one.

The generated module embeds `lanesheet/runtime.py` verbatim, exactly
as the LangGraph lifter does, so the stub providers and the
canonical trace format are the code the sheet was checked against.
Requires langchain-core (the runnables) only -- not the full
langchain package.

Usage: python -m lanesheet.lift_langchain <sheet.json> <out.py>
"""

import re
import sys
from pathlib import Path

from . import common

_REFUSAL = "UnliftableToLangChain"


def _suffix(site_path):
    return re.sub(r"\W", "_", site_path)


class _Builder:
    """Accumulates the generated module, one chain unit per sheet site."""

    def __init__(self, resolve):
        self.resolve = resolve
        self.parts = []
        self.fn_names = set()

    def _register(self, name, qualified):
        if name in self.fn_names:
            raise common.LaneSheetError(
                "NodeNameCollision",
                f"cell {qualified!r} collides as generated function name {name!r}",
            )
        self.fn_names.add(name)
        return name

    def _inputs_lines(self, cell, indent="    "):
        inputs = cell.get("inputs", {})
        if inputs:
            pairs = ", ".join(f"{port!r}: values[{src!r}]" for port, src in inputs.items())
            return [f"{indent}inputs = {{{pairs}}}"]
        return [f"{indent}inputs = {{}}"]

    def _state_return(self, cell_id, line_expr, indent="    ", lines_expr=None):
        """Source lines returning the new state with the cell's line(s) appended."""
        if lines_expr is None:
            lines_expr = f"[{line_expr}]"
        return [
            f"{indent}return {{"
            f'"values": {{**values, {cell_id!r}: output}}, '
            f'"trace_lines": state["trace_lines"] + {lines_expr}}}'
        ]

    def _step_source(self, cell, site_path, bound):
        """Python source for one cell's chain stage (or branch triple)."""
        cell_id = cell["id"]
        kind = cell["kind"]
        qualified = f"{site_path}/{cell_id}" if site_path else cell_id
        name = self._register(common.node_name(qualified), qualified)
        inputs = cell.get("inputs", {})

        if kind == "branch":
            # Selection as RunnableBranch: the condition applies the
            # runtime's own selection rule to sentinel arms; each arm
            # runnable emits the trace line with its value selected.
            cond_name = self._register(name + "_cond", qualified)
            then_name = self._register(name + "_then", qualified)
            else_name = self._register(name + "_else", qualified)
            marker = (True, cell["equals"]) if "equals" in cell else (False, None)
            lines = [f"def {cond_name}(state):", '    values = state["values"]']
            lines += self._inputs_lines(cell)
            lines.append(
                f"    return select_branch(inputs['cond'], True, False, {marker!r})"
            )
            lines.append("")
            lines.append("")
            for arm_name, arm_port in ((then_name, "then"), (else_name, "else")):
                lines.append(f"def {arm_name}(state):")
                lines.append('    values = state["values"]')
                lines += self._inputs_lines(cell)
                lines.append(f"    output = inputs[{arm_port!r}]")
                lines.append(
                    f"    line = make_trace_line({cell_id!r}, 'branch', inputs, output)"
                )
                lines += self._state_return(cell_id, "line")
                lines.append("")
                lines.append("")
            return "\n".join(lines), ("branch", cond_name, then_name, else_name)

        lines = [f"def {name}(state):", '    values = state["values"]']
        lines += self._inputs_lines(cell)
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
        elif kind == "sheet":
            sub = _suffix(qualified)
            if "each" in cell:
                each_port = cell["each"]
                bind = cell.get("bind", {})
                element_target = next(t for t, p in bind.items() if p == each_port)
                fixed = ", ".join(
                    f"{target!r}: inputs[{port!r}]"
                    for target, port in bind.items()
                    if port != each_port
                )
                lines.append(f"    _items = each_elements(inputs[{each_port!r}])")
                lines.append(f"    _fixed = {{{fixed}}}")
                lines.append(
                    f"    _one = RunnableLambda("
                    f"lambda _el, _f=_fixed: run_sub_{sub}({{**_f, {element_target!r}: _el}}))"
                )
                lines.append("    _runs = _one.map().invoke(_items)")
                lines.append("    _sections = []")
                lines.append("    for _i, (_iv, _il) in enumerate(_runs):")
                lines.append("        for _l in _il:")
                lines.append("            _rec = json.loads(_l)")
                lines.append(
                    f"            _rec['cell'] = {cell_id!r} + '[' + str(_i) + ']/' + _rec['cell']"
                )
                lines.append("            _sections.append(canonical_json(_rec))")
                if "output" in cell:
                    lines.append(
                        f"    output = [_run[{cell['output']!r}] for _run, _ in _runs]"
                    )
                else:
                    pairs = ", ".join(
                        f"{out_name!r}: [_run[{target!r}] for _run, _ in _runs]"
                        for out_name, target in cell["outputs"].items()
                    )
                    lines.append(f"    output = {{{pairs}}}")
                lines.append(f"    line = make_trace_line({cell_id!r}, 'sheet', inputs, output)")
                lines.append("    _lines = [line]")
                lines.append("    _lines.extend(_sections)")
                lines += self._state_return(cell_id, None, lines_expr="_lines")
                return "\n".join(lines), ("step", name)
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
            lines += self._state_return(cell_id, None, lines_expr="_lines")
            return "\n".join(lines), ("step", name)
        else:
            raise common.LaneSheetError(
                _REFUSAL,
                f"cell {qualified!r}: kind {kind!r} has no LangChain (LCEL) "
                "expression in the lift_langchain mapping",
            )
        lines.append(f"    line = make_trace_line({cell_id!r}, {kind!r}, inputs, output)")
        lines += self._state_return(cell_id, "line")
        return "\n".join(lines), ("step", name)

    def emit_unit(self, sheet, site_path, bound):
        """Emit one chain unit: sub-units first, then stages, build, run."""
        ordered = common.canonical_order(sheet)

        for cell in ordered:
            if cell["kind"] == "sheet":
                inner = common.load_ref(self.resolve, cell["sheet"])
                sub_path = f"{site_path}/{cell['id']}" if site_path else cell["id"]
                self.emit_unit(inner, sub_path, frozenset(cell.get("bind", {})))

        stage_exprs = []
        for cell in ordered:
            source, stage = self._step_source(cell, site_path, bound)
            self.parts.append(source)
            self.parts.append("")
            self.parts.append("")
            if stage[0] == "branch":
                _, cond_name, then_name, else_name = stage
                stage_exprs.append(
                    f"RunnableBranch(({cond_name}, RunnableLambda({then_name})), "
                    f"RunnableLambda({else_name}))"
                )
            else:
                stage_exprs.append(f"RunnableLambda({stage[1]})")

        build_name = "build" if not site_path else f"build_sub_{_suffix(site_path)}"
        run_name = "run" if not site_path else f"run_sub_{_suffix(site_path)}"
        parts = self.parts
        parts.append(f"def {build_name}():")
        parts.append("    chain = RunnablePassthrough()")
        for expr in stage_exprs:
            parts.append(f"    chain = chain | {expr}")
        parts.append("    return chain")
        parts.append("")
        parts.append("")
        parts.append(f"def {run_name}({'seeds' if site_path else ''}):")
        if site_path:
            parts.append(
                '    final = '
                f'{build_name}().invoke({{"values": dict(seeds), "trace_lines": []}})'
            )
            parts.append('    return final["values"], final["trace_lines"]')
        else:
            parts.append(
                f'    final = {build_name}().invoke({{"values": {{}}, "trace_lines": []}})'
            )
            parts.append('    return final["trace_lines"]')
        parts.append("")
        parts.append("")


def lift(sheet, resolve=None):
    """Validate a parsed sheet and return the generated module source."""
    common.validate_sheet(sheet, resolve=resolve)
    runtime_src = Path(__file__).with_name("runtime.py").read_text(encoding="utf-8")

    parts = [
        f'"""GENERATED by lanesheet.lift_langchain -- do not edit by hand.\n\n'
        f"Lane sheet: {sheet['id']!r} (lane-sheet {sheet['lanesheet']}).\n"
        f"Standalone LangChain (LCEL) module. Running it with the embedded\n"
        f"stub providers reproduces the sheet's canonical execution trace.\n"
        f'"""\n',
        "# --- embedded lanesheet runtime (verbatim) ---",
        runtime_src.rstrip("\n"),
        "# --- end embedded runtime ---\n",
        "from langchain_core.runnables import (",
        "    RunnableBranch,",
        "    RunnableLambda,",
        "    RunnablePassthrough,",
        ")",
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
        print("usage: python -m lanesheet.lift_langchain <sheet.json> <out.py>", file=sys.stderr)
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
