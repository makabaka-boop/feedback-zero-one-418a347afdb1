"""Strict validation of the repair-analysis input JSON.

Every structural problem raises :class:`InputError` whose message carries a
JSONPath-like location (e.g. ``rows[2].weight``) so the whole job can be
rejected with a precise location.
"""

from .model import Dependency, Problem, Query, Ref, Row


class InputError(ValueError):
    """Raised for any malformed input. Message starts with a JSON path."""

    def __init__(self, path, message):
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path


# ---------------------------------------------------------------------------
# small type/structure helpers
# ---------------------------------------------------------------------------

def _is_int_not_bool(x):
    """The spec forbids booleans wherever integers are required."""
    return isinstance(x, int) and not isinstance(x, bool)


def _is_ident(x):
    return (
        isinstance(x, str)
        and len(x) > 0
        and all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in x)
    )


def _require_keys(obj, allowed, path):
    extra = set(obj) - set(allowed)
    if extra:
        name = sorted(extra)[0]
        raise InputError(f"{path}.{name}", "unexpected field")


def _check_object(obj, path):
    if not isinstance(obj, dict):
        raise InputError(path, "expected an object")


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------

def validate(payload):
    """Validate a decoded JSON payload and build a :class:`Problem`."""
    _check_object(payload, "$")
    _require_keys(payload, ("columns", "rows", "dependencies", "query"), "$")

    columns = _validate_columns(payload.get("columns"))
    rows = _validate_rows(payload.get("rows"), columns)
    deps = _validate_dependencies(payload.get("dependencies"), columns)
    query = _validate_query(payload.get("query"), columns)

    return Problem(columns=columns, rows=rows, dependencies=deps, query=query)


def _validate_columns(raw):
    path = "$.columns"
    if not isinstance(raw, list):
        raise InputError(path, "expected an array")
    seen = set()
    for i, col in enumerate(raw):
        p = f"{path}[{i}]"
        if not _is_ident(col):
            raise InputError(
                p,
                "column name must be a non-empty ASCII alphanumeric/underscore string",
            )
        if col in seen:
            raise InputError(p, f"duplicate column name {col!r}")
        seen.add(col)
    return list(raw)


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def _validate_rows(raw, columns):
    path = "$.rows"
    if not isinstance(raw, list):
        raise InputError(path, "expected an array")

    colset = set(columns)
    seen_ids = set()
    rows = []

    for i, item in enumerate(raw):
        p = f"{path}[{i}]"
        _check_object(item, p)
        _require_keys(item, ("id", "weight", "values"), p)

        rid = item.get("id")
        if not _is_ident(rid):
            raise InputError(
                f"{p}.id",
                "row id must be a non-empty ASCII alphanumeric/underscore string",
            )
        if rid in seen_ids:
            raise InputError(f"{p}.id", f"duplicate row id {rid!r}")
        seen_ids.add(rid)

        weight = item.get("weight")
        if not _is_int_not_bool(weight) or weight <= 0:
            raise InputError(
                f"{p}.weight", "weight must be a positive integer (booleans forbidden)"
            )

        values = item.get("values")
        _check_object(values, f"{p}.values")
        if set(values) != colset:
            missing = sorted(colset - set(values))
            unknown = sorted(set(values) - colset)
            detail = []
            if missing:
                detail.append(f"missing {missing}")
            if unknown:
                detail.append(f"unknown {unknown}")
            raise InputError(
                f"{p}.values",
                "values must contain exactly every column; " + "; ".join(detail),
            )
        cells = {}
        for col in columns:  # fixed canonical order
            v = values[col]
            if v is not None and not isinstance(v, str):
                raise InputError(
                    f"{p}.values.{col}", "cell must be a string or null"
                )
            cells[col] = v

        rows.append(Row(id=rid, weight=weight, values=cells))

    return rows


# ---------------------------------------------------------------------------
# functional dependencies
# ---------------------------------------------------------------------------

def _validate_dependencies(raw, columns):
    path = "$.dependencies"
    if not isinstance(raw, list):
        raise InputError(path, "expected an array")
    colset = set(columns)
    deps = []

    for i, item in enumerate(raw):
        p = f"{path}[{i}]"
        _check_object(item, p)
        _require_keys(item, ("lhs", "rhs"), p)

        lhs = _check_col_array(item.get("lhs"), f"{p}.lhs", colset)
        rhs = _check_col_array(item.get("rhs"), f"{p}.rhs", colset)
        deps.append(Dependency(lhs=tuple(lhs), rhs=tuple(rhs)))

    return deps


def _check_col_array(raw, path, colset):
    if not isinstance(raw, list) or len(raw) == 0:
        raise InputError(path, "expected a non-empty array of column names")
    seen = set()
    for i, col in enumerate(raw):
        p = f"{path}[{i}]"
        if not isinstance(col, str) or col not in colset:
            raise InputError(p, "must reference an existing column")
        if col in seen:
            raise InputError(p, "duplicate column inside the array")
        seen.add(col)
    return list(raw)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

def _validate_query(raw, columns):
    path = "$.query"
    _check_object(raw, path)
    _require_keys(raw, ("aliases", "conditions", "projections"), path)

    aliases_raw = raw.get("aliases")
    if not isinstance(aliases_raw, list) or len(aliases_raw) == 0:
        raise InputError(f"{path}.aliases", "expected a non-empty array")
    aliases = []
    seen = set()
    for i, a in enumerate(aliases_raw):
        p = f"{path}.aliases[{i}]"
        if not _is_ident(a):
            raise InputError(
                p,
                "alias must be a non-empty ASCII alphanumeric/underscore string",
            )
        if a in seen:
            raise InputError(p, f"duplicate alias {a!r}")
        seen.add(a)
        aliases.append(a)

    conditions = _validate_conditions(raw.get("conditions"), aliases, columns, path)
    projections = _validate_projections(
        raw.get("projections"), aliases, columns, path
    )

    return Query(
        aliases=tuple(aliases),
        conditions=tuple(conditions),
        projections=tuple(projections),
    )


def _parse_ref(raw, path, alias_set, colset):
    if not isinstance(raw, str):
        raise InputError(path, "reference must be a string alias.column")
    parts = raw.split(".")
    if len(parts) != 2:
        raise InputError(path, "reference must have the form alias.column")
    alias, col = parts
    if alias not in alias_set:
        raise InputError(path, f"unknown alias {alias!r}")
    if col not in colset:
        raise InputError(path, f"unknown column {col!r}")
    return Ref(alias=alias, column=col)


def _validate_conditions(raw, aliases, columns, qpath):
    path = f"{qpath}.conditions"
    if not isinstance(raw, list):
        raise InputError(path, "expected an array")
    alias_set, colset = set(aliases), set(columns)
    conds = []
    for i, cond in enumerate(raw):
        p = f"{path}[{i}]"
        if not isinstance(cond, list) or len(cond) != 2:
            raise InputError(p, "condition must be a two-element array of references")
        left = _parse_ref(cond[0], f"{p}[0]", alias_set, colset)
        right = _parse_ref(cond[1], f"{p}[1]", alias_set, colset)
        conds.append((left, right))
    return conds


def _validate_projections(raw, aliases, columns, qpath):
    path = f"{qpath}.projections"
    if not isinstance(raw, list) or len(raw) == 0:
        raise InputError(path, "expected a non-empty array of references")
    alias_set, colset = set(aliases), set(columns)
    projs = []
    for i, ref in enumerate(raw):
        projs.append(_parse_ref(ref, f"{path}[{i}]", alias_set, colset))
    return projs
