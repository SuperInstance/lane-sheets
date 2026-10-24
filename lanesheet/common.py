"""Lane-sheet loading, validation, and canonical execution order.

Validation is where the spec's refusals live: every construct the
format does not support is refused here, by name, before any
execution -- in the interpreter and in the lifter alike. Nothing is
silently ignored, defaulted, or approximated.

Lane-sheet 0.2 (SPEC-AMENDMENT.md) adds the `sheet` cell kind:
sub-sheet composition. Validation of a sheet cell resolves its
reference against a sheet library (a resolver callable), checks the
reference chain for recursion and excessive depth, validates the
referenced sheet recursively, and checks the port mapping (bind /
output) against the referenced sheet's cells.

Lane-sheet 0.3 (SPEC-AMENDMENT-0.3.md) adds the `each` mode of a
`sheet` cell: the cell names one input port carrying a list, and the
interior sheet runs once per element, the element bound to a
designated interior `value` cell. Validation checks the each port is
piped and bound to exactly one element cell; the list-ness and the
fan-out cap are run-time checks (runtime.each_elements), shared by
every engine.
"""

import json
import re
from pathlib import Path

from . import runtime

FORMAT_VERSION = "0.3"
SUPPORTED_VERSIONS = ("0.1", "0.2", "0.3")

CELL_KINDS = ("value", "prompt", "llm", "tool", "branch", "sheet")

# Kinds that exist on the Quilt shelf (SuperInstance/quilt cell-kinds.md,
# quilt-agent README) but are deliberately NOT part of lane-sheets.
QUILT_KINDS_NOT_IN_V01 = (
    "formula", "api", "program", "sensor", "listener", "router", "io", "ai",
)

# A sheet reference may nest at most this many edges below the sheet
# that was handed to the engine. Deeper composition is refused
# (SheetNestingTooDeep); the cap exists so a reference graph that is
# finite but absurd cannot exhaust the engine -- raise it deliberately
# in a future version, never silently.
MAX_NESTING_DEPTH = 8

# Sheet references are bare library names (SPEC-AMENDMENT section 2):
# no path separators, no traversal, no leading dot.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

_TOP_KEYS = {"lanesheet", "id", "title", "lanes", "outputs"}
_LANE_KEYS = {"id", "cells"}
_BASE_CELL_KEYS = {"id", "kind", "inputs"}
_KIND_KEYS = {
    "value": {"value"},
    "prompt": {"template"},
    "llm": set(),
    "tool": {"tool"},
    "branch": {"equals"},
    "sheet": {"sheet", "bind", "output", "outputs", "each"},
}
_RESERVED_IDS = {"START", "END"}


class LaneSheetError(Exception):
    """A named refusal. `name` is stable spec vocabulary (SPEC section 8)."""

    def __init__(self, name, detail=""):
        self.name = name
        super().__init__(f"{name}: {detail}" if detail else name)


def _fail(name, detail):
    raise LaneSheetError(name, detail)


def load_sheet(path):
    with open(path, "r", encoding="utf-8") as fh:
        sheet = json.load(fh)
    # References from a file-loaded sheet resolve against the library
    # in the sheet's own directory (fixture-local names, section 2 of
    # the amendment).
    return validate_sheet(sheet, resolve=local_resolver(Path(path).parent))


def local_resolver(base_dir):
    """A resolver over a directory of `<ref>.sheet.json` files.

    The resolver is the sheet library: given a bare reference name it
    returns the parsed (not yet validated) sheet document. Results are
    cached per resolver, so a sheet referenced from many cells is read
    once. A missing or unparsable file is an UnresolvedSheetRef.
    """
    base = Path(base_dir)
    cache = {}

    def resolve(ref):
        if ref not in cache:
            path = base / f"{ref}.sheet.json"
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise LaneSheetError(
                    "UnresolvedSheetRef",
                    f"cannot resolve sheet reference {ref!r} against library {str(base)!r}: {exc}",
                )
            cache[ref] = parsed
        return cache[ref]

    return resolve


