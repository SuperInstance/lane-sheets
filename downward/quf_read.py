#!/usr/bin/env python3
"""quf_read.py -- QUF reader for lane-sheet images (SuperInstance).

Downward lane 2 companion to quf_write.py. Parses a QUF v1 image
(SuperInstance/quilt-verilog docs/QUF-SPEC.md) back into the value
cells, edges, and sheet state it carries, and verifies agreement the
shelf's way: the reconstructed fabric's canonical hash (Charter
serialization + FNV-1a 64, via lanesheet_emit.py's machinery) must
equal the source workflow's.

The parser is independent of the writer (no shared code but the
emitter's hash machinery, which is the contract being checked).
Structural validation implements the QUF-SPEC S5a checks that apply
to parsing -- magic/version/endian gates, walk bounds, u64 ceiling,
front-matter overlap, known-section size formulas, present-count
assertions, alignment, zero padding, KV length bounds, skippable
types -- each raising with its S5a reason code. It is a structural
parser, not the shelf's hostile-input reference implementation
(tools/quf.py); QUF-NOTES.md scopes the difference.

Unknown KV keys are skipped by type-derived size and unknown section
names via the table (S8 rules 1/3) -- that is how the writer's SKETCH
elements (lanesheet.* KVs, steps section) coexist with the standard
fabric image.

Stdlib only. Usage:
    python3 quf_read.py IMAGE.quf [--ignore-section=NAME]...
"""

import json
import struct
import sys
import zlib

import lanesheet_emit as emit

# GGUF value-type numbering (QUF-SPEC S4), duplicated deliberately:
# a reader that imports the writer's tables is not an independent
# check. Fixed sizes for scalar types; string/array are counted.
FIXED_SIZE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1,
              10: 8, 11: 8, 12: 8}
T_STRING, T_ARRAY = 8, 9
KNOWN_SECTIONS = ("dials", "edges", "routing", "ticks")


class QufError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code = code


class Cursor:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def take(self, n, what):
        if self.p + n > len(self.d):
            raise QufError("E10", f"truncated: {what} runs past EOF")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u32(self, what):
        return struct.unpack("<I", self.take(4, what))[0]

    def u64(self, what):
        return struct.unpack("<Q", self.take(8, what))[0]


def read_value(cur, vtype, what):
    """Decode one KV value; returns a Python value."""
    if vtype in FIXED_SIZE:
        raw = cur.take(FIXED_SIZE[vtype], what)
        fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
               6: "<f", 7: "<B", 10: "<Q", 11: "<q", 12: "<d"}[vtype]
        return struct.unpack(fmt, raw)[0]
    if vtype == T_STRING:
        n = cur.u32(what + " (string len)")
        if cur.p + n > len(cur.d):
            raise QufError("E17", f"KV string {what} length {n} "
                                  f"overruns file")
        return cur.take(n, what).decode("utf-8", "replace")
    if vtype == T_ARRAY:
        etype = cur.u32(what + " (array elem type)")
        if etype not in FIXED_SIZE:
            raise QufError("E18", f"array element type {etype} is not "
                                  f"fixed-size (S8 rule 2)")
        count = cur.u32(what + " (array count)")
        if cur.p + count * FIXED_SIZE[etype] > len(cur.d):
            raise QufError("E17", f"KV array {what} overruns file")
        return [read_value(cur, etype, what) for _ in range(count)]
    raise QufError("E18", f"undefined KV value type {vtype} (S8 rule 2)")


