"""Exhaustive acceptance tests.

The oracle below is an *independent* reimplementation of the specification
written directly against the raw JSON payload (plain dicts), enumerating all
2^n row subsets by brute force.  The production pipeline is accepted only
when its answer matches the oracle on random small tables and on a battery
of handcrafted conflict scenarios.

Run (from the project root):
    python -I tests/test_exhaustive.py
"""

import os
import random
import sys
from itertools import combinations, product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repairjson.pipeline import run  # noqa: E402


# ---------------------------------------------------------------------------
# Independent oracle, operating only on the raw payload
# ---------------------------------------------------------------------------

def _oracle_consistent(kept, rows, deps):
    for i, j in combinations(kept, 2):
        vi, vj = rows[i]["values"], rows[j]["values"]
        for dep in deps:
            # null == null is equality, so plain Python == is exactly right
            lhs_eq = all(vi[c] == vj[c] for c in dep["lhs"])
            if lhs_eq:
                rhs_eq = all(vi[c] == vj[c] for c in dep["rhs"])
                if not rhs_eq:
                    return False
    return True


def _oracle_eval_query(payload, kept):
    q = payload["query"]
    pos = {a: i for i, a in enumerate(q["aliases"])}

    def parse(ref):
        alias, col = ref.split(".")
        return pos[alias], col

    conds = [(parse(x), parse(y)) for x, y in q["conditions"]]
    projs = [parse(r) for r in q["projections"]]

    out = set()
    for binding in product(kept, repeat=len(q["aliases"])):
        witness = True
        for (pa, ca), (pb, cb) in conds:
            va = binding[pa]["values"][ca]
            vb = binding[pb]["values"][cb]
            if va is None or vb is None or va != vb:
                witness = False
                break
        if witness:
            out.add(tuple(binding[pa]["values"][c] for pa, c in projs))
    return out


def _sort_key(tuple_):
    key = []
    for v in tuple_:
        key.append((1, b"") if v is None else (0, v.encode("utf-8")))
    return tuple(key)


def oracle(payload):
    rows, deps = payload["rows"], payload["dependencies"]
    n = len(rows)

    best_weight = 0
    optimal = []
    for mask in range(1 << n):
        kept = [i for i in range(n) if (mask >> i) & 1]
        if _oracle_consistent(kept, rows, deps):
            w = sum(rows[i]["weight"] for i in kept)
            if w > best_weight:
                best_weight, optimal = w, [kept]
            elif w == best_weight:
                optimal.append(kept)

    counts = {}
    for kept in optimal:
        for tuple_ in _oracle_eval_query(payload, [rows[i] for i in kept]):
            counts[tuple_] = counts.get(tuple_, 0) + 1

    return {
        "optimal_weight": str(best_weight),
        "optimal_repair_count": str(len(optimal)),
        "tuples": [
            {
                "tuple": list(t),
                "optimal_repair_count": str(counts[t]),
                "in_all_optimal_repairs": counts[t] == len(optimal),
            }
            for t in sorted(counts, key=_sort_key)
        ],
    }


# ---------------------------------------------------------------------------
# random payload generation
# ---------------------------------------------------------------------------

def random_payload(rng):
    n = rng.randint(0, 6)
    cols = [f"c{k}" for k in range(rng.randint(1, 3))]
    pool = ["a", "b", "c", None, "é", "中"]
    rows = []
    for i in range(n):
        rows.append(
            {
                "id": f"r{i}",
                "weight": rng.randint(1, 5),
                "values": {c: rng.choice(pool) for c in cols},
            }
        )

    deps = []
    for _ in range(rng.randint(0, 2)):
        lhs = rng.sample(cols, rng.randint(1, len(cols)))
        rhs = rng.sample(cols, rng.randint(1, len(cols)))
        deps.append({"lhs": lhs, "rhs": rhs})

    aliases = [f"t{k}" for k in range(rng.randint(1, 3))]
    refs = [f"{a}.{c}" for a in aliases for c in cols]
    conditions = []
    for _ in range(rng.randint(0, 2)):
        # the two references may be identical (t.K = t.K acts as a
        # non-null filter), so sampling with replacement is allowed
        if len(refs) >= 2 and rng.random() < 0.8:
            x, y = rng.sample(refs, 2)
        else:
            x, y = rng.choice(refs), rng.choice(refs)
        conditions.append([x, y])
    projections = rng.sample(refs, rng.randint(1, min(3, len(refs))))

    return {
        "columns": cols,
        "rows": rows,
        "dependencies": deps,
        "query": {
            "aliases": aliases,
            "conditions": conditions,
            "projections": projections,
        },
    }