def load_ref(resolve, ref):
    """Resolve a sheet reference at run time, with named refusals."""
    if resolve is None:
        _fail(
            "UnresolvedSheetRef",
            f"sheet reference {ref!r} cannot be resolved: no sheet library was supplied",
        )
    if not isinstance(ref, str) or not _REF_RE.match(ref):
        _fail("InvalidSheetRef", f"sheet reference {ref!r} is not a bare library name")
    return resolve(ref)


def validate_sheet(sheet, resolve=None, _chain=()):
    """Check a parsed sheet against the lane-sheet format. Returns the sheet.

    `resolve` is a sheet-library resolver (see local_resolver); it is
    required iff the sheet (transitively) contains `sheet` cells.
    `_chain` is the tuple of references traversed to reach this sheet,
    used for recursion and depth refusals.
    """
    if not isinstance(sheet, dict):
        _fail("SheetNotObject", "a lane sheet is a JSON object")
    unknown = set(sheet) - _TOP_KEYS
    if unknown:
        _fail("UnexpectedKey", f"sheet has unsupported key(s): {sorted(unknown)}")
    if sheet.get("lanesheet") not in SUPPORTED_VERSIONS:
        _fail(
            "UnsupportedVersion",
            f"lanesheet version must be one of {SUPPORTED_VERSIONS}, got {sheet.get('lanesheet')!r}",
        )
    if not isinstance(sheet.get("id"), str) or not sheet["id"]:
        _fail("MissingField", "sheet requires a non-empty string 'id'")
    lanes = sheet.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        _fail("MissingField", "sheet requires a non-empty 'lanes' list")

    cells = {}          # cell id -> cell dict
    positions = {}      # cell id -> (lane index, index within lane)
    lane_ids = set()
    for lane_idx, lane in enumerate(lanes):
        if not isinstance(lane, dict):
            _fail("SheetNotObject", "each lane is an object with 'id' and 'cells'")
        unknown = set(lane) - _LANE_KEYS
        if unknown:
            _fail("UnexpectedKey", f"lane has unsupported key(s): {sorted(unknown)}")
        lane_id = lane.get("id")
        if not isinstance(lane_id, str) or not lane_id:
            _fail("MissingField", "each lane requires a non-empty string 'id'")
        if lane_id in lane_ids:
            _fail("DuplicateLaneId", f"lane id {lane_id!r} appears twice")
        lane_ids.add(lane_id)
        lane_cells = lane.get("cells")
        if not isinstance(lane_cells, list):
            _fail("MissingField", f"lane {lane_id!r} requires a 'cells' list")
        for cell_idx, cell in enumerate(lane_cells):
            _validate_cell(cell, cells, positions, (lane_idx, cell_idx))

    for cell in cells.values():
        _validate_cell_refs(cell, cells)

    outputs = sheet.get("outputs", [])
    if not isinstance(outputs, list):
        _fail("MissingField", "'outputs' must be a list of cell ids")
    for out in outputs:
        if out not in cells:
            _fail("UndeclaredOutput", f"output {out!r} is not a cell in this sheet")

    canonical_order(sheet)  # raises CycleDetected; also checks name collisions

    if sheet["lanesheet"] == "0.1":
        for cell in cells.values():
            if cell["kind"] == "sheet":
                _fail(
                    "UnsupportedVersion",
                    f"cell {cell['id']!r}: 'sheet' cells require lanesheet 0.2; "
                    "this sheet declares 0.1",
                )
    if sheet["lanesheet"] != "0.3":
        for cell in cells.values():
            if cell["kind"] == "sheet" and "each" in cell:
                _fail(
                    "UnsupportedVersion",
                    f"cell {cell['id']!r}: the 'each' mode requires lanesheet 0.3; "
                    f"this sheet declares {sheet['lanesheet']}",
                )
    _validate_sheet_cells(sheet, cells, resolve, _chain)
    return sheet


