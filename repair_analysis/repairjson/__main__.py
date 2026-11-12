"""Allow ``python -m repairjson ...`` as an alias of the CLI entry point."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
