#!/usr/bin/env python3
"""lanesheet_emit.py -- DOWNWARD SPIKE emitter (SuperInstance).

Takes a trivial lane-sheet workflow description (JSON) and emits the
Quilt-fabric opcode sequence that the mapping in DOWNWARD.md predicts
for it: a LOAD program (BIND/LINK), a RUN program (EFFECT/TICK/VIEW
plus off-fabric PORT annotations), and the canonical state hash of the
bound fabric image.

This is a spike: a compiler-shaped listing generator, not a compiler.
It does not simulate execution and does not emit Verilog or QUF bytes.

Stdlib only. Usage:
    python3 lanesheet_emit.py WORKFLOW.json
    python3 lanesheet_emit.py --selftest
"""

import json
import struct
import sys

# --- FNV-1a 64 (Charter: offset/prime as pinned in quilt-verilog README) ---
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK64 = (1 << 64) - 1


def fnv1a(data: bytes) -> int:
    h = FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * FNV_PRIME) & MASK64
    return h


# --- Canonical per-cell serialization (Charter S1, via DOSSIER S2 and the
# --- quilt-verilog README): type(1) || id(8 LE) || dials(32 LE) ||
# --- neighbors(8*N LE). Type 0x01 = value cell, 0x02 = formula cell
# --- (charter extension point). ---
TYPE_BYTE = {"value": 0x01, "prompt": 0x02, "tool": 0x02,
             "program": 0x02, "listener": 0x02}

# Dial names at addresses 0..10 per QUF-SPEC.md S6.1 (q_dialfile map);
# 11..15 are reserved there and still round-tripped.
DIAL_NAMES = {0: "ETA_F", 1: "ETA_S", 2: "KF", 3: "KS", 4: "KA",
              5: "THRESH", 6: "REFR", 7: "COS_MIN", 8: "P0E",
              9: "MODE", 10: "HL"}

# Fields that would put text/code into fabric state. The fabric has no
# text type (QUF writer refuses floats and carries no string state;
# QUIL's only type is int<PW>), so a workflow carrying any of these is
# refused, loudly, instead of silently dropping the content.
TEXT_FIELDS = {"prompt_text", "template", "system", "code", "body",
               "text", "script", "query_text"}


def fail(msg):
    raise SystemExit(f"EMIT-REFUSED: {msg}")


def check_no_floats(obj, path="$"):
    if isinstance(obj, float):
        fail(f"float at {path}: the QUF reference writer refuses to emit "
             f"floats (QUF-SPEC S4); quantize before lowering")
    if isinstance(obj, dict):
        for k, v in obj.items():
            check_no_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            check_no_floats(v, f"{path}[{i}]")


def validate(wf):
    check_no_floats(wf)
    cells = wf.get("cells")
    if not cells:
        fail("workflow has no cells")
    ids = set()
    for c in cells:
        for f in TEXT_FIELDS & set(c):
            fail(f"cell {c.get('name')!r} carries {f!r}: text cannot "
                 f"enter the fabric (no string type in QUF state; QUIL "
                 f"S1.5 quarantines content off-fabric). Name the cell; "
                 f"keep its text in the sheet layer.")
        if c["kind"] not in TYPE_BYTE:
            fail(f"unknown cell kind {c['kind']!r}")
        if not isinstance(c["id"], int) or c["id"] <= 0:
            fail(f"cell id must be a positive int, got {c['id']!r}")
        if c["id"] in ids:
            fail(f"duplicate cell id {c['id']}")
        ids.add(c["id"])
        d = c.get("dials", [0] * 16)
        if len(d) != 16 or any(not isinstance(x, int) or
                                not 0 <= x <= 0xFFFF for x in d):
            fail(f"cell {c['id']}: dials must be 16 ints in u16 range")
        c.setdefault("dials", [0] * 16)
    for e in wf.get("edges", []):
        if e["from"] not in ids or e["to"] not in ids:
            fail(f"edge {e} names an unbound cell")
        if not isinstance(e["base"], int) or not 0 <= e["base"] <= 0xFFFF:
            fail(f"edge {e}: base must be a u16 int (quant.edges)")


def serialize_cell(cell, neighbors):
    out = bytearray()
    out.append(TYPE_BYTE[cell["kind"]])
    out += struct.pack("<Q", cell["id"])
    out += struct.pack("<16H", *cell["dials"])
    for n in neighbors:
        out += struct.pack("<Q", n)
    return bytes(out)


