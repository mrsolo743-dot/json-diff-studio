"""Общие фикстуры: те же ожидания проверяет JS-порт (web/tests/core.test.mjs)."""
import json
from pathlib import Path

import pytest

from json_diff_studio import Options, apply_patch, diff, make_patch

CASES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "cases.json")
                   .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_case(case):
    opts = Options.from_dict(case.get("options"))
    assert [c.to_dict() for c in diff(case["a"], case["b"], opts)] == case["changes"]
    patch = make_patch(case["a"], case["b"], opts, case.get("withTests", False))
    assert patch == case["patch"]
    assert apply_patch(case["a"], patch) == case["patched"]
    if not opts.ignore:
        assert case["patched"] == case["b"]
