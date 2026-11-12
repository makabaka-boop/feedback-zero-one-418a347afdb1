"""Exact maximum-weight repair search over functional dependencies.

A repair may only delete whole rows and must satisfy every dependency.
For two retained rows, a dependency is violated exactly when they agree on
all lhs columns (null == null counts as equal) but disagree on some rhs
column.  We therefore build an undirected *conflict graph* on the rows: an
edge means the pair cannot coexist in any valid repair.  Valid repairs are
precisely the independent sets of this graph, and maximizing retained
weight is the maximum-weight independent set problem, solved here with an
exact branch-and-bound enumeration that returns **all** optimal repairs.
"""


# ---------------------------------------------------------------------------
# conflict graph
# ---------------------------------------------------------------------------

def build_conflict_graph(rows, dependencies):
    """Return adjacency sets of rows that violate at least one dependency."""
    n = len(rows)
    adj = [set() for _ in range(n)]

    for dep in dependencies:
        lhs, rhs = dep.lhs, dep.rhs
        # group row indices by their lhs value-tuple; only rows inside the
        # same group can conflict under this dependency
        groups = {}
        for i, row in enumerate(rows):
            key = tuple(row.values[c] for c in lhs)
            groups.setdefault(key, []).append(i)

        for members in groups.values():
            for a in range(len(members)):
                i = members[a]
                ri = rows[i]
                for b in range(a + 1, len(members)):
                    j = members[b]
                    rj = rows[j]
                    # lhs equal by construction (including null==null);
                    # violation iff some rhs cell differs
                    if any(ri.values[c] != rj.values[c] for c in rhs):
                        adj[i].add(j)
                        adj[j].add(i)
    return adj


# ---------------------------------------------------------------------------
# greedy feasible lower bound (deterministic)
# ---------------------------------------------------------------------------

def greedy_independent_set(weights, adj):
    """A deterministic greedy independent set, used as an initial lower bound."""
    n = len(weights)
    alive = set(range(n))
    chosen = []
    while alive:
        # highest weight first, break ties by smallest index
        v = min(alive, key=lambda x: (-weights[x], x))
        chosen.append(v)
        alive.discard(v)
        alive -= adj[v]
    return chosen


# ---------------------------------------------------------------------------
# branch and bound
# ---------------------------------------------------------------------------

def _forced_vertices(rem, adj):
    """Vertices with no conflict with any other remaining vertex.

    They appear in every independent set of the remainder, so they can be
    forced into the solution without any branching.
    """
    return [v for v in rem if not (adj[v] & rem)]


def _branch_vertex(rem, adj):
    """Highest-degree remaining vertex (ties: smallest index)."""
    return min(rem, key=lambda v: (-len(adj[v] & rem), v))


def maximum_retained_weight(weights, adj):
    """Phase 1: compute the maximum total weight of an independent set."""
    n = len(weights)
    best = sum(weights[i] for i in greedy_independent_set(weights, adj))
    total = sum(weights)

    def recurse(rem, current, rem_weight):
        nonlocal best
        if current + rem_weight <= best:
            return
        forced = _forced_vertices(rem, adj)
        if forced:
            fset = set(forced)
            fw = sum(weights[v] for v in forced)
            new_rem = rem - fset
            recurse(new_rem, current + fw, rem_weight - fw)
            return
        if not rem:
            if current > best:
                best = current
            return
        v = _branch_vertex(rem, adj)
        # branch 1: exclude v
        rem1 = set(rem)
        rem1.discard(v)
        recurse(rem1, current, rem_weight - weights[v])
        # branch 2: include v (then all its neighbours are excluded)
        rem2 = rem1 - adj[v]
        recurse(rem2, current + weights[v],
                rem_weight - weights[v] - sum(weights[u] for u in adj[v] & rem))

    recurse(set(range(n)), 0, total)
    return best


def enumerate_optimal_repairs(weights, adj, target):
    """Phase 2: enumerate every independent set whose weight equals target.

    Returns a list of frozensets of row indices.
    """
    n = len(weights)
    solutions = []
    total = sum(weights)

    def recurse(rem, chosen, current, rem_weight):
        if current + rem_weight < target:
            return
        forced = _forced_vertices(rem, adj)
        if forced:
            fset = set(forced)
            fw = sum(weights[v] for v in forced)
            recurse(rem - fset, chosen | fset, current + fw, rem_weight - fw)
            return
        if current == target:
            solutions.append(frozenset(chosen))
            return
        if not rem:
            return
        v = _branch_vertex(rem, adj)
        # exclude v
        recurse(rem - {v}, chosen, current, rem_weight - weights[v])
        # include v, excluding all its neighbours
        blocked = adj[v] & rem
        recurse(
            rem - {v} - blocked,
            chosen | {v},
            current + weights[v],
            rem_weight - weights[v] - sum(weights[u] for u in blocked),
        )

    recurse(set(range(n)), set(), 0, total)
    return solutions