def parse(data):
    """Parse and structurally validate a QUF image. Returns a doc dict."""
    if len(data) < 16:
        raise QufError("E10", "file shorter than the 16-byte fixed header")
    cur = Cursor(data)
    magic = cur.take(4, "magic")
    if magic != b"QUF\x00":
        raise QufError("E7", f"bad magic {magic!r}")
    version = cur.u32("version")
    endian = cur.u32("endian")
    kv_count = cur.u32("kv_count")
    if version != 1:
        raise QufError("E8", f"version {version} != 1")
    if endian != 1:
        raise QufError("E9", f"endian word {endian} != 1")

    kv_list = []
    for _ in range(kv_count):
        nlen = cur.u32("kv name_len")
        if cur.p + nlen > len(data):
            raise QufError("E11", "kv name_len walks past EOF")
        name = cur.take(nlen, "kv name")
        vtype = cur.u32("kv value type")
        kv_list.append((name, vtype,
                        read_value(cur, vtype, f"kv {name!r}")))
    kv = {}
    for name, _, val in kv_list:
        kv[name.decode("utf-8", "replace")] = val

    edge_k = kv.get("edge.k", 8)
    if not (1 <= edge_k <= 16):
        raise QufError("E8", f"edge.k {edge_k} outside 1..16")
    align = kv.get("align", 32)

    section_count = cur.u32("section_count")
    sections = []
    for _ in range(section_count):
        nlen = cur.u32("section name_len")
        if cur.p + nlen > len(data):
            raise QufError("E11", "section name_len walks past EOF")
        name = cur.take(nlen, "section name").decode("utf-8", "replace")
        kind = cur.u32("section kind")
        offset = cur.u64("section offset")
        size = cur.u64("section size")
        sections.append({"name": name, "kind": kind,
                         "offset": offset, "size": size})
    table_end = cur.p

    names = [s["name"] for s in sections]
    if len(set(names)) != len(names):
        raise QufError("S5", "duplicate section names (S5)")
    prev_end, prev_off = None, None
    for s in sections:
        if s["offset"] > 0xFFFFFFFF or s["size"] > 0xFFFFFFFF \
                or s["offset"] + s["size"] >= 1 << 32:
            raise QufError("E12", f"section {s['name']}: u64 high word / "
                                  f"4 GiB ceiling (R5)")
        if prev_off is not None and s["offset"] <= prev_off:
            raise QufError("S5", "section offsets not strictly ascending "
                                 "(S5)")
        if prev_end is not None and s["offset"] < prev_end:
            raise QufError("S5", "sections overlap (S5)")
        prev_off = s["offset"]
        prev_end = s["offset"] + s["size"]
        if s["offset"] < table_end:
            raise QufError("E13", f"section {s['name']} payload overlaps "
                                  f"front matter (R6)")
        if s["offset"] % align:
            raise QufError("E15", f"section {s['name']} offset not a "
                                  f"multiple of align (R9)")
        if s["offset"] + s["size"] > len(data):
            raise QufError("E10", f"section {s['name']} extends past EOF")
        s["bytes"] = data[s["offset"]:s["offset"] + s["size"]]
    if len(data) % align:
        raise QufError("E15", "file length not a multiple of align (R9)")

    # Padding is zero everywhere outside front matter and payloads (R11).
    spans = sorted((s["offset"], s["offset"] + s["size"]) for s in sections)
    cursor = table_end
    for a, b in spans:
        if any(data[cursor:a]):
            raise QufError("E16", f"nonzero padding byte before section "
                                  f"at {a} (R11)")
        cursor = max(cursor, b)
    if any(data[cursor:]):
        raise QufError("E16", "nonzero trailing padding byte (R11)")

    # Known-section size formulas and present-count assertions (R7/R8).
    by_name = {s["name"]: s for s in sections}
    cell_count = kv.get("cell_count")
    if "dials" in by_name:
        if by_name["dials"]["size"] % 32:
            raise QufError("E14", "dials size not cell_count x 32 (R7)")
        derived = by_name["dials"]["size"] // 32
        if cell_count is not None and cell_count != derived:
            raise QufError("E14", f"cell_count KV {cell_count} != dials "
                                  f"rows {derived} (R8)")
        cell_count = derived
    if "ticks" in by_name and cell_count is not None:
        if by_name["ticks"]["size"] != 4 + 4 * cell_count:
            raise QufError("E14", "ticks size != 4 + 4 x cell_count (R7)")
    if "edges" in by_name:
        rec = 12 + edge_k
        if by_name["edges"]["size"] % rec:
            raise QufError("E14", "edges size not a multiple of 12 + K")
        derived_e = by_name["edges"]["size"] // rec
        if "edge_count" in kv and kv["edge_count"] != derived_e:
            raise QufError("E14", "edge_count KV != edges records (R8)")
    if "routing" in by_name:
        if by_name["routing"]["size"] % 2:
            raise QufError("E14", "routing size odd (R7)")
        derived_r = by_name["routing"]["size"] // 2
        if "route_count" in kv and kv["route_count"] != derived_r:
            raise QufError("E14", "route_count KV != routing records (R8)")

    # Opt-in payload digest (S12.2): recompute over payloads, table order.
    if "crc32" in kv:
        crc = 0
        for s in sections:
            crc = zlib.crc32(s["bytes"], crc)
        if crc & 0xFFFFFFFF != kv["crc32"]:
            raise QufError("CRC32", "payload crc32 mismatch (S12.2; "
                                    "RTL loader error 12)")

    return {"kv": kv, "kv_list": kv_list, "sections": sections,
            "by_name": by_name, "cell_count": cell_count,
            "edge_k": edge_k, "align": align, "table_end": table_end}


