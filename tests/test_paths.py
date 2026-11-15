import pytest

from json_diff_studio.paths import (KeyRef, PathMatcher, PatternError, format_path,
                                    parse_pattern, parse_pointer, to_pointer)


def test_format_path_variants():
    assert format_path(()) == "$"
    assert format_path(("a", 0, "b")) == "$.a[0].b"
    assert format_path(("with space", "a/b")) == '$["with space"]["a/b"]'
    assert format_path(("users", KeyRef(2, "id", 7), "email")) == "$.users[id=7].email"
    assert format_path((KeyRef(0, "k", "x"),)) == '$[k="x"]'
    assert format_path(("имя",)) == '$["имя"]'


def test_pointer_roundtrip_and_escaping():
    path = ("a/b", "m~n", 3, KeyRef(5, "id", 1))
    ptr = to_pointer(path)
    assert ptr == "/a~1b/m~0n/3/5"
    assert parse_pointer(ptr) == ["a/b", "m~n", "3", "5"]
    assert parse_pointer("") == []
    assert parse_pointer("/") == [""]
    with pytest.raises(ValueError):
        parse_pointer("a/b")


@pytest.mark.parametrize("pattern,path,expected", [
    ("$.a.b", ("a", "b"), True),
    ("$.a.b", ("a", "b", "c"), False),
    ("$.a.*", ("a", "x"), True),
    ("$.items[*].ts", ("items", 4, "ts"), True),
    ("$.items[*].ts", ("items", KeyRef(1, "id", 9), "ts"), True),
    ("$.items[2]", ("items", 2), True),
    ("$.items[2]", ("items", KeyRef(2, "id", 9)), True),
    ("$..ts", ("ts",), True),
    ("$..ts", ("a", 0, "b", "ts"), True),
    ("$..ts", ("a", "ts", "x"), False),
    ("$..b.c", ("x", "b", "c"), True),
    ('$["with space"]', ("with space",), True),
    ("$.users[id=7].email", ("users", KeyRef(0, "id", 7), "email"), True),
    ("$.users[id=7].email", ("users", KeyRef(0, "id", 8), "email"), False),
    ('$.users[name="Ann"]', ("users", KeyRef(0, "name", "Ann")), True),
    ("$.f[id=1]", ("f", KeyRef(0, "id", True)), False),
    ("$", (), True),
    ("$..*", ("anything", 1), True),
])
def test_match(pattern, path, expected):
    assert PathMatcher([pattern]).matches(path) is expected


@pytest.mark.parametrize("bad", ["a.b", "$.", "$[", "$[abc def]", "$.a b"])
def test_bad_patterns(bad):
    with pytest.raises(PatternError):
        parse_pattern(bad)