# ---------------------------------------------------------------------------
# handcrafted scenarios
# ---------------------------------------------------------------------------

def test_equal_weight_conflict_key_is_certain():
    # Two equal-weight conflicting rows project the same key K=x.  The key
    # remains a certain answer even though neither individual row is certain.
    payload = {
        "columns": ["K", "V"],
        "rows": [
            {"id": "r1", "weight": 10, "values": {"K": "x", "V": "a"}},
            {"id": "r2", "weight": 10, "values": {"K": "x", "V": "b"}},
            {"id": "r3", "weight": 5, "values": {"K": "y", "V": "c"}},
        ],
        "dependencies": [{"lhs": ["K"], "rhs": ["V"]}],
        "query": {
            "aliases": ["t"],
            "conditions": [],
            "projections": ["t.K"],
        },
    }
    out = run(payload)
    assert out["optimal_weight"] == "15"
    assert out["optimal_repair_count"] == "2"
    by_tuple = {tuple(t["tuple"]): t for t in out["tuples"]}
    # x appears in BOTH optimal repairs: certain, despite no certain row
    assert by_tuple[("x",)]["optimal_repair_count"] == "2"
    assert by_tuple[("x",)]["in_all_optimal_repairs"] is True
    assert by_tuple[("y",)]["in_all_optimal_repairs"] is True
    # A query over only globally-necessary rows (r3) would never return x;
    # that shortcut must therefore not be used to compute certainty.
    assert oracle(payload) == out


def test_self_join_witness_switch():
    payload = {
        "columns": ["A", "B"],
        "rows": [
            {"id": "r1", "weight": 1, "values": {"A": "1", "B": "10"}},
            {"id": "r2", "weight": 1, "values": {"A": "1", "B": "20"}},
            {"id": "r3", "weight": 3, "values": {"A": "2", "B": "30"}},
        ],
        "dependencies": [{"lhs": ["A"], "rhs": ["B"]}],
        "query": {
            "aliases": ["t", "u"],
            "conditions": [["t.A", "u.A"]],
            "projections": ["t.B", "u.B"],
        },
    }
    out = run(payload)
    assert out["optimal_weight"] == "4"
    assert out["optimal_repair_count"] == "2"
    by_tuple = {tuple(t["tuple"]): t for t in out["tuples"]}
    # the (30,30) witness survives the r1<->r2 repair switch
    assert by_tuple[("30", "30")]["optimal_repair_count"] == "2"
    assert by_tuple[("30", "30")]["in_all_optimal_repairs"] is True
    assert by_tuple[("10", "10")]["optimal_repair_count"] == "1"
    assert by_tuple[("10", "10")]["in_all_optimal_repairs"] is False
    assert by_tuple[("20", "20")]["optimal_repair_count"] == "1"
    assert oracle(payload) == out


def test_multiple_witnesses_in_one_repair_count_once():
    payload = {
        "columns": ["A"],
        "rows": [
            {"id": "r1", "weight": 1, "values": {"A": "z"}},
            {"id": "r2", "weight": 1, "values": {"A": "z"}},
        ],
        "dependencies": [],
        "query": {
            "aliases": ["t", "u"],
            "conditions": [],
            "projections": ["t.A"],
        },
    }
    out = run(payload)
    # four bindings, one unique tuple, one repair -> count must be 1 not 4
    assert out["optimal_repair_count"] == "1"
    assert len(out["tuples"]) == 1
    assert out["tuples"][0]["tuple"] == ["z"]
    assert out["tuples"][0]["optimal_repair_count"] == "1"
    assert oracle(payload) == out


def test_null_fd_and_query_semantics():
    payload = {
        "columns": ["K", "V"],
        "rows": [
            {"id": "r1", "weight": 1, "values": {"K": None, "V": "a"}},
            {"id": "r2", "weight": 1, "values": {"K": None, "V": "b"}},
            {"id": "r3", "weight": 10, "values": {"K": "k", "V": "c"}},
        ],
        "dependencies": [{"lhs": ["K"], "rhs": ["V"]}],
        "query": {
            "aliases": ["t"],
            "conditions": [["t.K", "t.K"]],
            "projections": ["t.V"],
        },
    }
    out = run(payload)
    # null == null makes r1,r2 conflict on the FD; two optimal repairs
    assert out["optimal_weight"] == "11"
    assert out["optimal_repair_count"] == "2"
    # equality condition rejects null cells: only r3 witnesses the query
    assert len(out["tuples"]) == 1
    assert out["tuples"][0]["tuple"] == ["c"]
    assert out["tuples"][0]["optimal_repair_count"] == "2"
    assert out["tuples"][0]["in_all_optimal_repairs"] is True
    assert oracle(payload) == out


