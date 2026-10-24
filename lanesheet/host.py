"""Host binding layer for SuperInstance lane-sheets.

Lane-sheet 0.1 names its providers and never binds them: an `llm` cell
carries only input ports, a `tool` cell only a tool name (SPEC section
4). The conformance suite runs those names against the deterministic
stubs in `lanesheet.runtime`, and per the shelf's two-tier law that
path is byte-exact and quarantined from live inference -- forever.

This module is the other tier: a host. A host binds names to real
providers via a small JSON binding config, executes a sheet through
the same validation and canonical order as the reference interpreter,
and emits the same canonical trace format -- with one difference that
is the whole point: a host trace begins with a header record naming
the run as live and naming every provider and model that produced it.
A live trace can therefore never be confused with, or passed off as, a
stub conformance trace. Live output is nondeterministic; host traces
are evidence of a run, not conformance objects (see run_host_check.py,
which validates them structurally, never byte-for-byte).

`sheet` cells (0.2) run exactly as the interpreter runs them: the
host recurses through a sheet library, one rung down per cell, with
per-invocation-site bound values and interior trace lines prefixed by
the sheet cell's id. Bindings resolve by the same rule at every rung
-- a binding keyed by a cell id applies to that id in whichever sheet
document declares it; otherwise the cell's name ("llm", or a tool
name) decides. The header names every binding the run resolves to at
any rung, interiors included. A `sheet` cell in `each` mode (0.3)
runs its interior once per element of its list input, exactly as the
interpreter does -- the fan-out refusals included (runtime.
each_elements, re-named as HostErrors with the same names).

Providers are duck-typed:

    complete(prompt, system=None, params=None) -> str     (llm cells)
    call_tool(name, args) -> value                        (tool cells)

Binding config (JSON):

    {
      "bindings": {
        "llm":    {"provider": "minimax", "model": "MiniMax-Text-01",
                   "params": {"max_tokens": 400, "temperature": 0.7}},
        "search": {"provider": "stub"}
      }
    }

Keys are the names cells carry: a tool cell's `tool` name, and the
literal name "llm" for llm cells -- unless a binding is keyed by a
specific cell id, which wins for that cell. Providers in this build:
"minimax" (llm cells; the connector's documented surrogate route --
see HOST.md) and "stub" (the runtime's deterministic stubs, for tools
or for dry host runs). An unbound name is a named refusal, never a
silent default.

Usage: python -m lanesheet.host <sheet.json> <bindings.json> [--library DIR]

Sheet references resolve against a sheet library: DIR when --library
is given, else the sheet's own directory (the interpreter CLI's
convention).
"""

import json
import sys
import urllib.request
from pathlib import Path

from . import common, runtime

_NO_OVERRIDE = object()

# The custom-connector credential helper's documented location. It
# attaches an `hsurr:*` surrogate credential to a request; the raw
# credential never appears in this process, this file, or any output.
_CREDENTIALS_BIN = "/opt/muse/skills/custom-connector-setup/bin"

MINIMAX_API_URL = "https://api.minimax.io/v1/chat/completions"
MINIMAX_DEFAULT_MODEL = "MiniMax-Text-01"


class HostError(Exception):
    """A named host-layer refusal (binding, provider, transport)."""

    def __init__(self, name, detail=""):
        self.name = name
        super().__init__(f"{name}: {detail}" if detail else name)


def _fail(name, detail):
    raise HostError(name, detail)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class StubProvider:
    """The runtime's deterministic stubs, behind the provider interface.

    Used for tool names in this build, and for llm cells when a host
    run wants the piping exercised without a live call. Traces from
    such a run still carry the host header and name this provider, so
    they cannot be mistaken for conformance traces either.
    """

    name = "stub"

    def describe(self, binding):
        return {"provider": "stub"}

    def complete(self, prompt, system=None, params=None):
        try:
            return runtime.llm_complete(prompt, system)
        except runtime.StubError as exc:
            raise HostError(exc.name, str(exc)) from exc

    def call_tool(self, name, args):
        try:
            return runtime.call_tool(name, args)
        except runtime.StubError as exc:
            raise HostError(exc.name, str(exc)) from exc


