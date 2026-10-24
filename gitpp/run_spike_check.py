"""run_spike_check.py -- the round-trip proof for the git.pp spike.

For both fixtures (linear-chain, sheet-reused):
    sheet -> records -> FOLD -> sheet'
  1. sheet' canonical-equals the original sheet (the lane-sheets
     runtime canonical JSON: sorted keys, compact separators);
  2. the fold's state is identical when the same records are fed in
     a shuffled order -- arrival order is never an input;
  3. the lane-sheet interpreter's trace on sheet' is byte-identical
     to the fixture's golden trace.

Plus two conflict probes on linear-chain's records, pinning what the
fold decides when two records disagree about one cell (the claims
GITPP-SPIKE.md makes about conflicts are proven HERE, not argued):
  4. an override-kind record redefining a cell wins by class, and the
     reconstruction carries the override's definition;
  5. a sibling task record redefining a cell loses the tie-break to
     the original (equal cleanliness, smallest id), and the conflict
     names it as loser;
  6. a task record that DESCENDS from the original cell record (it
     saw the definition and built on it) dominates it by ancestry,
     same class, no tie-break needed.

Usage: python3 run_spike_check.py
Stdlib only (plus the lane-sheets package). SuperInstance.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent if (HERE.parent / "lanesheet").is_dir() else Path.home() / "workspace" / "lane-sheets-repo"
FIXTURES = REPO / "fixtures"
OUT = HERE / "out"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from lanesheet import common, interpret, runtime  # noqa: E402

import fold  # noqa: E402
import records_to_sheet  # noqa: E402
import sheet_to_records  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" -- {detail}" if detail else ""))


def round_trip(fixture):
    sheet_path = FIXTURES / f"{fixture}.sheet.json"
    golden = (FIXTURES / f"{fixture}.golden.jsonl").read_bytes()
    original = json.loads(sheet_path.read_text(encoding="utf-8"))
    common.validate_sheet(
        original, resolve=common.local_resolver(FIXTURES)
    )

    records = sheet_to_records.convert(original)
    records_dir = OUT / fixture / "records"
    sheet_to_records.write_records(records, records_dir)

    loaded = records_to_sheet.load_records(records_dir)
    sheet2, result = records_to_sheet.reconstruct(loaded)

    check(
        f"{fixture}: sheet' canonical-equals sheet",
        runtime.canonical_json(sheet2) == runtime.canonical_json(original),
    )

    shuffled = list(reversed(loaded))
    state_a = fold.derive(loaded)["state"]
    state_b = fold.derive(shuffled)["state"]
    check(
        f"{fixture}: fold state is arrival-order independent",
        runtime.canonical_json(state_a) == runtime.canonical_json(state_b),
    )

    check(
        f"{fixture}: uncontested conversion (no conflicts, no orphans)",
        result["conflicts"] == [] and result["orphans"] == [],
        f"conflicts={result['conflicts']} orphans={result['orphans']}",
    )

    lines = interpret.run_sheet(
        sheet2, resolve=common.local_resolver(FIXTURES)
    )
    trace = ("\n".join(lines) + "\n").encode("utf-8")
    check(f"{fixture}: interpreter trace on sheet' == golden", trace == golden)
    return loaded


def override_probe(records):
    override = {
        "id": "override-prompt-1",
        "kind": "override",
        "parents": ["cell-reasoning.prompt"],
        "effects": {
            "cell.reasoning.prompt.def": {"template": "OVERRIDE: {{topic}}"}
        },
    }
    sheet2, result = records_to_sheet.reconstruct(records + [override])
    conflict = next(
        (c for c in result["conflicts"] if c["key"] == "cell.reasoning.prompt.def"),
        None,
    )
    cell = next(
        c for lane in sheet2["lanes"] for c in lane["cells"]
        if c["id"] == "reasoning.prompt"
    )
    check(
        "probe-override: the override record wins the cell's def key",
        conflict is not None
        and conflict["winner"] == "override-prompt-1"
        and conflict["losers"] == ["cell-reasoning.prompt"]
        and cell["template"] == "OVERRIDE: {{topic}}",
        f"conflict={conflict}",
    )


def sibling_probe(records):
    sibling = {
        "id": "cell-reasoning.prompt--alt",
        "kind": "task",
        "parents": ["cell-input.topic"],
        "effects": {
            "cell.reasoning.prompt.def": {"template": "SIBLING: {{topic}}"}
        },
    }
    sheet2, result = records_to_sheet.reconstruct(records + [sibling])
    conflict = next(
        (c for c in result["conflicts"] if c["key"] == "cell.reasoning.prompt.def"),
        None,
    )
    cell = next(
        c for lane in sheet2["lanes"] for c in lane["cells"]
        if c["id"] == "reasoning.prompt"
    )
    check(
        "probe-sibling: equal-class sibling loses the tie-break, named as loser",
        conflict is not None
        and conflict["winner"] == "cell-reasoning.prompt"
        and conflict["losers"] == ["cell-reasoning.prompt--alt"]
        and cell["template"] == "Explain {{topic}} in one sentence.",
        f"conflict={conflict}",
    )


def descendant_probe(records):
    descendant = {
        "id": "cell-reasoning.prompt--v2",
        "kind": "task",
        "parents": ["cell-reasoning.prompt"],
        "effects": {
            "cell.reasoning.prompt.def": {"template": "V2: {{topic}}"}
        },
    }
    sheet2, result = records_to_sheet.reconstruct(records + [descendant])
    conflict = next(
        (c for c in result["conflicts"] if c["key"] == "cell.reasoning.prompt.def"),
        None,
    )
    cell = next(
        c for lane in sheet2["lanes"] for c in lane["cells"]
        if c["id"] == "reasoning.prompt"
    )
    check(
        "probe-descendant: a descendant task record dominates its ancestor",
        conflict is not None
        and conflict["winner"] == "cell-reasoning.prompt--v2"
        and conflict["losers"] == ["cell-reasoning.prompt"]
        and cell["template"] == "V2: {{topic}}",
        f"conflict={conflict}",
    )


def main():
    linear_records = round_trip("linear-chain")
    round_trip("sheet-reused")
    override_probe(linear_records)
    sibling_probe(linear_records)
    descendant_probe(linear_records)
    passed = sum(1 for _n, ok in RESULTS if ok)
    print(f"SUMMARY: {passed}/{len(RESULTS)} PASS")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
