#!/usr/bin/env python3
"""quf_write.py -- QUF writer for the lane-sheet clean subset (SuperInstance).

Downward lane 2: takes a lane-sheet workflow in the lanesheet_emit.py
JSON shape, extracts the CLEAN subset (numeric value cells, edges with
both endpoints in the subset, sheet state -- DOWNWARD.md S1 rows 4 and
10), and emits a real QUF v1 binary image following
SuperInstance/quilt-verilog docs/QUF-SPEC.md wherever the spec pins
bytes: fixed header (S3), header KV (S4), section table (S5), sections
dials/edges/routing/ticks (S6), alignment (S7), extensibility (S8), and
the opt-in payload crc32 KV (S12.2).

Everything the spec does NOT pin is decided in QUF-NOTES.md and flagged
SKETCH where it touches the file: four lanesheet.* KV keys (skipped by
any conformant reader per S8 rule 1) and one `steps` section (skipped
via the table per S8 rule 3). Excluded (non-clean) constructs are never
dropped silently: they are listed, with reasons, in the sidecar
manifest <OUT>.json.

Stdlib only. Usage:
    python3 quf_write.py WORKFLOW.json OUT.quf
"""

import hashlib
import json
import struct
import sys
import zlib

import lanesheet_emit as emit

PRODUCER = "lanesheet-quf 0.1"
LANESHEET_VERSION = "0.1"
EDGE_K = 8
ALIGN = 32
TPW_DEFAULT = None  # no default: the source must carry its tick schedule

# GGUF value-type numbering (QUF-SPEC S4).
T_U8, T_I8, T_U16, T_I16, T_U32, T_I32 = 0, 1, 2, 3, 4, 5
T_F32, T_BOOL, T_STRING, T_ARRAY, T_U64, T_I64, T_F64 = 6, 7, 8, 9, 10, 11, 12


def fail(msg):
    raise SystemExit(f"QUF-REFUSED: {msg}")


# ---------------------------------------------------------------- subsetting

def clean_subset(wf):
    """Extract the fabric-clean subset of a workflow.

    Clean = numeric value cells (DOWNWARD S1 row 4) and edges whose
    endpoints are both clean (row 7's wire is clean only as wiring
    between bound cells). Everything else is excluded WITH a reason.
    Returns (subset_dict, report_dict). The subset keeps the emitter's
    workflow shape so emit.validate() and emit.serialize_cell() apply
    to it unchanged.
    """
    emit.check_no_floats(wf)
    cells = wf.get("cells") or fail("workflow has no cells")
    included, excluded_cells = [], []
    for c in cells:
        bad_text = emit.TEXT_FIELDS & set(c)
        if bad_text:
            excluded_cells.append({
                "id": c.get("id"), "name": c.get("name"),
                "kind": c.get("kind"),
                "reason": f"carries text field(s) {sorted(bad_text)}: no "
                          f"string type in QUF state (DOWNWARD S1 row 5)"})
        elif c.get("kind") != "value":
            excluded_cells.append({
                "id": c.get("id"), "name": c.get("name"),
                "kind": c.get("kind"),
                "reason": f"kind {c.get('kind')!r} is not a numeric value "
                          f"cell: maps with loss or not at all (DOWNWARD "
                          f"S1 rows 2/3/6/9); only its dial/wiring shadow "
                          f"could cross, so it is excluded from the clean "
                          f"image, not silently shadowed"})
        else:
            included.append(c)
    inc_ids = {c["id"] for c in included}
    inc_edges, excluded_edges = [], []
    for e in wf.get("edges", []):
        if e["from"] in inc_ids and e["to"] in inc_ids:
            inc_edges.append(e)
        else:
            excluded_edges.append({
                "from": e.get("from"), "to": e.get("to"),
                "reason": "an endpoint is outside the clean subset"})
    # run events: an inject on an included cell is a clean step; any
    # other event belongs to an excluded construct.
    inc_steps, excluded_steps = [], []
    for ev in wf.get("run", []):
        if "inject" in ev and ev["inject"]["cell"] in inc_ids:
            inc_steps.append(ev)
        elif "inject" in ev:
            excluded_steps.append({"event": ev, "reason":
                                   "inject target outside the clean subset"})
        else:
            excluded_steps.append({"event": ev, "reason":
                                   "not an inject step: port returns are "
                                   "off-fabric answers (DOWNWARD S1b), not "
                                   "fabric state or schedule"})
    subset = {"name": wf["name"], "cells": included, "edges": inc_edges,
              "run": inc_steps, "tick_tpw": wf.get("tick_tpw")}
    report = {"included_cells": [c["id"] for c in included],
              "excluded_cells": excluded_cells,
              "included_edges": len(inc_edges),
              "excluded_edges": excluded_edges,
              "included_steps": len(inc_steps),
              "excluded_run_events": excluded_steps}
    return subset, report


# ---------------------------------------------------------------- KV encoding