def emit(wf):
    validate(wf)
    cells = sorted(wf["cells"], key=lambda c: c["id"])
    by_id = {c["id"]: c for c in cells}
    edges = wf.get("edges", [])
    neighbors = {c["id"]: sorted({e["to"] for e in edges
                                  if e["from"] == c["id"]})
                 for c in cells}
    lines = []
    lines.append(f"; lanesheet_emit spike -- workflow {wf['name']!r}")
    lines.append("; LOAD program (mapping: DOWNWARD.md S1). Response "
                 "annotations are the")
    lines.append("; fabric's own discipline (quilt-verilog README, 5+1 "
                 "table): BIND/LINK/VIEW")
    lines.append("; are answered ACK/NAK; EFFECT and TICK carry no "
                 "response promise.")
    lines.append("")
    lines.append("; --- LOAD: bind cells ---")
    slot = {}
    for c in cells:
        lines.append(f"BIND   cell {c['id']:<3} ; first bind sets cell_id "
                     f"({c['kind']} cell {c['name']!r})  -> ACK")
        for addr, val in enumerate(c["dials"]):
            if val:
                nm = DIAL_NAMES.get(addr, "reserved")
                lines.append(f"BIND   cell {c['id']:<3} dial[{addr}] {nm} "
                             f"<- {val}  -> ACK")
        if c["kind"] in ("prompt", "tool"):
            lines.append(f"EXTERN cell {c['id']:<3} {c['name']!r} "
                         f"; NOT AN OPCODE -- a black-box port (QUIL "
                         f"propose / fabric Law 4).")
            lines.append(f"       ; the cell's text and behaviour stay in "
                         f"the sheet layer; only an integer")
            lines.append(f"       ; shadow and the ACK/NAK discipline "
                         f"cross into the fabric.")
        elif c["kind"] == "program":
            lines.append(f"NOTE   cell {c['id']:<3} {c['name']!r} "
                         f"; program semantics do NOT lower (DOWNWARD.md "
                         f"S1) -- the fabric")
            lines.append(f"       ; image is a plain cell; only "
                         f"integration/threshold behaviour exists here.")
        elif c["kind"] == "listener":
            lines.append(f"NOTE   cell {c['id']:<3} {c['name']!r} "
                         f"; listener: pull form is VIEW; push form is "
                         f"threshold wiring")
            lines.append(f"       ; on the watched cell's fanout. No "
                         f"subscription object exists on-fabric.")
    lines.append("")
    lines.append("; --- LOAD: link edges (wiring as data) ---")
    for e in edges:
        s = slot.get(e["from"], 0)
        slot[e["from"]] = s + 1
        lines.append(f"LINK   cell {e['from']:<3} slot {s} := "
                     f"{{peer {e['to']}, base {e['base']}}}  -> ACK")
    lines.append("")
    lines.append("; --- RUN: one pass, per the time mapping "
                 "(DOWNWARD.md S1b) ---")
    lines.append("; A workflow step = a tick window: ops issued and "
                 "answered, propagation at")
    lines.append("; one edge per TICK, the step commits at a tick "
                 "boundary (super-step shape).")
    step = 0
    for ev in wf.get("run", []):
        step += 1
        lines.append(f"; STEP {step}")
        if "inject" in ev:
            iv = ev["inject"]
            lines.append(f"EFFECT cell {iv['cell']:<3} src PORT dat "
                         f"{iv['dat']}  ; ingress flit (Law 4 generic IO "
                         f"contract).")
            lines.append(f"       ; EFFECT is not answered; an unbound "
                         f"src is dropped silently")
            lines.append(f"       ; (README), so the sheet's loader "
                         f"binds the port as the src of record.")
            lines.append(f"TICK   ; decay sweep, leak, fire test on "
                         f"cell {iv['cell']}: if act >= THRESH and "
                         f"REFR = 0,")
            for e in edges:
                if e["from"] == iv["cell"]:
                    lines.append(f"       ; fanout EFFECT -> cell "
                                 f"{e['to']} (one-tick edge delay: the "
                                 f"step's effect")
                    lines.append(f"       ; is visible downstream only "
                                 f"from this boundary)")
        elif "port_return" in ev:
            pv = ev["port_return"]
            c = by_id[pv["cell"]]
            dat = pv["dat"]
            what = (f"integer shadow dat {dat}" if dat is not None
                    else "completion only, no payload word")
            lines.append(f"PORT-IN cell {pv['cell']:<3} ; NOT AN OPCODE "
                         f"-- the {c['kind']} port {c['name']!r} "
                         f"answers: {what},")
            lines.append(f"       ; closed by ACK (a refusal / timeout "
                         f"is NAK and the step aborts). The wait")
            lines.append(f"       ; happened off-fabric, between tick "
                         f"windows; the fabric never waits.")
            outs = [e for e in edges if e["from"] == pv["cell"]]
            if outs:
                lines.append(f"TICK   ; fanout from cell {pv['cell']} "
                             f"to {', '.join('cell %d' % e['to'] for e in outs)} "
                             f"at this boundary")
    if cells:
        last = cells[-1]["id"]
        lines.append(f"VIEW   cell {last:<3} ; read act / wsum(edges) / "
                     f"a dial -- response flit carries the value  -> ACK")
    lines.append("")
    lines.append("; --- Bound fabric image (post-LOAD, pre-run) ---")
    blob = bytearray()
    for c in cells:
        h = fnv1a(serialize_cell(c, neighbors[c["id"]]))
        blob += serialize_cell(c, neighbors[c["id"]])
        lines.append(f"; cell {c['id']:<3} canonical hash "
                     f"0x{h:016x}")
    lines.append(f"; fabric hash (spike convention: FNV-1a over cells "
                 f"concatenated in ascending")
    lines.append(f"; id order; the Charter pins the per-cell bytes, "
                 f"not this composition)")
    lines.append(f"; = 0x{fnv1a(bytes(blob)):016x}")
    return "\n".join(lines) + "\n"


def selftest():
    cell = {"id": 1, "kind": "value", "name": "contract",
            "dials": list(range(1, 17))}
    h = fnv1a(serialize_cell(cell, [2, 3, 4]))
    expect = 0xE435D91D6D92A1D8
    status = "PASS" if h == expect else "FAIL"
    print(f"selftest: contract cell hash 0x{h:016x} "
          f"(expect 0x{expect:016x}) -- {status}")
    return 0 if h == expect else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if len(argv) != 2:
        print(__doc__)
        return 2
    with open(argv[1], "r", encoding="utf-8") as f:
        wf = json.load(f)
    sys.stdout.write(emit(wf))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
