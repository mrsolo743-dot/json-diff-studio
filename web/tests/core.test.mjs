// Тесты JS-порта: общие фикстуры с Python, RFC 6902 и свойство «патч восстанавливает b».
// Запуск: node --test web/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  applyPatch, changeToDict, diff, formatPath, KeyRef, makeOptions, makePatch,
  parseJsonWithPosition, parsePattern, PatchError, PathMatcher, toPointer, PatternError,
} from "../js/core.js";

const cases = JSON.parse(readFileSync(fileURLToPath(new URL("../../fixtures/cases.json", import.meta.url)), "utf8"));

for (const c of cases) {
  test(`фикстура: ${c.name}`, () => {
    const opts = makeOptions(c.options || {});
    assert.deepEqual(diff(c.a, c.b, opts).map(changeToDict), c.changes);
    const patch = makePatch(c.a, c.b, opts, Boolean(c.withTests));
    assert.deepEqual(patch, c.patch);
    assert.deepEqual(applyPatch(c.a, patch), c.patched);
  });
}

test("форматирование путей и JSON Pointer", () => {
  assert.equal(formatPath([]), "$");
  assert.equal(formatPath(["a", 0, "with space"]), '$.a[0]["with space"]');
  assert.equal(formatPath(["u", new KeyRef(1, "id", 7)]), "$.u[id=7]");
  assert.equal(toPointer(["a/b", "m~n", new KeyRef(4, "id", 1)]), "/a~1b/m~0n/4");
});

test("шаблоны путей", () => {
  const m = (p, path) => new PathMatcher([p]).matches(path);
  assert.ok(m("$..ts", ["a", 0, "ts"]));
  assert.ok(m("$.items[*].ts", ["items", new KeyRef(0, "id", 1), "ts"]));
  assert.ok(m("$.users[id=7]", ["users", new KeyRef(0, "id", 7)]));
  assert.ok(!m("$.f[id=1]", ["f", new KeyRef(0, "id", true)]));
  assert.ok(!m("$.a", ["a", "b"]));
  for (const bad of ["a.b", "$.", "$[", "$[abc def]"]) assert.throws(() => parsePattern(bad), PatternError);
});

const RFC = [
  [{ foo: ["bar", "baz"] }, [{ op: "add", path: "/foo/1", value: "qux" }], { foo: ["bar", "qux", "baz"] }],
  [{ foo: ["all", "grass", "cows", "eat"] }, [{ op: "move", from: "/foo/1", path: "/foo/3" }], { foo: ["all", "cows", "eat", "grass"] }],
  [{ foo: ["bar"] }, [{ op: "add", path: "/foo/-", value: ["abc"] }], { foo: ["bar", ["abc"]] }],
  [{ "/": 9, "~1": 10 }, [{ op: "test", path: "/~01", value: 10 }], { "/": 9, "~1": 10 }],
  [{ foo: 1 }, [{ op: "copy", from: "/foo", path: "/bar" }], { foo: 1, bar: 1 }],
  [{ foo: 1 }, [{ op: "replace", path: "", value: [1] }], [1]],
];

test("примеры RFC 6902", () => {
  for (const [doc, patch, expected] of RFC) assert.deepEqual(applyPatch(doc, patch), expected);
});

test("ошибки патча и атомарность", () => {
  const doc = { a: 1 };
  assert.throws(() => applyPatch(doc, [{ op: "replace", path: "/a", value: 2 }, { op: "remove", path: "/x" }]),
    (e) => e instanceof PatchError && e.index === 1);
  assert.deepEqual(doc, { a: 1 });
  const bad = [
    [{ op: "test", path: "/a", value: true }],
    [{ op: "add", path: "/a/b/c", value: 1 }],
    [{ op: "remove", path: "/01" }],
    [{ op: "jump", path: "/a" }],
    [{ op: "add", path: "x", value: 1 }],
  ];
  for (const p of bad) assert.throws(() => applyPatch(doc, p), PatchError);
  assert.throws(() => applyPatch([1], [{ op: "remove", path: "/01" }]), PatchError);
});

test("ключ __proto__ не ломает объект", () => {
  const out = applyPatch({}, [{ op: "add", path: "/__proto__", value: { polluted: true } }]);
  assert.equal(({}).polluted, undefined);
  assert.deepEqual(Object.keys(out), ["__proto__"]);
});

test("ошибка разбора JSON с позицией", () => {
  const r = parseJsonWithPosition('{"a": 1,\n "b": }');
  assert.equal(r.ok, false);
  assert.equal(r.line, 2);
  assert.ok(parseJsonWithPosition("[1]").ok);
});

// --- свойство на случайных документах (детерминированный ГПСЧ)
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; };
}
const pick = (r, arr) => arr[Math.floor(r() * arr.length)];
function randomJson(r, depth = 0) {
  const k = r();
  if (depth > 3 || k < 0.35) return pick(r, [null, true, false, 0, 1, 2, 3.5, -1, "a", "b", "", "ж"]);
  if (k < 0.65) return Array.from({ length: Math.floor(r() * 6) }, () => randomJson(r, depth + 1));
  const o = {};
  for (const key of ["a", "b", "c", "x/y", "m~n"]) if (r() < 0.5) o[key] = randomJson(r, depth + 1);
  return o;
}
function mutate(r, v, depth = 0) {
  if (r() < 0.2) return randomJson(r, depth);
  if (Array.isArray(v)) {
    const out = v.map((x) => (r() < 0.4 ? mutate(r, x, depth + 1) : x));
    if (r() < 0.5) out.splice(Math.floor(r() * (out.length + 1)), 0, randomJson(r, depth + 1));
    if (r() < 0.4 && out.length) out.splice(Math.floor(r() * out.length), 1);
    return out;
  }
  if (v && typeof v === "object") {
    const out = {};
    for (const [key, x] of Object.entries(v)) if (r() > 0.15) out[key] = r() < 0.4 ? mutate(r, x, depth + 1) : x;
    if (r() < 0.3) out.q = randomJson(r, depth + 1);
    return out;
  }
  return v;
}

test("свойство: applyPatch(a, makePatch(a, b)) == b (400 случаев)", () => {
  for (let seed = 1; seed <= 400; seed++) {
    const r = rng(seed);
    const a = randomJson(r);
    const b = mutate(r, a);
    assert.deepEqual(applyPatch(a, makePatch(a, b)), b, `seed ${seed}`);
    assert.deepEqual(applyPatch(a, makePatch(a, b, {}, true)), b, `seed ${seed} + tests`);
  }
});

test("свойство: массивы по ключу (200 случаев)", () => {
  const opts = makeOptions({ arrayKeys: ["id"] });
  for (let seed = 1; seed <= 200; seed++) {
    const r = rng(seed * 7919);
    const list = () => {
      const ids = [...Array(12).keys()].filter(() => r() < 0.5).sort(() => r() - 0.5);
      return ids.map((id) => ({ id, v: Math.floor(r() * 3) }));
    };
    const a = { items: list() };
    const b = { items: list() };
    assert.deepEqual(applyPatch(a, makePatch(a, b, opts)), b, `seed ${seed}`);
  }
});

test("сканер ошибок JSON", async () => {
  const { findJsonErrorOffset } = await import("../js/core.js");
  assert.equal(findJsonErrorOffset('{"a": [1, 2]}'), null);
  assert.equal(findJsonErrorOffset("[1,]"), 3);
  assert.equal(findJsonErrorOffset('{"a" 1}'), 5);
  assert.equal(findJsonErrorOffset("[1] x"), 4);
  assert.equal(findJsonErrorOffset('"abc'), 4);
});
