import random

import pytest

from json_diff_studio import ArrayKey, Options, PatchError, apply_patch, make_patch


# Примеры из RFC 6902, приложение A (сокращённо)
RFC_CASES = [
    ({"foo": "bar"}, [{"op": "add", "path": "/baz", "value": "qux"}], {"baz": "qux", "foo": "bar"}),
    ({"foo": ["bar", "baz"]}, [{"op": "add", "path": "/foo/1", "value": "qux"}],
     {"foo": ["bar", "qux", "baz"]}),
    ({"baz": "qux", "foo": "bar"}, [{"op": "remove", "path": "/baz"}], {"foo": "bar"}),
    ({"foo": ["bar", "qux", "baz"]}, [{"op": "remove", "path": "/foo/1"}], {"foo": ["bar", "baz"]}),
    ({"baz": "qux", "foo": "bar"}, [{"op": "replace", "path": "/baz", "value": "boo"}],
     {"baz": "boo", "foo": "bar"}),
    ({"foo": {"bar": "baz", "waldo": "fred"}, "qux": {"corge": "grault"}},
     [{"op": "move", "from": "/foo/waldo", "path": "/qux/thud"}],
     {"foo": {"bar": "baz"}, "qux": {"corge": "grault", "thud": "fred"}}),
    ({"foo": ["all", "grass", "cows", "eat"]}, [{"op": "move", "from": "/foo/1", "path": "/foo/3"}],
     {"foo": ["all", "cows", "eat", "grass"]}),
    ({"foo": "bar"}, [{"op": "add", "path": "/child", "value": {"grandchild": {}}}],
     {"foo": "bar", "child": {"grandchild": {}}}),
    ({"foo": ["bar"]}, [{"op": "add", "path": "/foo/-", "value": ["abc", "def"]}],
     {"foo": ["bar", ["abc", "def"]]}),
    ({"/": 9, "~1": 10}, [{"op": "test", "path": "/~01", "value": 10}], {"/": 9, "~1": 10}),
    ({"foo": 1}, [{"op": "copy", "from": "/foo", "path": "/bar"}], {"foo": 1, "bar": 1}),
    ({"foo": 1}, [{"op": "replace", "path": "", "value": [1]}], [1]),
]


@pytest.mark.parametrize("doc,patch,expected", RFC_CASES)
def test_rfc_examples(doc, patch, expected):
    assert apply_patch(doc, patch) == expected


@pytest.mark.parametrize("doc,patch", [
    ({"baz": "qux"}, [{"op": "test", "path": "/baz", "value": "bar"}]),
    ({"foo": "bar"}, [{"op": "add", "path": "/baz/bat", "value": "qux"}]),
    ({"foo": [1]}, [{"op": "add", "path": "/foo/5", "value": 2}]),
    ({"foo": [1]}, [{"op": "remove", "path": "/foo/01"}]),
    ({"foo": 1}, [{"op": "remove", "path": "/bar"}]),
    ({"foo": 1}, [{"op": "replace", "path": "/bar", "value": 1}]),
    ({"foo": 1}, [{"op": "jump", "path": "/foo"}]),
    ({"foo": 1}, [{"op": "add", "path": "/x"}]),
    ({"foo": 1}, [{"op": "add", "path": "x", "value": 1}]),
    ({"a": {"b": 1}}, [{"op": "move", "from": "/a", "path": "/a/b/c"}]),
    ({"a": 1}, [{"op": "test", "path": "/a", "value": True}]),
    ({}, {"op": "add"}),
    ({}, ["not an op"]),
    ({"a": 1}, [{"op": "remove", "path": ""}]),
])
def test_errors(doc, patch):
    with pytest.raises(PatchError):
        apply_patch(doc, patch)


def test_error_index_and_atomicity():
    doc = {"a": 1}
    with pytest.raises(PatchError) as info:
        apply_patch(doc, [{"op": "replace", "path": "/a", "value": 2},
                          {"op": "remove", "path": "/missing"}])
    assert info.value.index == 1
    assert "#1" in str(info.value)
    assert doc == {"a": 1}


def test_make_patch_with_tests_detects_drift():
    a, b = {"a": 1}, {"a": 2}
    patch = make_patch(a, b, with_tests=True)
    assert patch[0] == {"op": "test", "path": "/a", "value": 1}
    with pytest.raises(PatchError):
        apply_patch({"a": 5}, patch)


def test_make_patch_respects_ignore():
    a = {"ts": 1, "v": 1}
    b = {"ts": 2, "v": 2}
    assert make_patch(a, b, Options(ignore=["$.ts"])) == [
        {"op": "replace", "path": "/v", "value": 2}]


def test_make_patch_ignores_report_only_options():
    patch = make_patch({"x": 1.0}, {"x": 1.0000001}, Options(tolerance=1))
    assert patch == [{"op": "replace", "path": "/x", "value": 1.0000001}]


def test_patch_value_is_copied():
    b = {"a": {"nested": [1]}}
    patch = make_patch({}, b)
    patch[0]["value"]["nested"].append(2)
    assert b == {"a": {"nested": [1]}}


# --------------------------------------------------- свойство: apply(a, make_patch(a, b)) == b

def random_json(rng, depth=0):
    kind = rng.random()
    if depth > 3 or kind < 0.35:
        return rng.choice([None, True, False, 0, 1, 2, 3.5, -1, "a", "b", "c", "", "ж"])
    if kind < 0.65:
        return [random_json(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    keys = rng.sample(["a", "b", "c", "d", "x/y", "m~n", "id"], rng.randint(0, 4))
    return {k: random_json(rng, depth + 1) for k in keys}


def mutate(rng, value, depth=0):
    if rng.random() < 0.2:
        return random_json(rng, depth)
    if isinstance(value, list):
        out = [mutate(rng, v, depth + 1) if rng.random() < 0.4 else v for v in value]
        for _ in range(rng.randint(0, 2)):
            op = rng.random()
            if op < 0.4:
                out.insert(rng.randint(0, len(out)), random_json(rng, depth + 1))
            elif op < 0.7 and out:
                out.pop(rng.randrange(len(out)))
            elif len(out) > 1:
                i, j = rng.randrange(len(out)), rng.randrange(len(out))
                out[i], out[j] = out[j], out[i]
        return out
    if isinstance(value, dict):
        out = {k: (mutate(rng, v, depth + 1) if rng.random() < 0.4 else v)
               for k, v in value.items() if rng.random() > 0.15}
        if rng.random() < 0.3:
            out[rng.choice(["new", "a", "q"])] = random_json(rng, depth + 1)
        return out
    return value


def keyed_list(rng):
    ids = rng.sample(range(12), rng.randint(0, 8))
    return [{"id": i, "v": rng.randint(0, 3), "tags": random_json(rng, 2)} for i in ids]


@pytest.mark.parametrize("seed", range(300))
def test_property_patch_roundtrip(seed):
    rng = random.Random(seed)
    a = random_json(rng)
    b = mutate(rng, a)
    patch = make_patch(a, b)
    assert apply_patch(a, patch) == b
    assert apply_patch(a, make_patch(a, b, with_tests=True)) == b


@pytest.mark.parametrize("seed", range(200))
def test_property_keyed_roundtrip(seed):
    rng = random.Random(1000 + seed)
    a, b = {"items": keyed_list(rng)}, {"items": keyed_list(rng)}
    opts = Options(array_keys=[ArrayKey("id")])
    assert apply_patch(a, make_patch(a, b, opts)) == b
