"""records_to_sheet.py -- reconstruct a lane sheet by FOLDING records.

The sheet is rebuilt from the fold's derived state and nothing else:
the record files are read in raw directory order (never sorted --
arrival order is not an input), handed to the fold (fold.py, a
labelled minimal port of git.pp's derive), and the sheet is assembled
from the winning values of the declared keys. No field of the output
is read from a record file directly; if the fold changes its mind
about a key (a conflict, an override), the reconstruction follows
the fold.

Assembly, from derived state alone:
    sheet.id / sheet.lanesheet / sheet.title / sheet.outputs
    sheet.lanes = [{id, cells: [ids]}]         -- structure and order
    per cell id, from the structure:
        cell.<id>.kind  +  cell.<id>.def  +  cell.<id>.inputs
        (the inputs key is emitted only when the map is non-empty,
        matching the sheet format's own shape)

Usage: python3 records_to_sheet.py <records-dir> [out.sheet.json]
Prints the fold's conflicts and orphans to stderr -- the state was
decided by the fold, but a contested cell is never hidden.
Stdlib only. SuperInstance.
"""

import json
import sys
from pathlib import Path

import fold


def load_records(records_dir):
    """Every record in the directory, in raw (unsorted) read order."""
    records = []
    for path in Path(records_dir).iterdir():
        if path.suffix != ".json":
            continue
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, list):
            records.extend(parsed)
        else:
            records.append(parsed)
    return records


def reconstruct(records):
    """Records -> (sheet, fold result). The sheet comes from the fold."""
    result = fold.derive(records)
    state = result["state"]

    sheet = {"id": state["sheet.id"], "lanesheet": state["sheet.lanesheet"]}
    if "sheet.title" in state:
        sheet["title"] = state["sheet.title"]

    lanes = []
    for lane in state["sheet.lanes"]:
        cells = []
        for cid in lane["cells"]:
            cell = {"id": cid, "kind": state[f"cell.{cid}.kind"]}
            cell.update(state[f"cell.{cid}.def"])
            inputs = state[f"cell.{cid}.inputs"]
            if inputs:
                cell["inputs"] = inputs
            cells.append(cell)
        lanes.append({"id": lane["id"], "cells": cells})
    sheet["lanes"] = lanes

    if "sheet.outputs" in state:
        sheet["outputs"] = state["sheet.outputs"]
    return sheet, result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2):
        print("usage: python3 records_to_sheet.py <records-dir> [out.json]",
              file=sys.stderr)
        return 2
    records = load_records(argv[0])
    sheet, result = reconstruct(records)
    for conflict in result["conflicts"]:
        print(f"conflict: {conflict}", file=sys.stderr)
    if result["orphans"]:
        print(f"orphans: {result['orphans']}", file=sys.stderr)
    text = json.dumps(sheet, indent=2, sort_keys=True) + "\n"
    if len(argv) == 2:
        Path(argv[1]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
