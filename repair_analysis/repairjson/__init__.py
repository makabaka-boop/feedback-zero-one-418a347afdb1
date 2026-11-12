"""Backend repair-analysis package: maximum-weight FD repairs and query
certainty analysis over contradictory scientific master data."""

from .pipeline import run
from .validate import InputError

__all__ = ["run", "InputError"]
