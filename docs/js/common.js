// Lane-sheet loading, validation, and canonical execution order --
// JavaScript port of lanesheet/common.py.
//
// Validation is where the spec's refusals live: every construct the
// format does not support is refused here, by name, before any
// execution. The check ORDER mirrors the Python source exactly, so a
// sheet that breaks several rules is refused with the same name the
// reference interpreter would use.

import * as runtime from "./runtime.js";

export const FORMAT_VERSION = "0.3";
export const SUPPORTED_VERSIONS = ["0.1", "0.2", "0.3"];
export const CELL_KINDS = ["value", "prompt", "llm", "tool", "branch", "sheet"];
export const QUILT_KINDS_NOT_IN_V01 = [
  "formula", "api", "program", "sensor", "listener", "router", "io", "ai",
];
export const MAX_NESTING_DEPTH = 8;

const REF_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;
const TOP_KEYS = new Set(["lanesheet", "id", "title", "lanes", "outputs"]);
const LANE_KEYS = new Set(["id", "cells"]);
const BASE_CELL_KEYS = new Set(["id", "kind", "inputs"]);
const KIND_KEYS = {
  value: new Set(["value"]),
  prompt: new Set(["template"]),
  llm: new Set(),
  tool: new Set(["tool"]),
  branch: new Set(["equals"]),
  sheet: new Set(["sheet", "bind", "output", "outputs", "each"]),
};
const RESERVED_IDS = new Set(["START", "END"]);

export class LaneSheetError extends Error {
  constructor(name, detail = "") {
    super(detail ? `${name}: ${detail}` : name);
    this.name = name;
  }
}

