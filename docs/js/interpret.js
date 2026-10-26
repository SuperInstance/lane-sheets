// Reference interpreter for SuperInstance lane-sheets -- JavaScript
// port of lanesheet/interpret.py.
//
// Executes a sheet with the deterministic stub providers from
// runtime.js and emits the canonical execution trace -- one JSON line
// per cell, in canonical order. The trace is the conformance object:
// this port is correct exactly insofar as its traces match the Python
// reference's golden traces byte-for-byte (proven by
// check_conformance.mjs over the full fixture corpus).
//
// `sheet` cells run their referenced sheet as a unit, one rung down:
// one boundary trace line (boundary inputs/outputs only), followed by
// the interior section with prefixed cell ids. In `each` mode the
// interior runs once per element, sections indexed `fan.define[0]/`.

import * as common from "./common.js";
import * as runtime from "./runtime.js";

const NO_OVERRIDE = Symbol("no-override");

function buildInputs(cell, values) {
  const inputs = Object.create(null);
  for (const [port, src] of Object.entries(cell.inputs ?? {})) {
    inputs[port] = values.get(src);
  }
  return inputs;
}

export function evaluateCell(cell, values, valueOverride = NO_OVERRIDE) {
  const kind = cell.kind;
  const inputs = buildInputs(cell, values);
  let output;
  if (kind === "value") {
    output = valueOverride === NO_OVERRIDE ? cell.value : valueOverride;
  } else if (kind === "prompt") {
    output = runtime.renderTemplate(cell.template, inputs);
  } else if (kind === "llm") {
    try {
      output = runtime.llmComplete(
        inputs.prompt,
        Object.prototype.hasOwnProperty.call(inputs, "system") ? inputs.system : null
      );
    } catch (exc) {
      if (exc instanceof runtime.StubError) {
        throw new common.LaneSheetError(exc.name, `cell '${cell.id}': ${exc.message}`);
      }
      throw exc;
    }
  } else if (kind === "tool") {
    try {
      output = runtime.callTool(cell.tool, inputs);
    } catch (exc) {
      if (exc instanceof runtime.StubError) {
        throw new common.LaneSheetError(exc.name, `cell '${cell.id}': ${exc.message}`);
      }
      throw exc;
    }
  } else if (kind === "branch") {
    const marker = [Object.prototype.hasOwnProperty.call(cell, "equals"), cell.equals];
    output = runtime.selectBranch(inputs.cond, inputs.then, inputs.else, marker);
  } else {
    throw new common.LaneSheetError("UnknownCellKind", `cell '${cell.id}': '${kind}'`);
  }
  return [inputs, output];
}

function runInner(sheet, resolve, prefix, overrides) {
  const values = new Map();
  const lines = [];
  for (const cell of common.canonicalOrder(sheet)) {
    const cellId = cell.id;
    if (cell.kind === "sheet") {
      const inputs = buildInputs(cell, values);
      const inner = common.loadRef(resolve, cell.sheet);
      const bind = cell.bind ?? {};
      if (Object.prototype.hasOwnProperty.call(cell, "each")) {
        const eachPort = cell.each;
        let elements;
        try {
          elements = runtime.eachElements(inputs[eachPort]);
        } catch (exc) {
          if (exc instanceof runtime.StubError) {
            throw new common.LaneSheetError(exc.name, `cell '${cellId}': ${exc.message}`);
          }
          throw exc;
        }
        const elementTarget = Object.entries(bind).find(([, p]) => p === eachPort)[0];
        const fixed = new Map(
          Object.entries(bind)
            .filter(([, p]) => p !== eachPort)
            .map(([target, port]) => [target, inputs[port]])
        );
        const sections = [];
        const runs = [];
        elements.forEach((element, i) => {
          const elementOverrides = new Map(fixed);
          elementOverrides.set(elementTarget, element);
          const [innerLines, innerValues] = runInner(
            inner,
            resolve,
            `${prefix}${cellId}[${i}]/`,
            elementOverrides
          );
          sections.push(...innerLines);
          runs.push(innerValues);
        });
        let output;
        if (Object.prototype.hasOwnProperty.call(cell, "output")) {
          output = runs.map((run) => run.get(cell.output));
        } else {
          output = Object.create(null);
          for (const [name, target] of Object.entries(cell.outputs)) {
            output[name] = runs.map((run) => run.get(target));
          }
        }
        values.set(cellId, output);
        lines.push(runtime.makeTraceLine(prefix + cellId, "sheet", inputs, output));
        lines.push(...sections);
        continue;
      }
      const innerOverrides = new Map(
        Object.entries(bind).map(([target, port]) => [target, inputs[port]])
      );
      const [innerLines, innerValues] = runInner(
        inner,
        resolve,
        prefix + cellId + "/",
        innerOverrides
      );
      let output;
      if (Object.prototype.hasOwnProperty.call(cell, "output")) {
        output = innerValues.get(cell.output);
      } else {
        output = Object.create(null);
        for (const [name, target] of Object.entries(cell.outputs)) {
          output[name] = innerValues.get(target);
        }
      }
      values.set(cellId, output);
      lines.push(runtime.makeTraceLine(prefix + cellId, "sheet", inputs, output));
      lines.push(...innerLines);
      continue;
    }
    const override =
      cell.kind === "value" && overrides.has(cellId) ? overrides.get(cellId) : NO_OVERRIDE;
    const [inputs, output] = evaluateCell(cell, values, override);
    values.set(cellId, output);
    lines.push(runtime.makeTraceLine(prefix + cellId, cell.kind, inputs, output));
  }
  return [lines, values];
}

export function runSheet(sheet, resolve = null) {
  common.validateSheet(sheet, resolve);
  const [lines] = runInner(sheet, resolve, "", new Map());
  return lines;
}
