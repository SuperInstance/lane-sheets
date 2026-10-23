"""Lane-sheet loading, validation, and canonical execution order.

Validation is where the spec's refusals live: every construct lane-sheet
0.1 does not support is refused here, by name, before any execution --
in the interpreter and in the lifter alike. Nothing is silently
ignored, defaulted, or approximated.
"""

import re

from . import runtime

FORMAT_VERSION = "0.1"

CELL_KINDS = ("value", "prompt", "llm", "tool", "branch")

# Kinds that exist on the Quilt shelf (SuperInstance/quilt cell-kinds.md,
# quilt-agent README) but are deliberately NOT part of lane-sheet 0.1.
QUILT_KINDS_NOT_IN_V01 = (
    "formula", "api", "program", "sensor", "listener", "router", "io", "ai",
)

_TOP_KEYS = {"lanesheet", "id", "title", "lanes", "outputs"}
_LANE_KEYS = {"id", "cells"}
_BASE_CELL_KEYS = {"id", "kind", "inputs"}
_KIND_KEYS = {
    "value": {"value"},
    "prompt": {"template"},
    "llm": set(),
    "tool": {"tool"},
    "branch": {"equals"},
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
    import json

    with open(path, "r", encoding="utf-8") as fh:
        sheet = json.load(fh)
    return validate_sheet(sheet)


def validate_sheet(sheet):
    """Check a parsed sheet against lane-sheet 0.1. Returns the sheet."""
    if not isinstance(sheet, dict):
        _fail("SheetNotObject", "a lane sheet is a JSON object")
    unknown = set(sheet) - _TOP_KEYS
    if unknown:
        _fail("UnexpectedKey", f"sheet has unsupported key(s): {sorted(unknown)}")
    if sheet.get("lanesheet") != FORMAT_VERSION:
        _fail("UnsupportedVersion", f"lanesheet version must be {FORMAT_VERSION!r}")
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
    return sheet


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
