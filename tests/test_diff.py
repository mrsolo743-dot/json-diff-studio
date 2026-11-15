from json_diff_studio import ArrayKey, Options, diff, summarize
from json_diff_studio.diff import MISSING, canonical, lcs_pairs, lis_keep, strict_equal, type_name


def paths(changes):
    return [(c.type, c.path_str) for c in changes]


def test_type_names_and_strict_equal():
    assert [type_name(v) for v in (None, True, 1, 1.5, "s", [], {})] == [
        "null", "boolean", "number", "number", "string", "array", "object"]
    assert strict_equal(1, 1.0)
    assert not strict_equal(True, 1)
    assert not strict_equal({"a": 1}, {"a": 1, "b": 2})
    assert canonical({"b": 1.0, "a": [True]}) == '{"a":[true],"b":1}'


def test_no_changes():
    doc = {"a": [1, {"b": None}], "c": "x"}
    assert diff(doc, doc) == []


def test_object_changes():
    ch = diff({"a": 1, "b": 2}, {"a": 3, "c": 4})
    assert paths(ch) == [("changed", "$.a"), ("removed", "$.b"), ("added", "$.c")]
    assert ch[1].old == 2 and ch[1].new is MISSING
    assert summarize(ch) == {"added": 1, "removed": 1, "changed": 1, "moved": 0, "total": 3}


def test_type_change_flag():
    (c,) = diff({"v": "1"}, {"v": 1})
    assert c.type_changed


def test_lcs_insertion_is_single_add():
    ch = diff(list(range(10)), [0, 1, 2, "x", 3, 4, 5, 6, 7, 8, 9])
    assert paths(ch) == [("added", "$[3]")]


def test_lcs_pairs_prefix_suffix():
    assert lcs_pairs([1, 2, 3], [1, 2, 3]) == [(0, 0), (1, 1), (2, 2)]
    assert lcs_pairs([], [1]) == []


def test_large_arrays_fall_back_to_positions(monkeypatch):
    import importlib
    d = importlib.import_module("json_diff_studio.diff")
    monkeypatch.setattr(d, "LCS_LIMIT", 4)
    ch = diff([1, 2, 3, 4], [9, 1, 2, 3])
    # без LCS вставка в начало выглядит как цепочка замен
    assert [c.type for c in ch] == ["changed"] * 4


def test_keyed_arrays():
    a = {"users": [{"id": 1, "n": "a"}, {"id": 2, "n": "b"}]}
    b = {"users": [{"id": 2, "n": "B"}, {"id": 1, "n": "a"}]}
    opts = Options(array_keys=[ArrayKey("id")])
    assert paths(diff(a, b, opts)) == [
        ("moved", "$.users[id=2]"), ("changed", "$.users[id=2].n")]
    # без ключа то же самое выглядит иначе
    assert ("moved", "$.users[id=2]") not in paths(diff(a, b))


def test_keyed_rule_with_path():
    rule = ArrayKey.parse("$.x=id")
    assert rule.where == "$.x" and rule.key == "id"
    assert rule.applies(("x",)) and not rule.applies(("y",))


def test_keyed_falls_back_when_key_missing():
    a = [{"id": 1}, {"name": "no id"}]
    b = [{"id": 1}, {"name": "changed"}]
    ch = diff(a, b, Options(array_keys=[ArrayKey("id")]))
    assert paths(ch) == [("changed", "$[1].name")]


def test_lis_keep():
    assert lis_keep([]) == set()
    assert len(lis_keep([3, 1, 0, 2])) == 2
    assert lis_keep([0, 1, 2]) == {0, 1, 2}


def test_ignore_patterns_and_keys():
    a = {"meta": {"ts": 1, "v": 1}, "list": [{"ts": 1, "x": 1}]}
    b = {"meta": {"ts": 2, "v": 2}, "list": [{"ts": 2, "x": 1}]}
    assert paths(diff(a, b, Options.from_dict({"ignoreKeys": ["ts"]}))) == [("changed", "$.meta.v")]
    assert paths(diff(a, b, Options(ignore=["$.meta"]))) == [("changed", "$.list[0].ts")]
    assert diff(a, b, Options(ignore=["$"])) == []


def test_ignore_applies_to_added_and_removed():
    ch = diff({"a": 1}, {"b": 2}, Options(ignore=["$.a", "$.b"]))
    assert ch == []


def test_tolerance_case_order():
    assert diff({"x": 1.0}, {"x": 1.0000001}, Options(tolerance=1e-6)) == []
    assert diff(["ABC"], ["abc"], Options(ignore_case=True)) == []
    assert diff([1, 2, 3], [3, 2, 1], Options(ignore_order=True)) == []
    ch = diff([1, 1, 2], [1, 2, 2], Options(ignore_order=True))
    assert paths(ch) == [("removed", "$[1]"), ("added", "$[2]")]


def test_to_dict():
    (c,) = diff({"a": [1]}, {"a": [1, 2]})
    assert c.to_dict() == {"type": "added", "path": "$.a[1]", "new": 2}
    assert c.pointer == "/a/1"
