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

Usage: python -m lanesheet.host <sheet.json> <bindings.json>
"""

import json
import sys
import urllib.request

from . import common, runtime

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

def evaluate_cell_host(cell, values, bindings, providers):
    kind = cell["kind"]
    inputs = {port: values[src] for port, src in cell.get("inputs", {}).items()}
    if kind == "value":
        output = cell["value"]
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


def run_sheet_host(sheet, bindings):
    """Execute a sheet with real bindings. Returns trace lines.

    Line 0 is the host header record; the remaining lines are the
    canonical trace records, identical in format to the interpreter's.
    """
    common.validate_sheet(sheet)
    providers = {}
    for binding in bindings.values():
        providers.setdefault(binding["provider"], PROVIDERS[binding["provider"]]())

    # The header names only the bindings this sheet actually resolves
    # to, in resolution order, and whether any of them is a live
    # (non-stub) provider.
    resolved = {}
    live = False
    for cell in common.canonical_order(sheet):
        if cell["kind"] in ("llm", "tool"):
            key, binding = _binding_for(bindings, cell)
            if binding is not None and key not in resolved:
                resolved[key] = providers[binding["provider"]].describe(binding)
                if binding["provider"] != "stub":
                    live = True
    header = {
        "bindings": resolved,
        "kind": "host-header",
        "live": live,
        "run": "live" if live else "host-stub",
        "sheet": sheet["id"],
    }
    lines = [runtime.canonical_json(header)]

    values = {}
    for cell in common.canonical_order(sheet):
        inputs, output = evaluate_cell_host(cell, values, bindings, providers)
        values[cell["id"]] = output
        lines.append(runtime.make_trace_line(cell["id"], cell["kind"], inputs, output))
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python -m lanesheet.host <sheet.json> <bindings.json>", file=sys.stderr)
        return 2
    try:
        sheet = common.load_sheet(argv[0])
        bindings = load_bindings(argv[1])
        lines = run_sheet_host(sheet, bindings)
    except (common.LaneSheetError, HostError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