def kv_string(name, s):
    b = s.encode("utf-8")
    return (struct.pack("<I", len(name)) + name.encode("utf-8")
            + struct.pack("<I", T_STRING) + struct.pack("<I", len(b)) + b)


def kv_u32(name, v):
    return (struct.pack("<I", len(name)) + name.encode("utf-8")
            + struct.pack("<I", T_U32) + struct.pack("<I", v))


def kv_u64_array(name, vals):
    return (struct.pack("<I", len(name)) + name.encode("utf-8")
            + struct.pack("<I", T_ARRAY) + struct.pack("<I", T_U64)
            + struct.pack("<I", len(vals))
            + b"".join(struct.pack("<Q", v) for v in vals))


# ---------------------------------------------------------------- sections

def assign_slots(edges):
    """Per-src slot indices, in source order (the emitter's LINK order)."""
    nxt, out = {}, []
    for e in edges:
        s = nxt.get(e["from"], 0)
        nxt[e["from"]] = s + 1
        out.append(dict(e, slot=s))
    return out


def build_sections(subset, addresses):
    """Return (ordered [(name, kind, payload)], edge_records).

    addresses: workflow id -> fabric address (rank in ascending id
    order, 0-based; QUF-NOTES decision D1). Standard section payloads
    follow QUF-SPEC S6 byte for byte.
    """
    cells = sorted(subset["cells"], key=lambda c: c["id"])
    edges = assign_slots(subset["edges"])
    # dials (S6.1): one 16xu16 row per cell, row = fabric address order.
    dials = b"".join(struct.pack("<16H", *c["dials"]) for c in cells)
    # edges (S6.2): 12 + K bytes per record. Bind-time image: mode 0
    # (ladder), wh/age/buckets zero -- the source carries no walk state
    # (QUF-NOTES D3).
    recs = []
    for e in sorted(edges, key=lambda e: (addresses[e["from"]], e["slot"])):
        recs.append(struct.pack("<BBBBHHI", addresses[e["from"]],
                                addresses[e["to"]], 0, e["slot"],
                                e["base"], 0, 0) + bytes(EDGE_K))
    edges_b = b"".join(recs)
    # routing (S6.3): one identity route per cell (v1 single ring:
    # via == dst).
    routing = b"".join(struct.pack("<BB", addresses[c["id"]],
                                   addresses[c["id"]]) for c in cells)
    # ticks (S6.4): tpw + one u32 phase per cell; phases 0 (v1 ignores
    # them; the source carries none -- QUF-NOTES D4).
    ticks = struct.pack("<I", subset["tick_tpw"]) + bytes(4 * len(cells))
    # steps (SKETCH, DOWNWARD S2): per step u32 index, u32 first_tick,
    # u32 op_count. An inject step is EFFECT+TICK = 2 ops and its tick
    # window spans 1 tick (QUF-NOTES D6).
    steps = b""
    for i, ev in enumerate(subset["run"]):
        steps += struct.pack("<III", i, i, 2)
    sections = [("dials", 0, dials), ("edges", 0, edges_b),
                ("routing", 0, routing), ("ticks", 0, ticks)]
    if subset["run"]:
        sections.append(("steps", 0, steps))
    return sections, edges


def align_up(n, a=ALIGN):
    return (n + a - 1) // a * a