class MiniMaxProvider:
    """MiniMax chat completions via the connector's documented route.

    Follows custom.legacy-minimax/CONNECTOR.md exactly: the request is
    built with urllib, the stored `custom.minimax` credential is
    attached as a surrogate by dynamic_credentials.add_surrogate_to_
    request (restricted to api.minimax.io), and the JSON body is read
    with read_json_response. No key is printed, logged, or persisted
    anywhere by this code.
    """

    name = "minimax"

    def describe(self, binding):
        return {"provider": "minimax", "model": binding.get("model", MINIMAX_DEFAULT_MODEL)}

    def complete(self, prompt, system=None, params=None):
        params = params or {}
        model = params.pop("model", MINIMAX_DEFAULT_MODEL)
        if not isinstance(prompt, str):
            raise HostError("NonStringPrompt", f"llm prompt input must be a string, got {type(prompt).__name__}")
        if system is not None and not isinstance(system, str):
            raise HostError("NonStringPrompt", f"llm system input must be a string, got {type(system).__name__}")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": params.get("max_tokens", 1000),
            "temperature": params.get("temperature", 0.7),
        }).encode("utf-8")

        sys.path.insert(0, _CREDENTIALS_BIN)
        try:
            from dynamic_credentials import add_surrogate_to_request, read_json_response
        except ImportError as exc:
            raise HostError("CredentialRouteUnavailable", f"dynamic_credentials not importable: {exc}") from exc

        req = urllib.request.Request(MINIMAX_API_URL, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        add_surrogate_to_request(req, "custom.minimax", allowed_hosts=["api.minimax.io"])
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            data = read_json_response(resp)
        except Exception as exc:  # transport / HTTP / auth surface, named once
            raise HostError("ProviderError", f"minimax request failed: {exc}") from exc

        base = data.get("base_resp") or {}
        if base.get("status_code", 0) != 0:
            raise HostError("ProviderError", f"minimax status {base.get('status_code')}: {base.get('status_msg')}")
        choices = data.get("choices") or []
        if not choices:
            raise HostError("ProviderError", "minimax returned no choices")
        content = (choices[0].get("message") or {}).get("content")
        if not isinstance(content, str):
            raise HostError("ProviderError", "minimax choice carried no string content")
        return content

    def call_tool(self, name, args):
        _fail("ProviderError", "the minimax provider serves llm cells, not tools")


PROVIDERS = {"stub": StubProvider, "minimax": MiniMaxProvider}


# ---------------------------------------------------------------------------
# Binding config
# ---------------------------------------------------------------------------

def load_bindings(path):
    with open(path, "r", encoding="utf-8") as fh:
        config = json.load(fh)
    if not isinstance(config, dict) or set(config) - {"bindings"}:
        _fail("BindingError", "binding config is an object with a single 'bindings' key")
    bindings = config.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        _fail("BindingError", "binding config requires a non-empty 'bindings' object")
    for key, binding in bindings.items():
        if not isinstance(binding, dict) or set(binding) - {"provider", "model", "params"}:
            _fail("BindingError", f"binding {key!r} may carry only provider/model/params")
        provider = binding.get("provider")
        if provider not in PROVIDERS:
            _fail("UnknownProvider", f"binding {key!r}: no provider named {provider!r}")
        if "params" in binding and not isinstance(binding["params"], dict):
            _fail("BindingError", f"binding {key!r}: 'params' must be an object")
    return bindings


def _binding_for(bindings, cell):
    """The binding a cell resolves to: cell id first, then its name."""
    if cell["id"] in bindings:
        return cell["id"], bindings[cell["id"]]
    name = "llm" if cell["kind"] == "llm" else cell.get("tool") if cell["kind"] == "tool" else None
    if name is not None and name in bindings:
        return name, bindings[name]
    return None, None


# ---------------------------------------------------------------------------
# Host runner
# ---------------------------------------------------------------------------

def evaluate_cell_host(cell, values, bindings, providers, value_override=_NO_OVERRIDE):
    """Compute one non-`sheet` cell's output from the values map.

    `value_override` mirrors the interpreter: a sub-sheet invocation's
    bound `value` cell computes the piped value in place of its
    constant.
    """
    kind = cell["kind"]
    inputs = {port: values[src] for port, src in cell.get("inputs", {}).items()}
    if kind == "value":
        output = cell["value"] if value_override is _NO_OVERRIDE else value_override
    elif kind == "prompt":
        output = runtime.render_template(cell["template"], inputs)
    elif kind == "branch":
        marker = ("equals" in cell, cell.get("equals"))
        output = runtime.select_branch(inputs["cond"], inputs["then"], inputs["else"], marker)
    elif kind in ("llm", "tool"):
        key, binding = _binding_for(bindings, cell)
        if binding is None:
            what = "llm" if kind == "llm" else f"tool {cell['tool']!r}"
            _fail("UnboundName", f"cell {cell['id']!r}: no binding for {what}")
        provider = providers[binding["provider"]]
        params = dict(binding.get("params", {}))
        if binding.get("model") is not None:
            params["model"] = binding["model"]
        try:
            if kind == "llm":
                output = provider.complete(inputs["prompt"], inputs.get("system"), params)
            else:
                output = provider.call_tool(cell["tool"], inputs)
        except runtime.StubError as exc:
            raise HostError(exc.name, f"cell {cell['id']!r}: {exc}") from exc
    else:  # pragma: no cover - validation guarantees a known kind
        raise HostError("UnknownCellKind", f"cell {cell['id']!r}: {kind!r}")
    return inputs, output


def _collect_resolved(sheet, bindings, providers, resolve, resolved):
    """Walk a sheet in execution order, recording resolved bindings.

    `sheet` cells recurse into their referenced sheet at the point
    they occur, so the header names the bindings a run resolves to at
    every rung -- interiors included -- in first-resolution order.
    Returns True iff any resolved binding is a live (non-stub)
    provider. The sheet is already validated, so every reference
    resolves and the walk terminates.
    """
    live = False
    for cell in common.canonical_order(sheet):
        if cell["kind"] in ("llm", "tool"):
            key, binding = _binding_for(bindings, cell)
            if binding is not None and key not in resolved:
                resolved[key] = providers[binding["provider"]].describe(binding)
                if binding["provider"] != "stub":
                    live = True
        elif cell["kind"] == "sheet":
            inner = common.load_ref(resolve, cell["sheet"])
            if _collect_resolved(inner, bindings, providers, resolve, resolved):
                live = True
    return live


def _run_host(sheet, bindings, providers, resolve, prefix, overrides):
    """Execute a validated sheet with bindings. Returns (lines, values).

    Mirrors the interpreter's recursion exactly: a `sheet` cell emits
    ONE boundary line (its own inputs and the declared boundary
    output), followed immediately by the interior sheet's section,
    whose cell ids carry the accumulated prefix. `overrides` maps
    this invocation's bound interior `value` cells to the values
    piped in across the boundary; bindings apply unchanged at every
    rung.
    """
    values = {}
    lines = []
    for cell in common.canonical_order(sheet):
        cell_id = cell["id"]
        if cell["kind"] == "sheet":
            inputs = {port: values[src] for port, src in cell.get("inputs", {}).items()}
            inner = common.load_ref(resolve, cell["sheet"])
            bind = cell.get("bind", {})
            if "each" in cell:
                # The 0.3 iteration mode, mirroring the interpreter:
                # validate the fan-out before any element invocation,
                # run the interior once per element with the fixed
                # bindings plus the element, collect the boundary
                # outputs in element order.
                each_port = cell["each"]
                try:
                    elements = runtime.each_elements(inputs[each_port])
                except runtime.StubError as exc:
                    raise HostError(exc.name, f"cell {cell_id!r}: {exc}") from exc
                element_target = next(t for t, p in bind.items() if p == each_port)
                fixed = {
                    target: inputs[port]
                    for target, port in bind.items()
                    if port != each_port
                }
                sections = []
                runs = []
                for i, element in enumerate(elements):
                    overrides = dict(fixed)
                    overrides[element_target] = element
                    inner_lines, inner_values = _run_host(
                        inner, bindings, providers, resolve,
                        f"{prefix}{cell_id}[{i}]/", overrides,
                    )
                    sections.extend(inner_lines)
                    runs.append(inner_values)
                if "output" in cell:
                    output = [run[cell["output"]] for run in runs]
                else:
                    output = {
                        name: [run[target] for run in runs]
                        for name, target in cell["outputs"].items()
                    }
                values[cell_id] = output
                lines.append(
                    runtime.make_trace_line(prefix + cell_id, "sheet", inputs, output)
                )
                lines.extend(sections)
                continue
            inner_overrides = {
                target: inputs[port] for target, port in bind.items()
            }
            inner_lines, inner_values = _run_host(
                inner, bindings, providers, resolve, prefix + cell_id + "/", inner_overrides
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
        inputs, output = evaluate_cell_host(
            cell, values, bindings, providers, value_override=override
        )
        values[cell_id] = output
        lines.append(runtime.make_trace_line(prefix + cell_id, cell["kind"], inputs, output))
    return lines, values


def run_sheet_host(sheet, bindings, resolve=None):
    """Execute a sheet with real bindings. Returns trace lines.

    Line 0 is the host header record; the remaining lines are the
    canonical trace records, identical in format to the interpreter's.
    `resolve` is the sheet library (see common.local_resolver); it is
    required iff the sheet (transitively) contains `sheet` cells --
    without one, validation refuses them with UnresolvedSheetRef, as
    it refuses a reference the supplied library cannot resolve.
    """
    common.validate_sheet(sheet, resolve=resolve)
    providers = {}
    for binding in bindings.values():
        providers.setdefault(binding["provider"], PROVIDERS[binding["provider"]]())

    # The header names only the bindings this run actually resolves
    # to, in resolution order across all rungs, and whether any of
    # them is a live (non-stub) provider.
    resolved = {}
    live = _collect_resolved(sheet, bindings, providers, resolve, resolved)
    header = {
        "bindings": resolved,
        "kind": "host-header",
        "live": live,
        "run": "live" if live else "host-stub",
        "sheet": sheet["id"],
    }
    lines = [runtime.canonical_json(header)]

    body, _values = _run_host(sheet, bindings, providers, resolve, "", {})
    lines.extend(body)
    return lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    library = None
    if "--library" in argv:
        at = argv.index("--library")
        if at + 1 >= len(argv):
            print(
                "usage: python -m lanesheet.host <sheet.json> <bindings.json> [--library DIR]",
                file=sys.stderr,
            )
            return 2
        library = argv[at + 1]
        del argv[at:at + 2]
    if len(argv) != 2:
        print(
            "usage: python -m lanesheet.host <sheet.json> <bindings.json> [--library DIR]",
            file=sys.stderr,
        )
        return 2
    sheet_path = Path(argv[0])
    try:
        sheet = common.load_sheet(sheet_path)
        bindings = load_bindings(argv[1])
        resolve = common.local_resolver(
            library if library is not None else sheet_path.parent
        )
        lines = run_sheet_host(sheet, bindings, resolve=resolve)
    except (common.LaneSheetError, HostError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
