#!/usr/bin/env python3
"""Lane-sheet conformance: interpreter vs lifted LangGraph, byte-for-byte.

For every positive fixture in fixtures/:
  1. run the reference interpreter and compare its trace with the
     fixture's golden trace (fixtures/<name>.golden.jsonl);
  2. lift the sheet to a standalone LangGraph module, run it, and
     compare its trace with the interpreter's, byte-for-byte.

For every negative fixture (fixtures/negative-*.sheet.json with a
<name>.expected.json sidecar naming the expected refusal): both the
interpreter and the lifter must refuse with exactly that error name.
A sidecar may declare "phase": "runtime" for a data-dependent
refusal (0.3: a non-list `each` input, an over-cap fan-out): the
sheet then validates and lifts cleanly, the interpreter refuses
while running, and the lifted module must exit non-zero with the
same refusal name in its output.

Sheet references (0.2 `sheet` cells) resolve against the fixtures
directory itself -- the fixture-local library: linear-chain doubles
as an inner sheet, and word-frame / leaf-define / mid-wrap are inner
sheets that are also standalone fixtures in their own right.

Run with the venv python so langgraph is importable:
    .venv/bin/python run_conformance.py
(Lifted modules are executed with the same interpreter.)
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
LIFTED = ROOT / "lifted"
sys.path.insert(0, str(ROOT))

from lanesheet import common, interpret, lift_langgraph  # noqa: E402

RESOLVER = common.local_resolver(FIXTURES)


def trace_bytes(lines):
    return ("\n".join(lines) + "\n").encode("utf-8")


def check_positive(sheet_path):
    name = sheet_path.name.replace(".sheet.json", "")
    problems = []
    sheet = common.load_sheet(sheet_path)
    interp_lines = interpret.run_sheet(sheet, resolve=RESOLVER)
    interp = trace_bytes(interp_lines)

    golden_path = FIXTURES / f"{name}.golden.jsonl"
    if not golden_path.exists():
        problems.append("golden trace missing")
    elif golden_path.read_bytes() != interp:
        problems.append("interpreter trace != golden trace")

    LIFTED.mkdir(exist_ok=True)
    lifted_path = LIFTED / f"{name}_lifted.py"
    lifted_path.write_text(lift_langgraph.lift(sheet, resolve=RESOLVER), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(lifted_path)],
        capture_output=True,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        problems.append(f"lifted module exited {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:400]}")
    elif proc.stdout != interp:
        problems.append("lifted trace != interpreter trace")

    status = "PASS" if not problems else "FAIL"
    print(f"{status} {name} ({len(interp_lines)} trace lines)" + ("" if not problems else " -- " + "; ".join(problems)))
    return not problems


def check_negative(sheet_path):
    name = sheet_path.name.replace(".sheet.json", "")
    sidecar = json.loads((FIXTURES / f"{name}.expected.json").read_text(encoding="utf-8"))
    expected = sidecar["error"]
    phase = sidecar.get("phase", "validation")
    problems = []

    sheet = None
    try:
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
        interpret.run_sheet(sheet, resolve=RESOLVER)
        problems.append("interpreter accepted the sheet")
    except common.LaneSheetError as exc:
        if exc.name != expected:
            problems.append(f"interpreter refused with {exc.name}, expected {expected}")

    if sheet is not None and phase == "validation":
        try:
            lift_langgraph.lift(sheet, resolve=RESOLVER)
            problems.append("lifter accepted the sheet")
        except common.LaneSheetError as exc:
            if exc.name != expected:
                problems.append(f"lifter refused with {exc.name}, expected {expected}")
    elif sheet is not None and phase == "runtime":
        # The sheet validates and lifts cleanly; the refusal is in
        # the data, so it must fire when the lifted module RUNS.
        try:
            source = lift_langgraph.lift(sheet, resolve=RESOLVER)
        except common.LaneSheetError as exc:
            problems.append(f"lifter refused a runtime-phase sheet with {exc.name}")
            source = None
        if source is not None:
            LIFTED.mkdir(exist_ok=True)
            lifted_path = LIFTED / f"{name}_lifted.py"
            lifted_path.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(lifted_path)],
                capture_output=True,
                cwd=str(ROOT),
            )
            if proc.returncode == 0:
                problems.append("lifted module ran a sheet it should have refused at run time")
            elif expected.encode() not in proc.stderr:
                problems.append(
                    f"lifted module exited {proc.returncode} without naming {expected}: "
                    f"{proc.stderr.decode('utf-8', 'replace')[-300:]}"
                )

    status = "PASS" if not problems else "FAIL"
    print(f"{status} {name} (refusal: {expected})" + ("" if not problems else " -- " + "; ".join(problems)))
    return not problems


def main():
    positives = sorted(p for p in FIXTURES.glob("*.sheet.json") if not p.name.startswith("negative-"))
    negatives = sorted(FIXTURES.glob("negative-*.sheet.json"))
    results = [check_positive(p) for p in positives]
    results += [check_negative(p) for p in negatives]
    passed = sum(results)
    print(f"SUMMARY: {passed}/{len(results)} PASS")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