def build_image(subset, source_name, source_sha256, extra_sections=()):
    """Assemble the QUF image. Returns (bytes, layout_dict)."""
    emit.validate(subset)  # emitter's own gate: ids, dials, bases, kinds
    if subset.get("tick_tpw") is None:
        fail("source carries no tick_tpw: a QUF image must carry its "
             "tick schedule (QUF-SPEC S6.4); refusing to invent one")
    cells = sorted(subset["cells"], key=lambda c: c["id"])
    if len(cells) > 256:
        fail(f"{len(cells)} clean cells: QUF fabric addressing is u8 "
             f"(S6.2/S6.3); refusing")
    addresses = {c["id"]: i for i, c in enumerate(cells)}
    sections, _ = build_sections(subset, addresses)
    sections = sections + [(n, k, p) for (n, k, p) in extra_sections]

    # crc32 (S12.2): over payload bytes only, in table order.
    crc = 0
    for _, _, payload in sections:
        crc = zlib.crc32(payload, crc)
    crc &= 0xFFFFFFFF

    # Header KV: standard keys in the S4 writer order, then the S12.2
    # crc32 KV (position unpinned by the spec -- QUF-NOTES D7), then
    # the SKETCH lanesheet.* keys (S8 rule 1: skipped by readers that
    # do not know them).
    kv = b"".join([
        kv_string("quf.version", PRODUCER),
        kv_u32("cell_count", len(cells)),
        kv_u32("edge_count", len(subset["edges"])),
        kv_u32("route_count", len(cells)),
        kv_u32("edge.k", EDGE_K),
        kv_u32("tick_period", 1 << subset["tick_tpw"]),
        kv_string("quant.dials", "Q1.15"),
        kv_string("quant.edges", "Q1.15"),
        kv_string("quant.routing", "u8"),
        kv_u32("align", ALIGN),
        kv_u32("crc32", crc),
        kv_string("lanesheet.version", LANESHEET_VERSION),
        kv_string("lanesheet.name", source_name),
        kv_string("lanesheet.source_sha256", source_sha256),
        kv_u64_array("lanesheet.cell_ids", [c["id"] for c in cells]),
    ])
    kv_count = 15

    table_len = 4 + sum(4 + len(n) + 4 + 8 + 8 for n, _, _ in sections)
    front_end = 16 + len(kv) + table_len
    offsets, pos = [], align_up(front_end)
    for _, _, payload in sections:
        offsets.append(pos)
        pos = align_up(pos + len(payload))
        if len(payload) == 0:
            # S5: table entries are STRICTLY ascending by offset; an
            # empty section still advances the cursor one quantum so
            # the next section cannot share its offset.
            pos += ALIGN

    table = struct.pack("<I", len(sections))
    for (name, kind, payload), off in zip(sections, offsets):
        table += (struct.pack("<I", len(name)) + name.encode("utf-8")
                  + struct.pack("<I", kind) + struct.pack("<Q", off)
                  + struct.pack("<Q", len(payload)))

    img = bytearray(pos)  # zero-filled: all padding is zero by construction
    img[0:16] = (b"QUF\x00" + struct.pack("<III", 1, 1, kv_count))
    img[16:16 + len(kv)] = kv
    img[16 + len(kv):16 + len(kv) + len(table)] = table
    for (_, _, payload), off in zip(sections, offsets):
        img[off:off + len(payload)] = payload

    layout = {"kv_count": kv_count, "front_end": front_end,
              "file_size": len(img), "crc32": crc,
              "sections": [{"name": n, "kind": k, "offset": o,
                            "size": len(p)}
                           for (n, k, p), o in zip(sections, offsets)]}
    return bytes(img), layout


def fabric_hash(subset):
    """The emitter's convention: FNV-1a over per-cell canonical
    serializations concatenated in ascending id order."""
    cells = sorted(subset["cells"], key=lambda c: c["id"])
    neighbors = {c["id"]: sorted({e["to"] for e in subset["edges"]
                                  if e["from"] == c["id"]}) for c in cells}
    blob, per_cell = bytearray(), {}
    for c in cells:
        s = emit.serialize_cell(c, neighbors[c["id"]])
        per_cell[c["id"]] = emit.fnv1a(s)
        blob += s
    return emit.fnv1a(bytes(blob)), per_cell


def write_workflow(wf_path, out_path, extra_sections=()):
    with open(wf_path, "rb") as f:
        raw = f.read()
    wf = json.loads(raw.decode("utf-8"))
    source_sha256 = hashlib.sha256(raw).hexdigest()
    subset, report = clean_subset(wf)
    img, layout = build_image(subset, wf["name"], source_sha256,
                              extra_sections)
    fhash, per_cell = fabric_hash(subset)
    with open(out_path, "wb") as f:
        f.write(img)
    manifest = {
        "producer": PRODUCER,
        "image": out_path,
        "source": {"file": wf_path, "name": wf["name"],
                   "sha256": source_sha256},
        "subset": report,
        "sketch_elements": {
            "kv_keys": ["lanesheet.version", "lanesheet.name",
                        "lanesheet.source_sha256", "lanesheet.cell_ids"],
            "sections": [s["name"] for s in layout["sections"]
                         if s["name"] == "steps"],
            "rule": "QUF-SPEC S8 rules 1/3/6: unknown KV keys and "
                    "section names are skipped; neither bumps version"},
        "spec_optional_elements": {"crc32_kv": "QUF-SPEC S12.2"},
        "layout": layout,
        "fabric_hash": f"0x{fhash:016x}",
        "per_cell_hashes": {str(k): f"0x{v:016x}"
                            for k, v in per_cell.items()},
        "notes": "decisions and underdetermined bytes: QUF-NOTES.md",
    }
    with open(out_path + ".json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return manifest


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    m = write_workflow(argv[1], argv[2])
    lay = m["layout"]
    print(f"wrote {argv[2]} ({lay['file_size']} bytes, "
          f"kv_count {lay['kv_count']}, "
          f"sections " + ", ".join(
              f"{s['name']}@{s['offset']}+{s['size']}"
              for s in lay["sections"]) + ")")
    print(f"fabric hash {m['fabric_hash']}  crc32 0x{lay['crc32']:08x}")
    sub = m["subset"]
    if sub["excluded_cells"] or sub["excluded_edges"]:
        print(f"subset: kept cells {sub['included_cells']}, "
              f"excluded {len(sub['excluded_cells'])} cell(s) and "
              f"{len(sub['excluded_edges'])} edge(s) -- see manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