def reconstruct(doc, use_cell_ids=True, ignore_sections=frozenset()):
    """Rebuild the workflow-shaped fabric from a parsed image.

    Cell identity: the SKETCH lanesheet.cell_ids KV binds dials rows
    (fabric addresses, in row order) to workflow ids. Without it (or
    with use_cell_ids=False) cells are named by fabric address -- the
    standard-profile reading; cell NAMES are never in the image (they
    live in the source sheet, referenced by lanesheet.source_sha256).
    """
    by_name = {n: s for n, s in doc["by_name"].items()
               if n not in ignore_sections}
    cell_count = doc["cell_count"]
    ids = list(range(cell_count))
    if use_cell_ids and "lanesheet.cell_ids" in doc["kv"]:
        ids = doc["kv"]["lanesheet.cell_ids"]
        if len(ids) != cell_count:
            raise QufError("E14", "lanesheet.cell_ids length != cell_count")
    dials = by_name["dials"]["bytes"]
    cells = []
    for a in range(cell_count):
        row = struct.unpack_from("<16H", dials, a * 32)
        cells.append({"id": ids[a], "kind": "value",
                      "dials": list(row), "address": a})

    # Edge/routing endpoints are fabric ADDRESSES (u8), not necessarily
    # described cells: the S11 golden vector itself carries an edge to
    # dst 2 and a route to dst 15 in a 2-cell file. A bound address
    # maps to its workflow id; an unbound one stays a raw address.
    def wid(addr):
        return ids[addr] if addr < len(ids) else addr

    k = doc["edge_k"]
    edges = []
    eb = by_name["edges"]["bytes"]
    for i in range(len(eb) // (12 + k)):
        src, dst, mode, slot, base, wh, age = struct.unpack_from(
            "<BBBBHHI", eb, i * (12 + k))
        buckets = list(eb[i * (12 + k) + 12: i * (12 + k) + 12 + k])
        edges.append({"from": wid(src), "to": wid(dst), "mode": mode,
                      "slot": slot, "base": base, "wh": wh, "age": age,
                      "buckets": buckets})

    ticks = by_name["ticks"]["bytes"]
    tpw = struct.unpack_from("<I", ticks, 0)[0]
    phases = [struct.unpack_from("<I", ticks, 4 + 4 * a)[0]
              for a in range(cell_count)]
    rb = by_name["routing"]["bytes"]
    routing = [{"dst": wid(rb[i]), "via": wid(rb[i + 1])}
               for i in range(0, len(rb), 2)]
    state = {"tpw": tpw, "tick_period": doc["kv"].get("tick_period"),
             "phases": phases, "routing": routing,
             "edge.k": doc["edge_k"]}
    return {"cells": cells, "edges": edges, "state": state}


def fabric_hash(rec):
    """Emitter convention: FNV-1a over per-cell canonical serializations
    (type || id || dials || neighbor ids) in ascending id order."""
    cells = sorted(rec["cells"], key=lambda c: c["id"])
    neighbors = {c["id"]: sorted({e["to"] for e in rec["edges"]
                                  if e["from"] == c["id"]}) for c in cells}
    blob, per_cell = bytearray(), {}
    for c in cells:
        s = emit.serialize_cell({"id": c["id"], "kind": "value",
                                 "dials": c["dials"]}, neighbors[c["id"]])
        per_cell[c["id"]] = emit.fnv1a(s)
        blob += s
    return emit.fnv1a(bytes(blob)), per_cell


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    ignore = frozenset(a.split("=", 1)[1] for a in argv[1:]
                       if a.startswith("--ignore-section="))
    if len(args) != 1:
        print(__doc__)
        return 2
    with open(args[0], "rb") as f:
        data = f.read()
    try:
        doc = parse(data)
        rec = reconstruct(doc, ignore_sections=ignore)
    except QufError as e:
        print(f"QUF-REJECT {e}")
        return 1
    fhash, per_cell = fabric_hash(rec)
    out = {"cells": [{"id": c["id"], "kind": c["kind"],
                      "dials": c["dials"]} for c in rec["cells"]],
           "edges": rec["edges"], "state": rec["state"],
           "fabric_hash": f"0x{fhash:016x}",
           "per_cell_hashes": {str(k): f"0x{v:016x}"
                               for k, v in per_cell.items()}}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
