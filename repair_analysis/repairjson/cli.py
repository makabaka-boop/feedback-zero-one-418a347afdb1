"""Command line entry point.

Usage:
    python -m repairjson.cli INPUT.json OUTPUT.json

The output file is replaced only after the whole job succeeds.  Input is
read as UTF-8 and malformed or semantically invalid payloads are rejected
with an exit status of 1 and a message that locates the offending path;
the output path is never touched in that case.
"""

import json
import os
import sys
import tempfile

from .pipeline import run
from .validate import InputError


class _DuplicateKeyDetector:
    """object_pairs_hook that rejects JSON objects with duplicate keys."""

    def __init__(self):
        self.counter = 0

    def __call__(self, pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                raise ValueError(f"duplicate JSON object key {key!r}")
            seen.add(key)
        return dict(pairs)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python -m repairjson.cli INPUT.json OUTPUT.json",
              file=sys.stderr)
        return 2

    input_path, output_path = argv

    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh, object_pairs_hook=_DuplicateKeyDetector())
        result = run(payload)
    except FileNotFoundError:
        print(f"$: input file not found: {input_path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"$: invalid JSON: {exc}", file=sys.stderr)
        return 1
    except (InputError, ValueError) as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1

    # Atomic replacement: write a temp file in the same directory and rename,
    # so a failed run never leaves a partial or replaced output behind.
    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".repairjson-", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, output_path)
    except OSError as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        print(f"$: failed to write output: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
