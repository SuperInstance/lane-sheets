"""Shared deterministic runtime for SuperInstance lane-sheets.

This module is the single source of truth for everything the reference
interpreter and the LangGraph lifter must agree on byte-for-byte:

  * canonical JSON encoding and the trace-line format (the trace is the
    conformance object, the way the state hash is for the Quilt cell
    fabric -- see the shelf study, DOSSIER.md section 2),
  * prompt-template rendering,
  * branch (value-selection) semantics,
  * the stub providers: a deterministic fake LLM and deterministic fake
    tools. No network, no randomness, no wall clock. Per the shelf's
    two-tier law, conformance paths never route through real LLM
    inference; the `llm` cell kind names a provider call, and in
    conformance that provider is this stub.

The lifter embeds this file's source verbatim into every generated
module, so a lifted sheet carries the exact runtime it was checked
against. Stdlib only.
"""

import hashlib
import json
import re

__all__ = [
    "StubError",
    "canonical_json",
    "inputs_hash",
    "make_trace_line",
    "stringify",
    "render_template",
    "llm_complete",
    "TOOL_SIGNATURES",
    "call_tool",
    "select_branch",
    "MAX_EACH_ELEMENTS",
    "each_elements",
]


class StubError(Exception):
    """A runtime refusal with a stable, named identity.

    `name` is part of the lane-sheet spec: hosts and lifters must refuse
    with the same names, never with a silent fallback.
    """

    def __init__(self, name, detail=""):
        self.name = name
        super().__init__(f"{name}: {detail}" if detail else name)


# ---------------------------------------------------------------------------
# Canonical form
# ---------------------------------------------------------------------------

def canonical_json(value):
    """The one JSON encoding used for hashing and template insertion."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def inputs_hash(inputs):
    """SHA-256 of the canonical encoding of a cell's input-port map."""
    return hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest()


def make_trace_line(cell_id, kind, inputs, output):
    """One canonical trace record, as a single JSON line (no newline)."""
    record = {
        "cell": cell_id,
        "inputs": inputs,
        "inputs_hash": inputs_hash(inputs),
        "kind": kind,
        "output": output,
    }
    return canonical_json(record)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_-]+)\s*\}\}")


def template_ports(template):
    """Port names referenced by a template, in order of appearance."""
    return _PLACEHOLDER.findall(template)


def stringify(value):
    """How a piped value appears inside a prompt template."""
    if isinstance(value, str):
        return value
    return canonical_json(value)


def render_template(template, inputs):
    def replace(match):
        port = match.group(1)
        if port not in inputs:
            raise StubError("TemplateError", f"template references undeclared port {port!r}")
        return stringify(inputs[port])

    return _PLACEHOLDER.sub(replace, template)


# ---------------------------------------------------------------------------
# Stub LLM provider
# ---------------------------------------------------------------------------

def llm_complete(prompt, system=None):
    """Deterministic fake completion: a pure function of (system, prompt).

    The reply echoes the prompt's last non-empty line, stamped with a
    short digest of the full input, so different prompts give visibly
    different -- but always reproducible -- completions.
    """
    if not isinstance(prompt, str):
        raise StubError("NonStringPrompt", f"llm prompt input must be a string, got {type(prompt).__name__}")
    if system is not None and not isinstance(system, str):
        raise StubError("NonStringPrompt", f"llm system input must be a string, got {type(system).__name__}")
    body = (system + "\x00" if system else "") + prompt
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    lines = [ln for ln in prompt.splitlines() if ln.strip()]
    last = lines[-1].strip() if lines else ""
    return f"[stub-llm:{digest}] {last} -> noted"


# ---------------------------------------------------------------------------
# Stub tool providers
# ---------------------------------------------------------------------------

def _tool_search(args):
    query = args["query"]
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:6]
    return {
        "query": query,
        "hits": [f"{query} :: result {i} ({digest})" for i in (1, 2, 3)],
    }


def _tool_wordcount(args):
    text = args["text"]
    return {"words": len(text.split()), "chars": len(text)}


_LOOKUP_TABLE = {
    "quilt": "a spreadsheet where every cell is a live, addressable capability",
    "lane": "one row of a lane sheet; a lane is a cell at the rung you are leading from",
    "verilog": "the bottom layer: a description everything else is synthesized from",
    "ledger": "the record of sends and receives whose agreement mints shared state",
}


def _tool_lookup(args):
    key = args["key"]
    if key in _LOOKUP_TABLE:
        return {"found": True, "key": key, "value": _LOOKUP_TABLE[key]}
    return {"found": False, "key": key}


# name -> (required string-typed argument ports, function)
TOOL_SIGNATURES = {
    "search": ({"query": "string"}, _tool_search),
    "wordcount": ({"text": "string"}, _tool_wordcount),
    "lookup": ({"key": "string"}, _tool_lookup),
}


def call_tool(name, args):
    if name not in TOOL_SIGNATURES:
        raise StubError("UnknownTool", f"no stub tool named {name!r}")
    required, fn = TOOL_SIGNATURES[name]
    for port in required:
        if port not in args:
            raise StubError("MissingPort", f"tool {name!r} requires argument port {port!r}")
        if not isinstance(args[port], str):
            raise StubError(
                "ToolArgument",
                f"tool {name!r} argument {port!r} must be a string, got {type(args[port]).__name__}",
            )
    return fn(args)


# ---------------------------------------------------------------------------
# Iteration (0.3): the `each` mode of a `sheet` cell
# ---------------------------------------------------------------------------

# The fan-out cap for one `each` cell (SPEC-AMENDMENT-0.3 section 2).
# 100 elements is generous for the fan-outs a sheet expresses (batch
# definition, batch counting, per-item framing) while keeping one
# cell's trace section a readable receipt and a lifted node's loop a
# loop, not a workload. The cap is spec, in this module, so every
# engine refuses the same count with the same name.
MAX_EACH_ELEMENTS = 100


def each_elements(value):
    """Validate an `each` port's value and return its element list.

    The value a cell pipes into its `each` port must be a list of at
    most MAX_EACH_ELEMENTS elements. Anything else is a named refusal,
    raised identically by every engine before any element invocation
    runs -- a fan-out never starts and then discovers it should not
    have.
    """
    if not isinstance(value, list):
        raise StubError(
            "EachInputNotList",
            f"an 'each' port must be piped a list, got {type(value).__name__}",
        )
    if len(value) > MAX_EACH_ELEMENTS:
        raise StubError(
            "EachTooManyElements",
            f"'each' fan-out of {len(value)} elements exceeds the cap of "
            f"{MAX_EACH_ELEMENTS}",
        )
    return value


# ---------------------------------------------------------------------------
# Branch selection
# ---------------------------------------------------------------------------

def select_branch(cond, then_value, else_value, equals_marker):
    """Value selection over eagerly evaluated arms (SPEC section 5).

    `equals_marker` is a (present, value) pair: when present, the `then`
    arm is selected iff cond deep-equals value (compared by canonical
    JSON, so 1 and true never conflate); when absent, the `then` arm is
    selected iff cond is neither false nor null -- the only two falsy
    values lane-sheet 0.1 recognises.
    """
    present, equals = equals_marker
    if present:
        return then_value if canonical_json(cond) == canonical_json(equals) else else_value
    return else_value if cond is False or cond is None else then_value
