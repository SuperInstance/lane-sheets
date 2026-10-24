"""fold.py -- a minimal Python port of the git.pp fold (derive semantics).

MINIMAL PORT, LABELLED AS SUCH. This is not the upstream engine and
claims no conformance with the git.pp corpus. It ports, as faithfully
as the spike needs, the semantics of `deriveLegacy` in the vendored
engine:

    source : patchwork-quilt/git.pp-action, lib/fold.ts
             (byte-identical vendor of patchwork-quilt/git.pp-ng
              src/fold.ts @ e296feabc3008a79ea25e7b73f5534f9454a579c)
    spec   : git.pp-ng DESIGN.md -- the fold is the specification;
             the production bitset engine (derive) is held
             byte-identical to deriveLegacy upstream, so porting the
             legacy set-based version ports the semantics.

What is ported (the whole of derive, nothing else):

  * canonical record index: records sorted by (effective id, canonical
    content), so input permutation and duplicate-id resolution cannot
    depend on arrival order. The canonical form is Python's own
    json.dumps(sort_keys=True, ensure_ascii=True) -- fold.ts's
    pyCanonical exists precisely to reproduce that byte-for-byte.
  * missing/non-string ids are indexed under "missing-id:" + SHA-256
    of the canonical content minus id (issue #38 ruling) and held
    orphan-class: never referenced, never applied.
  * orphans: a record with an absent parent is an orphan, orphanhood
    propagates to descendants, and records in (or blocked behind) a
    parent cycle are orphans.
  * canonical order: Kahn's algorithm, smallest ready id first.
  * per-key winner, among applied records only:
      1. CLASS PRIORITY IS ABSOLUTE: override > task > witness;
         kinds outside those three rank as witnesses.
      2. Within the highest class present, a candidate that is a
         (transitive) ancestor of another candidate is dominated;
         the survivors are the most-derived.
      3. Tie-break, the cleanest chain wins: most intent (task +
         override) ancestors, then fewest witness ancestors, then
         the smallest id (code-point order).
  * a conflict is reported for a key when its applied candidates hold
    >= 2 distinct values (Python equality: 1 == 1.0 == True share one
    numeric bucket; "1" != 1; None only == None).

What is NOT ported: checkpoints, delta derivation, witness freshness
-- the spike needs derive() and nothing else.

Stdlib only. SuperInstance.
"""

import hashlib
import heapq
import json

CLASS_RANK = {"override": 0, "task": 1, "witness": 2}
WITNESS_RANK = 2
FALLBACK_RANK = 2


