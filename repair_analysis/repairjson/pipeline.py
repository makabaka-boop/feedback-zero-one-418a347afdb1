"""End-to-end analysis: validation -> optimal repairs -> query aggregation.

Output ordering rules (shared by every result tuple comparison):

* tuples are compared position by position in projection order;
* each position is either ``null`` or a UTF-8 string;
* strings compare by UTF-8 byte (lexicographic) order;
* ``null`` sorts after every string.
"""

from .query import evaluate_on_repair
from .solver import (
    build_conflict_graph,
    enumerate_optimal_repairs,
    maximum_retained_weight,
)
from .validate import validate


def _sort_key(tuple_):
    # None (null) is placed last via the leading flag: strings -> (0, bytes),
    # null -> (1, b""), and (1, ...) always exceeds (0, ...).
    key = []
    for v in tuple_:
        if v is None:
            key.append((1, b""))
        else:
            key.append((0, v.encode("utf-8")))
    return tuple(key)


def run(payload):
    """Validate the payload and return the full result dictionary."""
    problem = validate(payload)
    rows = problem.rows
    weights = [r.weight for r in rows]

    adj = build_conflict_graph(rows, problem.dependencies)
    best_weight = maximum_retained_weight(weights, adj)
    optimal_sets = enumerate_optimal_repairs(weights, adj, best_weight)

    total_optimal = len(optimal_sets)

    # tuple -> number of distinct optimal repairs that produce it
    tuple_counts = {}
    for index_set in optimal_sets:
        retained = [rows[i] for i in index_set]
        produced = evaluate_on_repair(retained, problem.query)
        for tuple_ in produced:  # set: multiple witnesses count once
            tuple_counts[tuple_] = tuple_counts.get(tuple_, 0) + 1

    tuples_out = []
    for tuple_ in sorted(tuple_counts, key=_sort_key):
        count = tuple_counts[tuple_]
        tuples_out.append(
            {
                "tuple": list(tuple_),
                "optimal_repair_count": str(count),
                "in_all_optimal_repairs": count == total_optimal,
            }
        )

    return {
        "optimal_weight": str(best_weight),
        "optimal_repair_count": str(total_optimal),
        "tuples": tuples_out,
    }