def _validate_sheet_cells(sheet, cells, resolve, chain):
    """Cross-check every `sheet` cell against the sheet it references.

    For each sheet cell: the reference must be a bare library name, it
    must not close a reference cycle (directly or transitively), the
    chain must stay within the nesting cap, the referenced sheet must
    itself validate, and the port mapping must name real interior
    cells of the right kind.
    """
    for cell in cells.values():
        if cell["kind"] != "sheet":
            continue
        cell_id = cell["id"]
        ref = cell["sheet"]
        if not _REF_RE.match(ref):
            _fail(
                "InvalidSheetRef",
                f"cell {cell_id!r}: sheet reference {ref!r} is not a bare library name",
            )
        if ref in chain:
            _fail(
                "RecursiveSheetRef",
                f"cell {cell_id!r}: sheet reference {ref!r} closes a reference cycle "
                f"({' -> '.join(chain + (ref,))}); a sheet may not contain itself, "
                "directly or transitively",
            )
        if len(chain) >= MAX_NESTING_DEPTH:
            _fail(
                "SheetNestingTooDeep",
                f"cell {cell_id!r}: reference chain {' -> '.join(chain + (ref,))} exceeds "
                f"the nesting cap of {MAX_NESTING_DEPTH}",
            )
        inner = load_ref(resolve, ref)
        validate_sheet(inner, resolve=resolve, _chain=chain + (ref,))
        inner_cells = {c["id"]: c for c in all_cells(inner)}

        for target in cell.get("bind", {}):
            if target not in inner_cells:
                _fail(
                    "UnknownBindCell",
                    f"cell {cell_id!r} binds interior cell {target!r}, which does not "
                    f"exist in sheet {ref!r}",
                )
            if inner_cells[target]["kind"] != "value":
                _fail(
                    "BindTargetNotValue",
                    f"cell {cell_id!r} binds interior cell {target!r} of sheet {ref!r}, "
                    f"which is a {inner_cells[target]['kind']!r} cell; only 'value' "
                    "cells may be bound -- a parameter is a constant awaiting a value",
                )
        if "output" in cell:
            targets = [cell["output"]]
        else:
            targets = list(cell.get("outputs", {}).values())
        for target in targets:
            if target not in inner_cells:
                _fail(
                    "UnknownSheetOutput",
                    f"cell {cell_id!r} takes its output from interior cell {target!r}, "
                    f"which does not exist in sheet {ref!r}",
                )


