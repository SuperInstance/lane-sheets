#!/usr/bin/env python3
"""run_quf_check.py -- QUF downward-lane-2 conformance (SuperInstance).

Write -> read -> hash-compare, plus byte-level assertions on every
field QUF-SPEC pins for the worked example, S8 skip behaviour, and S5a
negative mutants. Prints PASS/FAIL per assertion and a summary; exit
code is 0 only if every assertion passes.

Run:  python3 run_quf_check.py
"""

import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lanesheet_emit as emit
import quf_read
import quf_write

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'} {name}"
          + (f" -- {detail}" if detail and not cond else ""))


def expect_reject(name, data, code):
    try:
        quf_read.parse(data)
        check(name, False, "reader accepted a mutant file")
    except quf_read.QufError as e:
        check(name, e.code == code, f"got {e.code}, want {code}: {e}")


def source_fabric(wf_path):
    wf = json.loads(Path(wf_path).read_text(encoding="utf-8"))
    subset, report = quf_write.clean_subset(wf)
    return wf, subset, report


def main():
    # --- A. the contract machinery itself (the shelf's anchor) ----------
    cell = {"id": 1, "kind": "value", "name": "contract",
            "dials": list(range(1, 17))}
    h = emit.fnv1a(emit.serialize_cell(cell, [2, 3, 4]))
    check("A1 charter contract cell hash", h == 0xE435D91D6D92A1D8,
          f"0x{h:016x}")
    r = subprocess.run([sys.executable, "lanesheet_emit.py", "--selftest"],
                       cwd=HERE, capture_output=True, text=True)
    check("A2 emitter selftest (CLI)", r.returncode == 0
          and "PASS" in r.stdout, r.stdout + r.stderr)

    # --- B. write triage-clean; byte-level assertions -------------------
    clean = HERE / "triage-clean.json"
    img_path = HERE / "triage-clean.quf"
    manifest = quf_write.write_workflow(str(clean), str(img_path))
    data = img_path.read_bytes()

    check("B1 magic", data[0:4] == b"QUF\x00", data[0:4])
    ver, end, kvc = struct.unpack_from("<III", data, 4)
    check("B2 header version/endian/kv_count", (ver, end, kvc) == (1, 1, 15),
          f"{ver},{end},{kvc}")
    doc = quf_read.parse(data)
    secs = {s["name"]: s for s in doc["sections"]}
    check("B3 section sizes (SPEC S6 formulas; DOWNWARD S2 example)",
          (secs["dials"]["size"], secs["edges"]["size"],
           secs["routing"]["size"], secs["ticks"]["size"],
           secs["steps"]["size"]) == (96, 40, 6, 16, 12),
          str({k: v["size"] for k, v in secs.items()}))
    offs = [secs[n]["offset"] for n in
            ("dials", "edges", "routing", "ticks", "steps")]
    check("B4 section offsets (pinned layout arithmetic)",
          offs == [672, 768, 832, 864, 896], str(offs))
    check("B5 offsets aligned / ascending / file size",
          all(o % 32 == 0 for o in offs) and offs == sorted(offs)
          and len(data) == 928 and len(data) % 32 == 0,
          f"len {len(data)}")
    kv = doc["kv"]
    check("B6 count KVs are honest assertions",
          (kv["cell_count"], kv["edge_count"], kv["route_count"],
           kv["edge.k"], kv["tick_period"], kv["align"])
          == (3, 2, 3, 8, 64, 32), str({k: kv[k] for k in
                                        ("cell_count", "edge_count",
                                         "route_count", "edge.k",
                                         "tick_period", "align")}))
    src_sha = hashlib.sha256(clean.read_bytes()).hexdigest()
    check("B7 lanesheet.source_sha256 == sha256(source file)",
          kv["lanesheet.source_sha256"] == src_sha)
    check("B8 lanesheet.cell_ids binds rows to workflow ids",
          kv["lanesheet.cell_ids"] == [1, 2, 3],
          str(kv["lanesheet.cell_ids"]))
    d = secs["dials"]["offset"]
    w = lambda off: struct.unpack_from("<H", data, off)[0]
    check("B9 dial words land where S6.1 puts them",
          w(d + 5 * 2) == 12000 and w(d + 32 + 5 * 2) == 8000
          and w(d + 64 + 5 * 2) == 0,
          f"{w(d+10)},{w(d+42)},{w(d+74)}")
    e = secs["edges"]["offset"]
    rec0 = struct.unpack_from("<BBBBHHI", data, e)
    rec1 = struct.unpack_from("<BBBBHHI", data, e + 20)
    check("B10 edge records (S6.2: src,dst,mode,slot,base,wh,age)",
          rec0 == (0, 1, 0, 0, 16384, 0, 0)
          and rec1 == (1, 2, 0, 0, 16384, 0, 0)
          and data[e + 12:e + 20] == bytes(8),
          f"{rec0} {rec1}")
    r_off = secs["routing"]["offset"]
    check("B11 routing bytes (identity routes, via == dst)",
          data[r_off:r_off + 6] == bytes([0, 0, 1, 1, 2, 2]),
          data[r_off:r_off + 6].hex())
    t_off = secs["ticks"]["offset"]
    check("B12 ticks (tpw 6, phases zero)",
          struct.unpack_from("<IIII", data, t_off) == (6, 0, 0, 0))
    s_off = secs["steps"]["offset"]
    check("B13 steps section (SKETCH: step 0, first_tick 0, 2 ops)",
          struct.unpack_from("<III", data, s_off) == (0, 0, 2))
    crc = 0
    for s in doc["sections"]:
        crc = zlib.crc32(s["bytes"], crc)
    check("B14 crc32 KV == payload digest in table order (S12.2)",
          crc & 0xFFFFFFFF == kv["crc32"],
          f"0x{crc & 0xFFFFFFFF:08x} vs 0x{kv['crc32']:08x}")
    check("B15 all padding zero (R11)",
          not any(data[doc["table_end"]:offs[0]])
          and not any(data[808:832]) and not any(data[838:864])
          and not any(data[880:896]) and not any(data[908:928]))

    # --- C. round trip: read back, compare, hash-agree -------------------
    wf, subset, _ = source_fabric(clean)
    src_hash, src_cells = quf_write.fabric_hash(subset)
    rec = quf_read.reconstruct(doc)
    rec_hash, rec_cells = quf_read.fabric_hash(rec)
    check("C1 reconstructed cells == source subset (ids, dials)",
          [(c["id"], c["dials"]) for c in rec["cells"]]
          == [(c["id"], c["dials"]) for c in
              sorted(subset["cells"], key=lambda c: c["id"])])
    check("C2 reconstructed edges == source edges (endpoints, base, slot)",
          [(x["from"], x["to"], x["base"], x["slot"]) for x in rec["edges"]]
          == [(1, 2, 16384, 0), (2, 3, 16384, 0)],
          str(rec["edges"]))
    check("C3 fabric hash agreement (the shelf's way)",
          rec_hash == src_hash
          and manifest["fabric_hash"] == f"0x{src_hash:016x}",
          f"src 0x{src_hash:016x} rec 0x{rec_hash:016x}")
    check("C4 per-cell hashes agree",
          rec_cells == src_cells,
          f"{rec_cells} vs {src_cells}")
    check("C5 state round-trips (tpw, phases, routing)",
          rec["state"]["tpw"] == 6 and rec["state"]["phases"] == [0, 0, 0]
          and [(x["dst"], x["via"]) for x in rec["state"]["routing"]]
          == [(1, 1), (2, 2), (3, 3)])

    # --- D. triage-mini: the clean subset of a lossy workflow ------------
    mini = HERE / "triage-mini.json"
    mini_img = HERE / "triage-mini.quf"
    mman = quf_write.write_workflow(str(mini), str(mini_img))
    sub = mman["subset"]
    check("D1 subsetting keeps only the value cell",
          sub["included_cells"] == [1]
          and [c["id"] for c in sub["excluded_cells"]] == [2, 3],
          str(sub["included_cells"]))
    check("D2 exclusions are named with reasons, nothing silent",
          all(c["reason"] for c in sub["excluded_cells"])
          and len(sub["excluded_edges"]) == 2
          and len(sub["excluded_run_events"]) == 2)
    mdoc = quf_read.parse(mini_img.read_bytes())
    msec = {s["name"]: s for s in mdoc["sections"]}
    check("D3 subset image shape (1 cell, 0 edges)",
          (mdoc["kv"]["cell_count"], mdoc["kv"]["edge_count"],
           msec["dials"]["size"], msec["edges"]["size"],
           msec["ticks"]["size"]) == (1, 0, 32, 0, 8),
          str({k: v["size"] for k, v in msec.items()}))
    _, msubset, _ = source_fabric(mini)
    msrc, _ = quf_write.fabric_hash(msubset)
    mrec_hash, _ = quf_read.fabric_hash(quf_read.reconstruct(mdoc))
    check("D4 subset fabric hash agreement", mrec_hash == msrc,
          f"0x{msrc:016x} vs 0x{mrec_hash:016x}")
    moffs = [s["offset"] for s in mdoc["sections"]]
    check("D5 subset table strictly ascending despite the empty edges "
          "section (S5)", all(b > a for a, b in zip(moffs, moffs[1:])),
          str(moffs))

    # --- E. S8 skip behaviour ---------------------------------------------
    rec_skip = quf_read.reconstruct(doc, ignore_sections={"steps"})
    skip_hash, _ = quf_read.fabric_hash(rec_skip)
    check("E1 unknown-section skip: steps ignored, state identical",
          skip_hash == src_hash)
    _, subset2, _ = source_fabric(clean)
    img2, _ = quf_write.build_image(
        subset2, "triage-clean", src_sha,
        extra_sections=[("zzlab", 0, b"LAB!")])
    try:
        doc2 = quf_read.parse(img2)
        h2, _ = quf_read.fabric_hash(quf_read.reconstruct(doc2))
        check("E2 foreign section present, skipped, hash unchanged",
              h2 == src_hash and "zzlab" in doc2["by_name"])
    except quf_read.QufError as ex:
        check("E2 foreign section present, skipped, hash unchanged",
              False, str(ex))
    rec_addr = quf_read.reconstruct(doc, use_cell_ids=False)
    check("E3 no-cell_ids reading: address-space fabric is the same fabric",
          [c["id"] for c in rec_addr["cells"]] == [0, 1, 2]
          and [c["dials"] for c in rec_addr["cells"]]
          == [c["dials"] for c in rec["cells"]]
          and [(x["from"], x["to"]) for x in rec_addr["edges"]]
          == [(0, 1), (1, 2)])

    # --- F. S5a negative mutants -------------------------------------------
    mut = bytearray(data)
    mut[665] ^= 0xFF  # inside the front padding run (table_end 659..671)
    expect_reject("F1 nonzero padding byte -> E16", bytes(mut), "E16")
    mut = bytearray(data)
    i = data.find(b"cell_count")
    struct.pack_into("<I", mut, i + len(b"cell_count") + 4, 4)
    expect_reject("F2 cell_count lie -> E14", bytes(mut), "E14")
    expect_reject("F3 truncated payload -> E10", data[:-32], "E10")
    expect_reject("F4 unpadded EOF -> E15", data[:-1], "E15")
    mut = bytearray(data)
    mut[0] = 0x51 ^ 0xFF
    expect_reject("F5 bad magic -> E7", bytes(mut), "E7")
    mut = bytearray(data)
    mut[secs["dials"]["offset"] + 10] ^= 0xFF  # THRESH low byte, cell 1
    expect_reject("F6 payload flip caught by crc32 gate (S12.2)",
                  bytes(mut), "CRC32")
    # Same flip with the crc32 KV honestly recomputed over the mutated
    # payloads: the file is now internally consistent, so it parses --
    # and agreement (hash vs source) is what catches it.
    crc = 0
    for s in doc["sections"]:
        payload = bytes(mut[s["offset"]:s["offset"] + s["size"]])
        crc = zlib.crc32(payload, crc)
    j = data.find(b"crc32")
    struct.pack_into("<I", mut, j + len(b"crc32") + 4, crc & 0xFFFFFFFF)
    try:
        d7 = quf_read.parse(bytes(mut))
        h7, _ = quf_read.fabric_hash(quf_read.reconstruct(d7))
        check("F7 crc-consistent payload flip parses but hash disagrees "
              "(agreement is the check, not the parse)", h7 != src_hash)
    except quf_read.QufError as ex:
        check("F7 crc-consistent payload flip", False,
              f"unexpected reject {ex}")

    # --- G. the CLIs stand alone -------------------------------------------
    r = subprocess.run([sys.executable, "quf_write.py",
                        "triage-clean.json", "/tmp/tc.quf"],
                       cwd=HERE, capture_output=True, text=True)
    check("G1 quf_write.py CLI", r.returncode == 0
          and "triage-clean.quf" in r.stdout or "tc.quf" in r.stdout,
          r.stdout + r.stderr)
    r = subprocess.run([sys.executable, "quf_read.py", "triage-clean.quf"],
                       cwd=HERE, capture_output=True, text=True)
    ok = r.returncode == 0 and f"0x{src_hash:016x}" in r.stdout
    check("G2 quf_read.py CLI prints the agreeing hash", ok,
          r.stdout[-200:] + r.stderr)
    bad = bytearray(data)
    bad[665] ^= 0xFF  # the F1 padding mutant: known-rejectable
    Path("/tmp/tc-bad.quf").write_bytes(bytes(bad))
    r = subprocess.run([sys.executable, "quf_read.py", "/tmp/tc-bad.quf"],
                       cwd=HERE, capture_output=True, text=True)
    check("G3 quf_read.py CLI rejects a mutant with its code",
          r.returncode == 1 and "QUF-REJECT E16" in r.stdout,
          r.stdout + r.stderr)

    # --- H. the shelf's own golden vector through this reader --------------
    ghex = (HERE / "golden-vector.hex").read_text().strip()
    gdata = bytes.fromhex(ghex)
    check("H1 QUF-SPEC S12.2 hex == S11 golden vector (sha256)",
          hashlib.sha256(gdata).hexdigest()
          == "5b2a236ba5e38bca9ad96783c4252a12f36517f98a9164a249f0db115f2"
             "21392" and len(gdata) == 576,
          hashlib.sha256(gdata).hexdigest())
    try:
        gdoc = quf_read.parse(gdata)
        grec = quf_read.reconstruct(gdoc)
        gsecs = {s["name"]: s for s in gdoc["sections"]}
        check("H2 golden parses: layout 384/448/512/544, sizes 64/60/6/12",
              [gsecs[n]["offset"] for n in
               ("dials", "edges", "routing", "ticks")]
              == [384, 448, 512, 544]
              and [gsecs[n]["size"] for n in
                   ("dials", "edges", "routing", "ticks")]
              == [64, 60, 6, 12])
        check("H3 golden content: 2 cells, 3 edges as printed in S11",
              gdoc["cell_count"] == 2
              and [(x["from"], x["to"], x["mode"], x["slot"], x["base"],
                    x["wh"], x["age"]) for x in grec["edges"]]
              == [(0, 1, 0, 0, 0x1234, 0, 0),
                  (0, 2, 1, 1, 64, 7, 1000),
                  (1, 0, 0, 0, 0x0200, 3, 5)],
              str(grec["edges"]))
        check("H4 golden state: tpw 6, phases [0, 3], routing incl. dst 15",
              grec["state"]["tpw"] == 6
              and grec["state"]["phases"] == [0, 3]
              and [(x["dst"], x["via"]) for x in grec["state"]["routing"]]
              == [(1, 1), (2, 2), (15, 15)])
        check("H5 golden dials row 0 head words (S11 lists u16 values)",
              grec["cells"][0]["dials"][:4] == [0x0800, 0x0080, 0x0006,
                                                0x000C],
              str(grec["cells"][0]["dials"][:4]))
    except quf_read.QufError as ex:
        check("H2-H5 golden vector parses under this reader", False, str(ex))

    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print(f"SUMMARY: {passed}/{len(RESULTS)} PASS")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
