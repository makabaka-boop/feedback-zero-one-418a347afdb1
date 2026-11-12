"""Validation and CLI acceptance tests.

Checks that every class of illegal input is rejected with a locating path,
that booleans are not accepted as integers, that a rejected run never
replaces the output file, and that duplicate JSON keys are refused.

Run (from the project root):
    python -I tests/test_validation.py
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from repairjson.cli import main  # noqa: E402
from repairjson.pipeline import run  # noqa: E402
from repairjson.validate import InputError  # noqa: E402


VALID = {
    "columns": ["K", "V"],
    "rows": [
        {"id": "r1", "weight": 1, "values": {"K": "x", "V": "y"}},
    ],
    "dependencies": [{"lhs": ["K"], "rhs": ["V"]}],
    "query": {
        "aliases": ["t"],
        "conditions": [["t.K", "t.K"]],
        "projections": ["t.K"],
    },
}


def _expect_reject(mutator, path_fragment):
    payload = json.loads(json.dumps(VALID))
    mutator(payload)
    try:
        run(payload)
    except InputError as exc:
        assert path_fragment in str(exc), f"{exc!s} lacks {path_fragment!r}"
        return
    raise AssertionError(f"expected rejection mentioning {path_fragment!r}")


def test_illegal_inputs():
    _expect_reject(lambda p: p.update({"bogus": 1}), "$.bogus")
    _expect_reject(lambda p: p["columns"].__setitem__(0, ""), "$.columns[0]")
    _expect_reject(lambda p: p["columns"].append("K"), "$.columns[2]")
    _expect_reject(lambda p: p["rows"][0].__setitem__("id", "bad-id"),
                   "$.rows[0].id")
    _expect_reject(lambda p: p["rows"][0].__setitem__("weight", 0),
                   "$.rows[0].weight")
    _expect_reject(lambda p: p["rows"][0].__setitem__("weight", True),
                   "$.rows[0].weight")
    _expect_reject(lambda p: p["rows"][0]["values"].pop("V"),
                   "$.rows[0].values")
    _expect_reject(lambda p: p["rows"][0]["values"].__setitem__("V", 7),
                   "$.rows[0].values.V")
    _expect_reject(lambda p: p["rows"][0]["values"].__setitem__("X", "z"),
                   "$.rows[0].values")
    _expect_reject(lambda p: p["dependencies"][0]["lhs"].append("K"),
                   "$.dependencies[0].lhs[1]")
    _expect_reject(lambda p: p["dependencies"][0]["lhs"].__setitem__(0, "nope"),
                   "$.dependencies[0].lhs[0]")
    _expect_reject(lambda p: p["dependencies"][0].__setitem__("rhs", []),
                   "$.dependencies[0].rhs")
    _expect_reject(lambda p: p["query"]["aliases"].append("t"),
                   "$.query.aliases[1]")
    _expect_reject(lambda p: p["query"]["conditions"][0].__setitem__(0, "x"),
                   "$.query.conditions[0][0]")
    _expect_reject(lambda p: p["query"]["conditions"][0].__setitem__(0, "z.K"),
                   "$.query.conditions[0][0]")
    _expect_reject(lambda p: p["query"].__setitem__("projections", []),
                   "$.query.projections")
    _expect_reject(lambda p: p["query"]["projections"].__setitem__(0, "t.nope"),
                   "$.query.projections[0]")
    _expect_reject(lambda p: p.pop("rows"), "$.rows")


def test_top_level_type_rejected():
    try:
        run([])
    except InputError as exc:
        assert str(exc).startswith("$")
    else:
        raise AssertionError("top-level array must be rejected")


def test_cli_rejected_run_preserves_output():
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.json")
        out_path = os.path.join(tmp, "nested", "out.json")
        sentinel = "DO-NOT-REPLACE"
        os.makedirs(os.path.dirname(out_path))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(sentinel)
        bad = json.loads(json.dumps(VALID))
        bad["rows"][0]["weight"] = -3
        with open(in_path, "w", encoding="utf-8") as fh:
            json.dump(bad, fh)

        rc = main([in_path, out_path])
        assert rc == 1
        with open(out_path, encoding="utf-8") as fh:
            assert fh.read() == sentinel


def test_cli_successful_run_replaces_output_and_roundtrips():
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.json")
        out_path = os.path.join(tmp, "out.json")
        with open(in_path, "w", encoding="utf-8") as fh:
            json.dump(VALID, fh)

        rc = main([in_path, out_path])
        assert rc == 0
        with open(out_path, encoding="utf-8") as fh:
            result = json.load(fh)
        assert result["optimal_weight"] == "1"
        assert result["optimal_repair_count"] == "1"
        assert result["tuples"][0]["tuple"] == ["x"]
        # counts are decimal strings, not JSON numbers
        assert isinstance(result["optimal_weight"], str)
        assert isinstance(result["tuples"][0]["optimal_repair_count"], str)


def test_duplicate_json_keys_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.json")
        out_path = os.path.join(tmp, "out.json")
        with open(in_path, "w", encoding="utf-8") as fh:
            fh.write('{"columns": ["C"], "columns": ["C"], "rows": [],'
                     ' "dependencies": [], "query": {"aliases": ["t"],'
                     ' "conditions": [], "projections": ["t.C"]}}')
        rc = main([in_path, out_path])
        assert rc == 1
        assert not os.path.exists(out_path)


def test_invalid_json_syntax_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.json")
        out_path = os.path.join(tmp, "out.json")
        with open(in_path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert main([in_path, out_path]) == 1
        assert not os.path.exists(out_path)


def test_module_invocation_matches_cli():
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.json")
        out_path = os.path.join(tmp, "out.json")
        with open(in_path, "w", encoding="utf-8") as fh:
            json.dump(VALID, fh)
        driver = os.path.join(HERE, "_cli_driver.py")
        proc = subprocess.run(
            [sys.executable, "-I", driver, in_path, out_path],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert os.path.exists(out_path)


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