def _validate_cell(cell, cells, positions, position):
    if not isinstance(cell, dict):
        _fail("SheetNotObject", "each cell is an object")
    cell_id = cell.get("id")
    if not isinstance(cell_id, str) or not cell_id:
        _fail("MissingField", "each cell requires a non-empty string 'id'")
    if cell_id in _RESERVED_IDS:
        _fail("ReservedCellId", f"cell id {cell_id!r} is reserved by the lifting target")
    if cell_id in cells:
        _fail("DuplicateCellId", f"cell id {cell_id!r} appears twice")
    kind = cell.get("kind")
    if kind is None:
        _fail("MissingField", f"cell {cell_id!r} requires a 'kind'")
    if kind in QUILT_KINDS_NOT_IN_V01:
        _fail(
            "UnsupportedCellKind",
            f"cell {cell_id!r}: kind {kind!r} is a Quilt kind but is not part of lane-sheet 0.1",
        )
    if kind not in CELL_KINDS:
        _fail("UnknownCellKind", f"cell {cell_id!r}: unknown kind {kind!r}")
    allowed = _BASE_CELL_KEYS | _KIND_KEYS[kind]
    unknown = set(cell) - allowed
    if unknown:
        _fail("UnexpectedKey", f"cell {cell_id!r} has unsupported key(s): {sorted(unknown)}")

    inputs = cell.get("inputs", {})
    if not isinstance(inputs, dict):
        _fail("MissingField", f"cell {cell_id!r}: 'inputs' must be an object mapping ports to cell ids")

    if kind == "value":
        if "value" not in cell:
            _fail("MissingField", f"value cell {cell_id!r} requires a 'value'")
        if inputs:
            _fail("ValueCellInputs", f"value cell {cell_id!r} takes no inputs; constants do not pipe")
    elif kind == "prompt":
        if not isinstance(cell.get("template"), str):
            _fail("MissingField", f"prompt cell {cell_id!r} requires a string 'template'")
    elif kind == "llm":
        if "prompt" not in inputs:
            _fail("MissingPort", f"llm cell {cell_id!r} requires an input port 'prompt'")
        extra = set(inputs) - {"prompt", "system"}
        if extra:
            _fail("UnexpectedPort", f"llm cell {cell_id!r} has unsupported port(s): {sorted(extra)}")
    elif kind == "tool":
        tool = cell.get("tool")
        if not isinstance(tool, str) or not tool:
            _fail("MissingField", f"tool cell {cell_id!r} requires a string 'tool' name")
        if tool not in runtime.TOOL_SIGNATURES:
            _fail("UnknownTool", f"cell {cell_id!r}: no stub tool named {tool!r}")
        required, _fn = runtime.TOOL_SIGNATURES[tool]
        for port in required:
            if port not in inputs:
                _fail("MissingPort", f"tool cell {cell_id!r} (tool {tool!r}) requires input port {port!r}")
    elif kind == "branch":
        for port in ("cond", "then", "else"):
            if port not in inputs:
                _fail("MissingPort", f"branch cell {cell_id!r} requires an input port {port!r}")
        extra = set(inputs) - {"cond", "then", "else"}
        if extra:
            _fail("UnexpectedPort", f"branch cell {cell_id!r} has unsupported port(s): {sorted(extra)}")
    elif kind == "sheet":
        ref = cell.get("sheet")
        if not isinstance(ref, str) or not ref:
            _fail("MissingField", f"sheet cell {cell_id!r} requires a non-empty string 'sheet' reference")
        bind = cell.get("bind", {})
        if not isinstance(bind, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in bind.items()
        ):
            _fail(
                "MissingField",
                f"sheet cell {cell_id!r}: 'bind' must be an object mapping interior "
                "cell ids to input port names",
            )
        if "each" in cell:
            # The 0.3 iteration mode (SPEC-AMENDMENT-0.3.md). The each
            # port must be piped, and exactly one bind entry must map
            # an interior cell to it -- that entry designates the
            # element cell. These checks run before port correspondence
            # because they are the more specific diagnosis: an unbound
            # each port is not merely an unbound pipe, it is a fan-out
            # with no element to land on.
            each = cell["each"]
            if not isinstance(each, str) or not each:
                _fail(
                    "MissingField",
                    f"sheet cell {cell_id!r}: 'each' must be the name of an input port",
                )
            if each not in inputs:
                _fail(
                    "EachPortNotPiped",
                    f"sheet cell {cell_id!r}: 'each' names port {each!r}, which is "
                    "not among the cell's piped inputs",
                )
            element_targets = [t for t, p in bind.items() if p == each]
            if not element_targets:
                _fail(
                    "EachElementUnbound",
                    f"sheet cell {cell_id!r}: no bind entry maps an interior cell "
                    f"to the 'each' port {each!r}; a fan-out needs a designated "
                    "element cell to land each element on",
                )
            if len(element_targets) > 1:
                _fail(
                    "EachElementConflict",
                    f"sheet cell {cell_id!r}: bind entries {sorted(element_targets)} "
                    f"all map to the 'each' port {each!r}; exactly one element "
                    "cell may be designated -- pipe inside the interior if two "
                    "cells need the element",
                )
        # Port correspondence is exact: every bound port is piped, and
        # every piped port is bound. An unbound pipe into a sub-sheet
        # would be a value crossing the boundary to nowhere.
        for port in bind.values():
            if port not in inputs:
                _fail(
                    "MissingPort",
                    f"sheet cell {cell_id!r} binds input port {port!r} but does not pipe it",
                )
        unbound = set(inputs) - set(bind.values())
        if unbound:
            _fail(
                "UnexpectedPort",
                f"sheet cell {cell_id!r} pipes port(s) {sorted(unbound)} that are not "
                "bound to any interior cell",
            )
        has_output = "output" in cell
        has_outputs = "outputs" in cell
        if has_output and has_outputs:
            _fail(
                "SheetOutputConflict",
                f"sheet cell {cell_id!r} declares both 'output' and 'outputs'; "
                "declare exactly one boundary output shape",
            )
        if not has_output and not has_outputs:
            _fail(
                "MissingField",
                f"sheet cell {cell_id!r} requires 'output' (one interior cell) or "
                "'outputs' (a name -> interior cell map)",
            )
        if has_output and not isinstance(cell["output"], str):
            _fail("MissingField", f"sheet cell {cell_id!r}: 'output' must be an interior cell id string")
        if has_outputs:
            outs = cell["outputs"]
            if not isinstance(outs, dict) or not outs or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in outs.items()
            ):
                _fail(
                    "MissingField",
                    f"sheet cell {cell_id!r}: 'outputs' must be a non-empty object "
                    "mapping output names to interior cell ids",
                )

    cells[cell_id] = cell
    positions[cell_id] = position