function fail(name, detail) {
  throw new LaneSheetError(name, detail);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function has(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

// ---------------------------------------------------------------------
// Sheet library resolver (analogue of common.local_resolver)
// ---------------------------------------------------------------------

export function mapResolver(sheetsByName) {
  const cache = new Map();
  return function resolve(ref) {
    if (!cache.has(ref)) {
      if (!has(sheetsByName, ref)) {
        throw new LaneSheetError(
          "UnresolvedSheetRef",
          `cannot resolve sheet reference '${ref}' against the fixture library`
        );
      }
      cache.set(ref, sheetsByName[ref]);
    }
    return cache.get(ref);
  };
}

export function loadRef(resolve, ref) {
  if (resolve === null || resolve === undefined) {
    fail(
      "UnresolvedSheetRef",
      `sheet reference '${ref}' cannot be resolved: no sheet library was supplied`
    );
  }
  if (typeof ref !== "string" || !REF_RE.test(ref)) {
    fail("InvalidSheetRef", `sheet reference '${ref}' is not a bare library name`);
  }
  return resolve(ref);
}

// ---------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------

export function validateSheet(sheet, resolve = null, chain = []) {
  if (!isObject(sheet)) {
    fail("SheetNotObject", "a lane sheet is a JSON object");
  }
  const unknownTop = Object.keys(sheet).filter((k) => !TOP_KEYS.has(k));
  if (unknownTop.length) {
    fail("UnexpectedKey", `sheet has unsupported key(s): ${unknownTop.sort().join(", ")}`);
  }
  if (!SUPPORTED_VERSIONS.includes(sheet.lanesheet)) {
    fail(
      "UnsupportedVersion",
      `lanesheet version must be one of ${SUPPORTED_VERSIONS.join(", ")}, got '${sheet.lanesheet}'`
    );
  }
  if (typeof sheet.id !== "string" || !sheet.id) {
    fail("MissingField", "sheet requires a non-empty string 'id'");
  }
  const lanes = sheet.lanes;
  if (!Array.isArray(lanes) || lanes.length === 0) {
    fail("MissingField", "sheet requires a non-empty 'lanes' list");
  }

  const cells = new Map();
  const positions = new Map();
  const laneIds = new Set();
  lanes.forEach((lane, laneIdx) => {
    if (!isObject(lane)) {
      fail("SheetNotObject", "each lane is an object with 'id' and 'cells'");
    }
    const unknownLane = Object.keys(lane).filter((k) => !LANE_KEYS.has(k));
    if (unknownLane.length) {
      fail("UnexpectedKey", `lane has unsupported key(s): ${unknownLane.sort().join(", ")}`);
    }
    const laneId = lane.id;
    if (typeof laneId !== "string" || !laneId) {
      fail("MissingField", "each lane requires a non-empty string 'id'");
    }
    if (laneIds.has(laneId)) {
      fail("DuplicateLaneId", `lane id '${laneId}' appears twice`);
    }
    laneIds.add(laneId);
    const laneCells = lane.cells;
    if (!Array.isArray(laneCells)) {
      fail("MissingField", `lane '${laneId}' requires a 'cells' list`);
    }
    laneCells.forEach((cell, cellIdx) => {
      validateCell(cell, cells, positions, [laneIdx, cellIdx]);
    });
  });

  for (const cell of cells.values()) {
    validateCellRefs(cell, cells);
  }

  const outputs = sheet.outputs === undefined ? [] : sheet.outputs;
  if (!Array.isArray(outputs)) {
    fail("MissingField", "'outputs' must be a list of cell ids");
  }
  for (const out of outputs) {
    if (!cells.has(out)) {
      fail("UndeclaredOutput", `output '${out}' is not a cell in this sheet`);
    }
  }

  canonicalOrder(sheet); // raises CycleDetected; also checks name collisions

  if (sheet.lanesheet === "0.1") {
    for (const cell of cells.values()) {
      if (cell.kind === "sheet") {
        fail(
          "UnsupportedVersion",
          `cell '${cell.id}': 'sheet' cells require lanesheet 0.2; this sheet declares 0.1`
        );
      }
    }
  }
  if (sheet.lanesheet !== "0.3") {
    for (const cell of cells.values()) {
      if (cell.kind === "sheet" && has(cell, "each")) {
        fail(
          "UnsupportedVersion",
          `cell '${cell.id}': the 'each' mode requires lanesheet 0.3; this sheet declares ${sheet.lanesheet}`
        );
      }
    }
  }
  validateSheetCells(sheet, cells, resolve, chain);
  return sheet;
}

function validateSheetCells(sheet, cells, resolve, chain) {
  for (const cell of cells.values()) {
    if (cell.kind !== "sheet") continue;
    const cellId = cell.id;
    const ref = cell.sheet;
    if (!REF_RE.test(ref)) {
      fail(
        "InvalidSheetRef",
        `cell '${cellId}': sheet reference '${ref}' is not a bare library name`
      );
    }
    if (chain.includes(ref)) {
      fail(
        "RecursiveSheetRef",
        `cell '${cellId}': sheet reference '${ref}' closes a reference cycle ` +
          `(${[...chain, ref].join(" -> ")}); a sheet may not contain itself, ` +
          "directly or transitively"
      );
    }
    if (chain.length >= MAX_NESTING_DEPTH) {
      fail(
        "SheetNestingTooDeep",
        `cell '${cellId}': reference chain ${[...chain, ref].join(" -> ")} exceeds ` +
          `the nesting cap of ${MAX_NESTING_DEPTH}`
      );
    }
    const inner = loadRef(resolve, ref);
    validateSheet(inner, resolve, [...chain, ref]);
    const innerCells = new Map(allCells(inner).map((c) => [c.id, c]));

    for (const target of Object.keys(cell.bind ?? {})) {
      if (!innerCells.has(target)) {
        fail(
          "UnknownBindCell",
          `cell '${cellId}' binds interior cell '${target}', which does not exist in sheet '${ref}'`
        );
      }
      if (innerCells.get(target).kind !== "value") {
        fail(
          "BindTargetNotValue",
          `cell '${cellId}' binds interior cell '${target}' of sheet '${ref}', ` +
            `which is a '${innerCells.get(target).kind}' cell; only 'value' ` +
            "cells may be bound -- a parameter is a constant awaiting a value"
        );
      }
    }
    const targets = has(cell, "output")
      ? [cell.output]
      : Object.values(cell.outputs ?? {});
    for (const target of targets) {
      if (!innerCells.has(target)) {
        fail(
          "UnknownSheetOutput",
          `cell '${cellId}' takes its output from interior cell '${target}', ` +
            `which does not exist in sheet '${ref}'`
        );
      }
    }
  }
}

function validateCell(cell, cells, positions, position) {
  if (!isObject(cell)) {
    fail("SheetNotObject", "each cell is an object");
  }
  const cellId = cell.id;
  if (typeof cellId !== "string" || !cellId) {
    fail("MissingField", "each cell requires a non-empty string 'id'");
  }
  if (RESERVED_IDS.has(cellId)) {
    fail("ReservedCellId", `cell id '${cellId}' is reserved by the lifting target`);
  }
  if (cells.has(cellId)) {
    fail("DuplicateCellId", `cell id '${cellId}' appears twice`);
  }
  const kind = cell.kind;
  if (kind === undefined || kind === null) {
    fail("MissingField", `cell '${cellId}' requires a 'kind'`);
  }
  if (QUILT_KINDS_NOT_IN_V01.includes(kind)) {
    fail(
      "UnsupportedCellKind",
      `cell '${cellId}': kind '${kind}' is a Quilt kind but is not part of lane-sheet 0.1`
    );
  }
  if (!CELL_KINDS.includes(kind)) {
    fail("UnknownCellKind", `cell '${cellId}': unknown kind '${kind}'`);
  }
  const allowed = new Set([...BASE_CELL_KEYS, ...KIND_KEYS[kind]]);
  const unknownKeys = Object.keys(cell).filter((k) => !allowed.has(k));
  if (unknownKeys.length) {
    fail("UnexpectedKey", `cell '${cellId}' has unsupported key(s): ${unknownKeys.sort().join(", ")}`);
  }

  const inputs = cell.inputs === undefined ? {} : cell.inputs;
  if (!isObject(inputs)) {
    fail("MissingField", `cell '${cellId}': 'inputs' must be an object mapping ports to cell ids`);
  }

  if (kind === "value") {
    if (!has(cell, "value")) {
      fail("MissingField", `value cell '${cellId}' requires a 'value'`);
    }
    if (Object.keys(inputs).length) {
      fail("ValueCellInputs", `value cell '${cellId}' takes no inputs; constants do not pipe`);
    }
  } else if (kind === "prompt") {
    if (typeof cell.template !== "string") {
      fail("MissingField", `prompt cell '${cellId}' requires a string 'template'`);
    }
  } else if (kind === "llm") {
    if (!has(inputs, "prompt")) {
      fail("MissingPort", `llm cell '${cellId}' requires an input port 'prompt'`);
    }
    const extra = Object.keys(inputs).filter((p) => p !== "prompt" && p !== "system");
    if (extra.length) {
      fail("UnexpectedPort", `llm cell '${cellId}' has unsupported port(s): ${extra.sort().join(", ")}`);
    }
  } else if (kind === "tool") {
    const tool = cell.tool;
    if (typeof tool !== "string" || !tool) {
      fail("MissingField", `tool cell '${cellId}' requires a string 'tool' name`);
    }
    const sig = runtime.TOOL_SIGNATURES[tool];
    if (!sig) {
      fail("UnknownTool", `cell '${cellId}': no stub tool named '${tool}'`);
    }
    for (const port of sig.required) {
      if (!has(inputs, port)) {
        fail("MissingPort", `tool cell '${cellId}' (tool '${tool}') requires input port '${port}'`);
      }
    }
  } else if (kind === "branch") {
    for (const port of ["cond", "then", "else"]) {
      if (!has(inputs, port)) {
        fail("MissingPort", `branch cell '${cellId}' requires an input port '${port}'`);
      }
    }
    const extra = Object.keys(inputs).filter((p) => !["cond", "then", "else"].includes(p));
    if (extra.length) {
      fail("UnexpectedPort", `branch cell '${cellId}' has unsupported port(s): ${extra.sort().join(", ")}`);
    }
  } else if (kind === "sheet") {
    const ref = cell.sheet;
    if (typeof ref !== "string" || !ref) {
      fail("MissingField", `sheet cell '${cellId}' requires a non-empty string 'sheet' reference`);
    }
    const bind = cell.bind === undefined ? {} : cell.bind;
    if (
      !isObject(bind) ||
      !Object.entries(bind).every(([k, v]) => typeof k === "string" && typeof v === "string")
    ) {
      fail(
        "MissingField",
        `sheet cell '${cellId}': 'bind' must be an object mapping interior cell ids to input port names`
      );
    }
    if (has(cell, "each")) {
      const each = cell.each;
      if (typeof each !== "string" || !each) {
        fail("MissingField", `sheet cell '${cellId}': 'each' must be the name of an input port`);
      }
      if (!has(inputs, each)) {
        fail(
          "EachPortNotPiped",
          `sheet cell '${cellId}': 'each' names port '${each}', which is not among the cell's piped inputs`
        );
      }
      const elementTargets = Object.entries(bind)
        .filter(([, p]) => p === each)
        .map(([t]) => t);
      if (elementTargets.length === 0) {
        fail(
          "EachElementUnbound",
          `sheet cell '${cellId}': no bind entry maps an interior cell to the 'each' port '${each}'; ` +
            "a fan-out needs a designated element cell to land each element on"
        );
      }
      if (elementTargets.length > 1) {
        fail(
          "EachElementConflict",
          `sheet cell '${cellId}': bind entries ${elementTargets.sort().join(", ")} all map to the ` +
            `'each' port '${each}'; exactly one element cell may be designated -- pipe inside ` +
            "the interior if two cells need the element"
        );
      }
    }
    for (const port of Object.values(bind)) {
      if (!has(inputs, port)) {
        fail(
          "MissingPort",
          `sheet cell '${cellId}' binds input port '${port}' but does not pipe it`
        );
      }
    }
    const boundPorts = new Set(Object.values(bind));
    const unbound = Object.keys(inputs).filter((p) => !boundPorts.has(p));
    if (unbound.length) {
      fail(
        "UnexpectedPort",
        `sheet cell '${cellId}' pipes port(s) ${unbound.sort().join(", ")} that are not bound to any interior cell`
      );
    }
    const hasOutput = has(cell, "output");
    const hasOutputs = has(cell, "outputs");
    if (hasOutput && hasOutputs) {
      fail(
        "SheetOutputConflict",
        `sheet cell '${cellId}' declares both 'output' and 'outputs'; declare exactly one boundary output shape`
      );
    }
    if (!hasOutput && !hasOutputs) {
      fail(
        "MissingField",
        `sheet cell '${cellId}' requires 'output' (one interior cell) or 'outputs' (a name -> interior cell map)`
      );
    }
    if (hasOutput && typeof cell.output !== "string") {
      fail("MissingField", `sheet cell '${cellId}': 'output' must be an interior cell id string`);
    }
    if (hasOutputs) {
      const outs = cell.outputs;
      if (
        !isObject(outs) ||
        Object.keys(outs).length === 0 ||
        !Object.entries(outs).every(([k, v]) => typeof k === "string" && typeof v === "string")
      ) {
        fail(
          "MissingField",
          `sheet cell '${cellId}': 'outputs' must be a non-empty object mapping output names to interior cell ids`
        );
      }
    }
  }

  cells.set(cellId, cell);
  positions.set(cellId, position);
}

function validateCellRefs(cell, cells) {
  const cellId = cell.id;
  for (const [port, source] of Object.entries(cell.inputs ?? {})) {
    if (typeof source !== "string" || !cells.has(source)) {
      fail(
        "UnknownInputCell",
        `cell '${cellId}' port '${port}' pipes from unknown cell '${source}'`
      );
    }
  }
  if (cell.kind === "prompt") {
    for (const port of runtime.templatePorts(cell.template)) {
      if (!has(cell.inputs ?? {}, port)) {
        fail(
          "TemplateError",
          `prompt cell '${cellId}' template references port '${port}' which is not among its piped inputs`
        );
      }
    }
  }
}

// ---------------------------------------------------------------------
// Canonical order
// ---------------------------------------------------------------------

export function allCells(sheet) {
  return sheet.lanes.flatMap((lane) => lane.cells);
}

export function nodeName(cellId) {
  return "node_" + cellId.replace(/\W/g, "_");
}

export function canonicalOrder(sheet) {
  const cells = allCells(sheet);
  const byId = new Map(cells.map((c) => [c.id, c]));
  const position = new Map(cells.map((c, i) => [c.id, i]));

  const names = new Map();
  for (const c of cells) {
    const nn = nodeName(c.id);
    if (names.has(nn)) {
      fail(
        "NodeNameCollision",
        `cells '${names.get(nn)}' and '${c.id}' collide as graph node names`
      );
    }
    names.set(nn, c.id);
  }

  const levels = new Map();
  function level(cellId, stack) {
    if (levels.has(cellId)) return levels.get(cellId);
    if (stack.has(cellId)) {
      fail("CycleDetected", `piping cycle through cell '${cellId}'; lane sheets are DAGs`);
    }
    stack.add(cellId);
    const sources = Object.values(byId.get(cellId).inputs ?? {});
    const lv = sources.length === 0 ? 0 : 1 + Math.max(...sources.map((s) => level(s, stack)));
    stack.delete(cellId);
    levels.set(cellId, lv);
    return lv;
  }
  for (const c of cells) level(c.id, new Set());

  return [...cells].sort(
    (a, b) => levels.get(a.id) - levels.get(b.id) || position.get(a.id) - position.get(b.id)
  );
}
