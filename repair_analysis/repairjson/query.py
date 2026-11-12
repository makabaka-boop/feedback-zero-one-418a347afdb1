"""Query evaluation over a single repaired table.

Every alias is bound to the *same* repaired table (a self-join); different
aliases may be bound to the same retained row.  All bindings are combined
by Cartesian product and a binding witnesses the query when every equality
condition holds: both sides must be non-null and their string values must
be equal.  Without conditions every binding is a witness.  Projected
tuples are deduplicated as a set within one repair, so several witness
bindings of one repair only count once.
"""

from itertools import product


def compile_query(query):
    """Pre-resolve references to (alias position, column) integer pairs."""
    alias_pos = {a: i for i, a in enumerate(query.aliases)}
    conditions = tuple(
        (
            (alias_pos[c[0].alias], c[0].column),
            (alias_pos[c[1].alias], c[1].column),
        )
        for c in query.conditions
    )
    projections = tuple((alias_pos[r.alias], r.column) for r in query.projections)
    return conditions, projections


def evaluate_on_repair(retained_rows, query):
    """Return the set of distinct projected tuples for one repair.

    ``retained_rows`` is a sequence/frozenset of :class:`Row` objects; the
    empty repair yields an empty result set.
    """
    conditions, projections = compile_query(query)
    rows = list(retained_rows)
    k = len(query.aliases)
    result = set()

    # product(rows, repeat=k): aliases may share the same row, and with no
    # rows the Cartesian product is empty, as required.
    for binding in product(rows, repeat=k):
        ok = True
        for (pa, ca), (pb, cb) in conditions:
            va = binding[pa].values[ca]
            vb = binding[pb].values[cb]
            # equality requires BOTH sides non-null and equal values
            if va is None or vb is None or va != vb:
                ok = False
                break
        if not ok:
            continue
        tuple_ = tuple(binding[pa].values[col] for pa, col in projections)
        result.add(tuple_)

    return result