def _validate_cell_refs(cell, cells):
    cell_id = cell["id"]
    for port, source in cell.get("inputs", {}).items():
        if not isinstance(source, str) or source not in cells:
            _fail(
                "UnknownInputCell",
                f"cell {cell_id!r} port {port!r} pipes from unknown cell {source!r}",
            )
    if cell["kind"] == "prompt":
        for port in runtime.template_ports(cell["template"]):
            if port not in cell.get("inputs", {}):
                _fail(
                    "TemplateError",
                    f"prompt cell {cell_id!r} template references port {port!r} "
                    "which is not among its piped inputs",
                )


def all_cells(sheet):
    """Every cell, in sheet order (lane order, then order within lane)."""
    return [cell for lane in sheet["lanes"] for cell in lane["cells"]]


def node_name(cell_id):
    """The Python identifier a lifter uses for a cell's node function."""
    return "node_" + re.sub(r"\W", "_", cell_id)


def canonical_order(sheet):
    """The one execution order every engine must reproduce (SPEC section 6).

    Cells are grouped by dependency level (longest piping path from a
    source cell); within a level, sheet order decides. Returns the cell
    dicts in canonical order. Raises CycleDetected and NodeNameCollision.
    """
    cells = all_cells(sheet)
    by_id = {c["id"]: c for c in cells}
    position = {c["id"]: i for i, c in enumerate(cells)}

    names = {}
    for c in cells:
        nn = node_name(c["id"])
        if nn in names:
            _fail(
                "NodeNameCollision",
                f"cells {names[nn]!r} and {c['id']!r} collide as graph node names",
            )
        names[nn] = c["id"]

    levels = {}

    def level(cell_id, stack):
        if cell_id in levels:
            return levels[cell_id]
        if cell_id in stack:
            _fail("CycleDetected", f"piping cycle through cell {cell_id!r}; lane sheets are DAGs")
        stack.add(cell_id)
        sources = list(by_id[cell_id].get("inputs", {}).values())
        lv = 0 if not sources else 1 + max(level(s, stack) for s in sources)
        stack.discard(cell_id)
        levels[cell_id] = lv
        return lv

    for c in cells:
        level(c["id"], set())

    return sorted(cells, key=lambda c: (levels[c["id"]], position[c["id"]]))
