"""Stress and cross-check tests beyond exhaustive 2^n reach.

Two independent checks:

1. *correctness* on medium instances (up to 14 rows): the pipeline's
   optimal weight and per-tuple counts are compared against the brute-force
   oracle reused from the exhaustive test module.
2. *performance* on larger instances (up to 24 rows): the optimal weight is
   cross-checked against an independent bitmask dynamic program over
   connected components (a different MWIS implementation), and run time is
   measured.

Run (from the project root):
    python -I tests/test_stress.py
"""

import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from repairjson.pipeline import run  # noqa: E402
from repairjson.solver import (  # noqa: E402
    build_conflict_graph,
    enumerate_optimal_repairs,
    maximum_retained_weight,
)
from repairjson.validate import validate  # noqa: E402
from tests.test_exhaustive import oracle, random_payload  # noqa: E402


def test_medium_oracle_crosscheck():
    rng = random.Random(77)
    for case in range(60):
        payload = random_payload(rng)
        # push row count up to the exhaustive ceiling
        n = rng.randint(7, 14)
        cols = payload["columns"]
        pool = ["a", "b", None]
        payload["rows"] = [
            {
                "id": f"r{i}",
                "weight": rng.randint(1, 9),
                "values": {c: rng.choice(pool) for c in cols},
            }
            for i in range(n)
        ]
        assert run(payload) == oracle(payload), f"case {case}"


def _components(adj, n):
    seen = set()
    comps = []
    for start in range(n):
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            v = stack.pop()
            comp.append(v)
            for u in adj[v]:
                if u not in seen:
                    seen.add(u)
                    stack.append(u)
        comps.append(comp)
    return comps


def independent_mwis_weight(weights, adj):
    """Bitmask DP MWIS, written independently of the branch-and-bound code."""
    n = len(weights)
    total = 0
    for comp in _components(adj, n):
        m = len(comp)
        local_adj = [
            sum(
                1 << b for b, j in enumerate(comp) if j in adj[comp[a]]
            )
            for a in range(m)
        ]
        best = [0] * (1 << m)
        for mask in range(1, 1 << m):
            v = mask.bit_length() - 1
            without = best[mask ^ (1 << v)]
            with_v = weights[comp[v]] + best[mask & ~local_adj[v] & ~(1 << v)]
            best[mask] = max(without, with_v)
        total += best[-1]
    return total


def test_large_performance_and_weight_crosscheck():
    rng = random.Random(99)
    timings = []
    for case in range(40):
        n = rng.randint(15, 24)
        cols = ["a", "b", "c"]
        rows = [
            {
                "id": f"r{i}",
                "weight": rng.randint(1, 20),
                "values": {
                    "a": rng.choice(["x", "y", "z", None]),
                    "b": rng.choice(["p", "q", None]),
                    "c": rng.choice(["1", "2", None]),
                },
            }
            for i in range(n)
        ]
        deps = [
            {"lhs": ["a"], "rhs": ["b"]},
            {"lhs": ["b"], "rhs": ["c"]},
        ]
        payload = {
            "columns": cols,
            "rows": rows,
            "dependencies": deps,
            "query": {
                "aliases": ["t"],
                "conditions": [],
                "projections": ["t.a"],
            },
        }
        weights = [r["weight"] for r in rows]
        problem = validate(payload)
        adj = build_conflict_graph(problem.rows, problem.dependencies)

        t0 = time.perf_counter()
        w1 = maximum_retained_weight(weights, adj)
        solutions = enumerate_optimal_repairs(weights, adj, w1)
        elapsed = time.perf_counter() - t0
        timings.append(elapsed)

        w2 = independent_mwis_weight(weights, adj)
        assert w1 == w2, f"weight mismatch case {case}: {w1} vs {w2}"
        # every enumerated solution must really be optimal and independent
        for sol in solutions:
            assert sum(weights[i] for i in sol) == w1
            for i in sol:
                assert not (adj[i] & sol)

        out = run(payload)
        assert out["optimal_weight"] == str(w1)
        assert int(out["optimal_repair_count"]) == len(solutions)

    print(f"  max solve time over n<=24 instances: {max(timings):.3f}s "
          f"(mean {sum(timings)/len(timings):.3f}s)")


def test_dense_conflict_graph():
    # all rows share an lhs value with distinct rhs -> clique of 12:
    # optimum keeps the single heaviest row, 12 rows => 1 optimum
    rng = random.Random(1)
    n = 12
    rows = [
        {"id": f"r{i}", "weight": i + 1,
         "values": {"k": "same", "v": f"v{i}"}}
        for i in range(n)
    ]
    payload = {
        "columns": ["k", "v"],
        "rows": rows,
        "dependencies": [{"lhs": ["k"], "rhs": ["v"]}],
        "query": {"aliases": ["t"], "conditions": [],
                  "projections": ["t.v"]},
    }
    out = run(payload)
    assert out["optimal_weight"] == str(n)
    assert out["optimal_repair_count"] == "1"
    assert out["tuples"][0]["tuple"] == [f"v{n-1}"]


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