def test_null_sorts_after_strings_and_utf8_byte_order():
    payload = {
        "columns": ["C"],
        "rows": [
            {"id": "r1", "weight": 1, "values": {"C": None}},
            {"id": "r2", "weight": 1, "values": {"C": "b"}},
            {"id": "r3", "weight": 1, "values": {"C": "a"}},
            {"id": "r4", "weight": 1, "values": {"C": "é"}},
        ],
        "dependencies": [],
        "query": {"aliases": ["t"], "conditions": [], "projections": ["t.C"]},
    }
    out = run(payload)
    ordered = [tuple(t["tuple"]) for t in out["tuples"]]
    assert ordered == [("a",), ("b",), ("é",), (None,)]
    assert oracle(payload) == out


def test_cross_dependency_conflicts():
    payload = {
        "columns": ["A", "B", "C"],
        "rows": [
            {"id": "r1", "weight": 1, "values": {"A": "1", "B": "1", "C": "1"}},
            {"id": "r2", "weight": 1, "values": {"A": "1", "B": "2", "C": "1"}},
            {"id": "r3", "weight": 1, "values": {"A": "2", "B": "1", "C": "1"}},
            {"id": "r4", "weight": 1, "values": {"A": "2", "B": "1", "C": "2"}},
        ],
        "dependencies": [
            {"lhs": ["A"], "rhs": ["B"]},
            {"lhs": ["B"], "rhs": ["C"]},
        ],
        "query": {"aliases": ["t"], "conditions": [], "projections": ["t.A"]},
    }
    out = run(payload)
    # edges r1-r2 (A->B) and r1-r4, r3-r4 (B->C): three optimal pairs
    assert out["optimal_weight"] == "2"
    assert out["optimal_repair_count"] == "3"
    by_tuple = {tuple(t["tuple"]): t for t in out["tuples"]}
    assert by_tuple[("1",)]["optimal_repair_count"] == "3"
    assert by_tuple[("2",)]["optimal_repair_count"] == "3"
    assert all(t["in_all_optimal_repairs"] for t in out["tuples"])
    assert oracle(payload) == out


def test_weight_tradeoff_unique_optimum():
    payload = {
        "columns": ["A", "B"],
        "rows": [
            {"id": "r1", "weight": 10, "values": {"A": "x", "B": "1"}},
            {"id": "r2", "weight": 9, "values": {"A": "x", "B": "2"}},
            {"id": "r3", "weight": 8, "values": {"A": "y", "B": "3"}},
            {"id": "r4", "weight": 7, "values": {"A": "y", "B": "4"}},
        ],
        "dependencies": [{"lhs": ["A"], "rhs": ["B"]}],
        "query": {"aliases": ["t"], "conditions": [], "projections": ["t.B"]},
    }
    out = run(payload)
    assert out["optimal_weight"] == "18"
    assert out["optimal_repair_count"] == "1"
    assert {tuple(t["tuple"]) for t in out["tuples"]} == {("1",), ("3",)}
    assert all(t["in_all_optimal_repairs"] for t in out["tuples"])
    assert oracle(payload) == out


def test_empty_table_has_one_empty_repair():
    payload = {
        "columns": ["C"],
        "rows": [],
        "dependencies": [],
        "query": {"aliases": ["t"], "conditions": [], "projections": ["t.C"]},
    }
    out = run(payload)
    assert out == {
        "optimal_weight": "0",
        "optimal_repair_count": "1",
        "tuples": [],
    }
    assert oracle(payload) == out


def test_random_vs_oracle():
    rng = random.Random(20261112)
    for case in range(400):
        payload = random_payload(rng)
        expected = oracle(payload)
        actual = run(payload)
        assert actual == expected, f"oracle mismatch on case {case}: {payload}"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failures = 0
    for test in TESTS:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} test groups passed")
    sys.exit(1 if failures else 0)
