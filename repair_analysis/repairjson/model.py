"""Plain data structures shared by the validation, solving and query layers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Ref:
    """A query reference ``alias.column``."""

    alias: str
    column: str


@dataclass(frozen=True)
class Dependency:
    """Functional dependency lhs -> rhs (both tuples of columns)."""

    lhs: tuple
    rhs: tuple


@dataclass(frozen=True)
class Row:
    id: str
    weight: int
    values: dict  # column -> str | None


@dataclass(frozen=True)
class Query:
    aliases: tuple          # tuple[str]
    conditions: tuple       # tuple[(Ref, Ref)]
    projections: tuple      # tuple[Ref]


@dataclass(frozen=True)
class Problem:
    columns: list
    rows: list              # list[Row]
    dependencies: list      # list[Dependency]
    query: Query
