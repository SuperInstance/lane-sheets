// Shared deterministic runtime for SuperInstance lane-sheets --
// JavaScript port of lanesheet/runtime.py, the single source of truth
// the Python reference interpreter and lifters agree on byte-for-byte.
//
// Ported semantics: canonical JSON (the trace encoding), the trace
// line format, prompt-template rendering, branch value selection, and
// the stub providers (deterministic fake LLM, deterministic fake
// tools). No network, no randomness, no wall clock.
//
// Known port edges (outside the fixture corpus, named honestly):
// integers beyond 2^53 and non-integral floats are rendered by JS
// number formatting, which can differ from CPython's repr (e.g. a
// sheet literal 1.0 canonicalises as "1" here, "1.0" in CPython).

import { sha256Hex } from "./sha256.js";

export class StubError extends Error {
  constructor(name, detail = "") {
    super(detail ? `${name}: ${detail}` : name);
    this.name = name;
  }
}

// Cosmetic: Python type names for refusal detail strings.
export function pyTypeName(value) {
  if (value === null || value === undefined) return "NoneType";
  if (Array.isArray(value)) return "list";
  const t = typeof value;
  if (t === "string") return "str";
  if (t === "boolean") return "bool";
  if (t === "number") return Number.isInteger(value) ? "int" : "float";
  return "dict";
}

// ---------------------------------------------------------------------
// Canonical form
// ---------------------------------------------------------------------

export function canonicalJson(value) {
  if (value === null || value === undefined) return "null";
  const t = typeof value;
  if (t === "boolean") return value ? "true" : "false";
  if (t === "number") {
    if (!Number.isFinite(value)) return String(value); // never in corpus
    return Number.isInteger(value) ? String(value) : String(value);
  }
  if (t === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalJson(value[k])).join(",") + "}";
}

export function inputsHash(inputs) {
  return sha256Hex(canonicalJson(inputs));
}

export function makeTraceLine(cellId, kind, inputs, output) {
  const record = {
    cell: cellId,
    inputs: inputs,
    inputs_hash: inputsHash(inputs),
    kind: kind,
    output: output,
  };
  return canonicalJson(record);
}

// ---------------------------------------------------------------------
// Prompt templates
// ---------------------------------------------------------------------

const PLACEHOLDER = /\{\{\s*([A-Za-z0-9_-]+)\s*\}\}/g;

export function templatePorts(template) {
  const ports = [];
  for (const match of template.matchAll(PLACEHOLDER)) ports.push(match[1]);
  return ports;
}

export function stringify(value) {
  if (typeof value === "string") return value;
  return canonicalJson(value);
}

export function renderTemplate(template, inputs) {
  return template.replace(PLACEHOLDER, (whole, port) => {
    if (!Object.prototype.hasOwnProperty.call(inputs, port)) {
      throw new StubError("TemplateError", `template references undeclared port '${port}'`);
    }
    return stringify(inputs[port]);
  });
}

// ---------------------------------------------------------------------
// Stub LLM provider
// ---------------------------------------------------------------------

// Python str.splitlines() line boundaries.
const LINE_BREAK = /\r\n|\r|\n|\v|\f|\x1c|\x1d|\x1e|\x85|\u2028|\u2029/;

function pySplitlines(s) {
  if (s === "") return [];
  const parts = s.split(LINE_BREAK);
  if (parts.length && parts[parts.length - 1] === "") parts.pop();
  return parts;
}

function pyStrip(s) {
  return s.replace(/^[\s\x1c-\x1f\x85]+/, "").replace(/[\s\x1c-\x1f\x85]+$/, "");
}

export function llmComplete(prompt, system = null) {
  if (typeof prompt !== "string") {
    throw new StubError("NonStringPrompt", `llm prompt input must be a string, got ${pyTypeName(prompt)}`);
  }
  if (system !== null && system !== undefined && typeof system !== "string") {
    throw new StubError("NonStringPrompt", `llm system input must be a string, got ${pyTypeName(system)}`);
  }
  const body = (system ? system + "\x00" : "") + prompt;
  const digest = sha256Hex(body).slice(0, 8);
  const lines = pySplitlines(prompt).filter((ln) => pyStrip(ln) !== "");
  const last = lines.length ? pyStrip(lines[lines.length - 1]) : "";
  return `[stub-llm:${digest}] ${last} -> noted`;
}

// ---------------------------------------------------------------------
// Stub tool providers
// ---------------------------------------------------------------------

function toolSearch(args) {
  const query = args.query;
  const digest = sha256Hex(query).slice(0, 6);
  return {
    query: query,
    hits: [1, 2, 3].map((i) => `${query} :: result ${i} (${digest})`),
  };
}

function toolWordcount(args) {
  const text = args.text;
  const words = text.split(/[\s\x1c-\x1f\x85]+/).filter((tok) => tok !== "").length;
  return { words: words, chars: [...text].length };
}

const LOOKUP_TABLE = {
  "quilt": "a spreadsheet where every cell is a live, addressable capability",
  "lane": "one row of a lane sheet; a lane is a cell at the rung you are leading from",
  "verilog": "the bottom layer: a description everything else is synthesized from",
  "ledger": "the record of sends and receives whose agreement mints shared state",
};

function toolLookup(args) {
  const key = args.key;
  if (Object.prototype.hasOwnProperty.call(LOOKUP_TABLE, key)) {
    return { found: true, key: key, value: LOOKUP_TABLE[key] };
  }
  return { found: false, key: key };
}

// name -> { required: [ports in signature order], fn }
export const TOOL_SIGNATURES = {
  search: { required: ["query"], fn: toolSearch },
  wordcount: { required: ["text"], fn: toolWordcount },
  lookup: { required: ["key"], fn: toolLookup },
};

export function callTool(name, args) {
  const sig = TOOL_SIGNATURES[name];
  if (!sig) throw new StubError("UnknownTool", `no stub tool named '${name}'`);
  for (const port of sig.required) {
    if (!Object.prototype.hasOwnProperty.call(args, port)) {
      throw new StubError("MissingPort", `tool '${name}' requires argument port '${port}'`);
    }
    if (typeof args[port] !== "string") {
      throw new StubError(
        "ToolArgument",
        `tool '${name}' argument '${port}' must be a string, got ${pyTypeName(args[port])}`
      );
    }
  }
  return sig.fn(args);
}

// ---------------------------------------------------------------------
// Iteration (0.3): the `each` mode of a `sheet` cell
// ---------------------------------------------------------------------

export const MAX_EACH_ELEMENTS = 100;

export function eachElements(value) {
  if (!Array.isArray(value)) {
    throw new StubError(
      "EachInputNotList",
      `an 'each' port must be piped a list, got ${pyTypeName(value)}`
    );
  }
  if (value.length > MAX_EACH_ELEMENTS) {
    throw new StubError(
      "EachTooManyElements",
      `'each' fan-out of ${value.length} elements exceeds the cap of ${MAX_EACH_ELEMENTS}`
    );
  }
  return value;
}

// ---------------------------------------------------------------------
// Branch selection
// ---------------------------------------------------------------------

export function selectBranch(cond, thenValue, elseValue, equalsMarker) {
  const [present, equals] = equalsMarker;
  if (present) {
    return canonicalJson(cond) === canonicalJson(equals) ? thenValue : elseValue;
  }
  return cond === false || cond === null ? elseValue : thenValue;
}