def py_canonical(value):
    """Python json.dumps(sort_keys=True) -- the form fold.ts reproduces."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _parents_of(rec):
    ps = rec.get("parents")
    if not isinstance(ps, list):
        return []
    return [str(p) for p in ps]


def _effects_of(rec):
    eff = rec.get("effects")
    if isinstance(eff, dict):
        return dict(eff)
    return {}


def _rank_of(rec):
    kind = rec.get("kind")
    if isinstance(kind, str) and kind in CLASS_RANK:
        return CLASS_RANK[kind]
    return FALLBACK_RANK


def _value_key(v):
    """Grouping key reproducing Python == for JSON values (fold.ts pyValueKey)."""
    if isinstance(v, bool):
        return "n:" + ("1" if v else "0")
    if isinstance(v, (int, float)):
        # JS String(number) after JSON.parse: integral values in the
        # plain band spell as integers; everything else shortest repr.
        f = float(v)
        if f == 0:
            return "n:0"
        if f.is_integer() and abs(f) < 1e21:
            return "n:" + str(int(f))
        return "n:" + repr(f)
    if isinstance(v, str):
        return "s:" + v
    if v is None:
        return "z:"
    return "c:" + py_canonical(v)


def _missing_id_placeholder(rec):
    normalized = {
        "parents": sorted(_parents_of(rec)),
        "kind": rec.get("kind"),
        "effects": _effects_of(rec),
        "reason": rec.get("reason"),
    }
    digest = hashlib.sha256(py_canonical(normalized).encode("utf-8")).hexdigest()
    return "missing-id:" + digest


def _effective_id(rec):
    rid = rec.get("id")
    return rid if isinstance(rid, str) else _missing_id_placeholder(rec)


def _index_key(rec):
    # The duplicate-id ordering key: canonical content with any digest
    # field removed (a digest is a claim ABOUT a record, never content).
    if "digest" not in rec:
        return py_canonical(rec)
    rest = {k: v for k, v in rec.items() if k != "digest"}
    return py_canonical(rest)


def index_records(records):
    ordered = sorted(records, key=lambda r: (_effective_id(r), _index_key(r)))
    idx = {}
    for r in ordered:
        idx[_effective_id(r)] = r
    return idx


def _cycle_affected(nodes, parents):
    """Nodes that cannot be topologically ordered within `nodes`."""
    indeg = {r: 0 for r in nodes}
    children = {r: [] for r in nodes}
    for r in nodes:
        for p in parents[r]:
            if p in indeg:
                indeg[r] += 1
                children[p].append(r)
    heap = [r for r in nodes if indeg[r] == 0]
    heapq.heapify(heap)
    done = set()
    while heap:
        n = heapq.heappop(heap)
        done.add(n)
        for c in children[n]:
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(heap, c)
    return set(nodes) - done


def _topological(nodes, parents):
    """Kahn's algorithm, always taking the smallest ready id."""
    indeg = {r: len(parents[r]) for r in nodes}
    children = {r: [] for r in nodes}
    for r in nodes:
        for p in parents[r]:
            if p in children:
                children[p].append(r)
    heap = [r for r in nodes if indeg[r] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        n = heapq.heappop(heap)
        order.append(n)
        for c in children[n]:
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(heap, c)
    return order


def derive(records):
    """The fold. Returns {"state", "order", "conflicts", "orphans"}.

    Mirrors fold.ts deriveLegacy step for step. Arrival order is never
    an input: the canonical index decides everything downstream.
    """
    idx = index_records(list(records))
    ids = set(idx)
    parents = {rid: _parents_of(idx[rid]) for rid in ids}

    children = {rid: [] for rid in ids}
    for rid, ps in parents.items():
        for p in ps:
            if p in children:
                children[p].append(rid)

    # Orphans: missing-id placeholders by construction, records with an
    # absent parent, and everything descending from either.
    orphan = set()
    work = []
    for rid in ids:
        if not isinstance(idx[rid].get("id"), str) or any(
            p not in ids for p in parents[rid]
        ):
            work.append(rid)
    for rid in work:
        orphan.add(rid)
    head = 0
    while head < len(work):
        for c in children[work[head]]:
            if c not in orphan:
                orphan.add(c)
                work.append(c)
        head += 1
    non_orphan = ids - orphan
    orphan |= _cycle_affected(non_orphan, parents)

    applied = sorted(rid for rid in ids if rid not in orphan)
    applied_set = set(applied)
    order = _topological(applied_set, parents)

    # Full applied-ancestor set of every applied record, in topo order.
    anc = {}
    for rid in order:
        a = set()
        for p in parents[rid]:
            if p in applied_set:
                a.add(p)
                a |= anc[p]
        anc[rid] = a

    setters = {}
    for rid in applied:
        for k in _effects_of(idx[rid]):
            setters.setdefault(k, set()).add(rid)

    state = {}
    conflicts = []
    for k in sorted(setters):
        cands = sorted(setters[k])
        best = min(_rank_of(idx[c]) for c in cands)
        pool = {c for c in cands if _rank_of(idx[c]) == best}
        dominated = set()
        for d in pool:
            for a in anc[d]:
                if a in pool:
                    dominated.add(a)
        maximal = sorted(pool - dominated)
        if len(maximal) == 1:
            winner = maximal[0]
        else:
            def cleanliness(c):
                intent = sum(
                    1 for a in anc[c] if _rank_of(idx[a]) < WITNESS_RANK
                )
                wit = sum(1 for a in anc[c] if _rank_of(idx[a]) == WITNESS_RANK)
                return (-intent, wit, c)

            winner = sorted(maximal, key=cleanliness)[0]
        state[k] = _effects_of(idx[winner])[k]
        distinct = {_value_key(_effects_of(idx[c])[k]) for c in cands}
        if len(distinct) >= 2:
            conflicts.append(
                {
                    "key": k,
                    "winner": winner,
                    "losers": sorted(c for c in cands if c != winner),
                }
            )

    return {
        "state": state,
        "order": order,
        "conflicts": conflicts,
        "orphans": sorted(orphan),
    }
