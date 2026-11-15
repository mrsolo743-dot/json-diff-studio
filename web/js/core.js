// json-diff-studio — JS-порт ядра (сравнение, JSON Patch, пути).
// Логика повторяет пакет json_diff_studio на Python; совпадение
// проверяется общими фикстурами из fixtures/cases.json.

export const LCS_LIMIT = 2_000_000;

// ------------------------------------------------------------ пути

const IDENT = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

export class KeyRef {
  constructor(index, key, value) {
    this.index = index;
    this.key = key;
    this.value = value;
  }
}

const dump = (v) => JSON.stringify(v);

export function formatPath(path) {
  let out = "$";
  for (const tok of path) {
    if (tok instanceof KeyRef) out += `[${tok.key}=${dump(tok.value)}]`;
    else if (typeof tok === "number") out += `[${tok}]`;
    else if (IDENT.test(tok)) out += "." + tok;
    else out += "[" + dump(tok) + "]";
  }
  return out;
}

export const escapePointer = (t) => String(t).replace(/~/g, "~0").replace(/\//g, "~1");

export function toPointer(path) {
  return path
    .map((tok) => "/" + (tok instanceof KeyRef ? String(tok.index) : escapePointer(tok)))
    .join("");
}

export function parsePointer(pointer) {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) throw new Error(`JSON Pointer должен начинаться с '/': ${pointer}`);
  return pointer.slice(1).split("/").map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
}

export class PatternError extends Error {}

const NAME = /^(\*|[A-Za-z_$][A-Za-z0-9_$]*)/;

export function parsePattern(text) {
  const s = text.trim();
  if (!s.startsWith("$")) throw new PatternError(`шаблон должен начинаться с '$': ${text}`);
  const segs = [];
  let i = 1;
  const n = s.length;
  const nameSeg = (name) => (name === "*" ? ["any"] : ["key", name]);
  while (i < n) {
    const c = s[i];
    if (s.startsWith("..", i)) {
      segs.push(["deep"]);
      i += 2;
      if (i < n && s[i] !== "." && s[i] !== "[") {
        const m = s.slice(i).match(NAME);
        if (!m) throw new PatternError(`ожидался ключ после '..' в ${text}`);
        segs.push(nameSeg(m[1]));
        i += m[1].length;
      }
    } else if (c === ".") {
      const m = s.slice(i + 1).match(NAME);
      if (!m) throw new PatternError(`ожидался ключ после '.' в ${text}`);
      segs.push(nameSeg(m[1]));
      i += 1 + m[1].length;
    } else if (c === "[") {
      const end = findBracketEnd(s, i, text);
      segs.push(parseBracket(s.slice(i + 1, end), text));
      i = end + 1;
    } else {
      throw new PatternError(`неожиданный символ '${c}' в шаблоне ${text}`);
    }
  }
  return segs;
}

function findBracketEnd(s, start, text) {
  let inStr = false;
  for (let i = start + 1; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (ch === "\\") { i++; continue; }
      if (ch === '"') inStr = false;
    } else if (ch === '"') inStr = true;
    else if (ch === "]") return i;
  }
  throw new PatternError(`незакрытая '[' в шаблоне ${text}`);
}

function parseBracket(raw, text) {
  const body = raw.trim();
  if (body === "*") return ["any"];
  if (/^\d+$/.test(body)) return ["index", Number(body)];
  if (body.startsWith('"')) {
    try { return ["key", JSON.parse(body)]; } catch { throw new PatternError(`плохая строка ${body} в ${text}`); }
  }
  const m = body.match(/^([A-Za-z_$][A-Za-z0-9_$]*)=(.+)$/s);
  if (m) {
    let value;
    try { value = JSON.parse(m[2]); } catch { value = m[2]; }
    return ["keyref", m[1], value];
  }
  throw new PatternError(`не понимаю сегмент [${body}] в ${text}`);
}

function segMatches(seg, tok) {
  switch (seg[0]) {
    case "any": return true;
    case "key": return typeof tok === "string" && tok === seg[1];
    case "index": return tok instanceof KeyRef ? tok.index === seg[1] : typeof tok === "number" && tok === seg[1];
    case "keyref": return tok instanceof KeyRef && tok.key === seg[1] && strictEqual(tok.value, seg[2]);
    default: return false;
  }
}

export function matchPattern(segs, path) {
  const rec = (si, pi) => {
    if (si === segs.length) return pi === path.length;
    const seg = segs[si];
    if (seg[0] === "deep") {
      for (let k = pi; k <= path.length; k++) if (rec(si + 1, k)) return true;
      return false;
    }
    if (pi === path.length) return false;
    return segMatches(seg, path[pi]) && rec(si + 1, pi + 1);
  };
  return rec(0, 0);
}

export class PathMatcher {
  constructor(patterns = []) {
    this.sources = [...patterns];
    this.compiled = patterns.map(parsePattern);
  }
  get size() { return this.compiled.length; }
  matches(path) { return this.compiled.some((c) => matchPattern(c, path)); }
}

// ------------------------------------------------------------ типы

export function typeName(v) {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  const t = typeof v;
  if (t === "boolean" || t === "number" || t === "string") return t;
  if (t === "object") return "object";
  throw new TypeError(`не JSON-значение: ${t}`);
}

const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

export function strictEqual(a, b) {
  const ta = typeName(a);
  if (ta !== typeName(b)) return false;
  if (ta === "array") return a.length === b.length && a.every((x, i) => strictEqual(x, b[i]));
  if (ta === "object") {
    const ka = Object.keys(a);
    if (ka.length !== Object.keys(b).length) return false;
    return ka.every((k) => has(b, k) && strictEqual(a[k], b[k]));
  }
  return a === b;
}

export function canonical(v) {
  const t = typeName(v);
  if (t === "array") return "[" + v.map(canonical).join(",") + "]";
  if (t === "object") {
    return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
  }
  return JSON.stringify(v);
}

const isScalar = (v) => v === null || typeof v !== "object";
const sortedKeys = (a, b) => [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

// ------------------------------------------------------------ настройки

export class ArrayKey {
  constructor(key, where = null) {
    this.key = key;
    this.where = where;
    this.segs = where ? parsePattern(where) : null;
  }
  static parse(spec) {
    const s = spec.trim();
    if (s.startsWith("$") && s.includes("=")) {
      const at = s.lastIndexOf("=");
      return new ArrayKey(s.slice(at + 1).trim(), s.slice(0, at).trim());
    }
    return new ArrayKey(s);
  }
  applies(path) { return this.segs === null || matchPattern(this.segs, path); }
}

export function makeOptions(data = {}) {
  const ignore = [...(data.ignore || [])];
  for (const k of data.ignoreKeys || []) ignore.push(IDENT.test(k) ? `$..${k}` : `$..[${JSON.stringify(k)}]`);
  return {
    arrayKeys: (data.arrayKeys || []).map((s) => (s instanceof ArrayKey ? s : ArrayKey.parse(s))),
    matcher: new PathMatcher(ignore),
    tolerance: Number(data.tolerance || 0),
    ignoreCase: Boolean(data.ignoreCase),
    ignoreOrder: Boolean(data.ignoreOrder),
  };
}

// ------------------------------------------------------------ выравнивание

export function lcsPairs(a, b) {
  const ha = a.map(canonical);
  const hb = b.map(canonical);
  const n = ha.length;
  const m = hb.length;
  let pre = 0;
  while (pre < n && pre < m && ha[pre] === hb[pre]) pre++;
  let suf = 0;
  while (suf < n - pre && suf < m - pre && ha[n - 1 - suf] === hb[m - 1 - suf]) suf++;
  const pairs = [];
  for (let k = 0; k < pre; k++) pairs.push([k, k]);
  const xa = ha.slice(pre, n - suf);
  const xb = hb.slice(pre, m - suf);
  const p = xa.length;
  const q = xb.length;
  if (p && q && p * q <= LCS_LIMIT) {
    const w = q + 1;
    const dp = new Uint32Array((p + 1) * w);
    for (let i = p - 1; i >= 0; i--) {
      for (let j = q - 1; j >= 0; j--) {
        if (xa[i] === xb[j]) dp[i * w + j] = dp[(i + 1) * w + j + 1] + 1;
        else {
          const down = dp[(i + 1) * w + j];
          const right = dp[i * w + j + 1];
          dp[i * w + j] = down >= right ? down : right;
        }
      }
    }
    let i = 0;
    let j = 0;
    while (i < p && j < q) {
      if (xa[i] === xb[j]) { pairs.push([pre + i, pre + j]); i++; j++; }
      else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) i++;
      else j++;
    }
  }
  for (let k = 0; k < suf; k++) pairs.push([n - suf + k, m - suf + k]);
  return pairs;
}

export function align(a, b) {
  const segs = [];
  let pi = 0;
  let pj = 0;
  const range = (from, to) => Array.from({ length: to - from }, (_, k) => from + k);
  for (const [i, j] of [...lcsPairs(a, b), [a.length, b.length]]) {
    if (i > pi || j > pj) segs.push(["gap", range(pi, i), range(pj, j)]);
    if (i < a.length && j < b.length) segs.push(["eq", i, j]);
    pi = i + 1;
    pj = j + 1;
  }
  return segs;
}

function keyOf(item, key) {
  if (typeName(item) !== "object" || !has(item, key) || !isScalar(item[key])) return null;
  return canonical(item[key]);
}

export function chooseArrayKey(a, b, path, rules) {
  if (!a.length && !b.length) return null;
  for (const rule of rules) {
    if (!rule.applies(path)) continue;
    let ok = true;
    for (const arr of [a, b]) {
      const seen = new Set();
      for (const item of arr) {
        const k = keyOf(item, rule.key);
        if (k === null || seen.has(k)) { ok = false; break; }
        seen.add(k);
      }
      if (!ok) break;
    }
    if (ok) return rule.key;
  }
  return null;
}

export function lisKeep(seq) {
  const tails = [];
  const tailsIdx = [];
  const prev = new Array(seq.length).fill(-1);
  seq.forEach((v, pos) => {
    let lo = 0;
    let hi = tails.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (tails[mid] < v) lo = mid + 1; else hi = mid;
    }
    if (lo === tails.length) { tails.push(v); tailsIdx.push(pos); }
    else { tails[lo] = v; tailsIdx[lo] = pos; }
    prev[pos] = lo ? tailsIdx[lo - 1] : -1;
  });
  const keep = new Set();
  let cur = tailsIdx.length ? tailsIdx[tailsIdx.length - 1] : -1;
  while (cur !== -1) { keep.add(cur); cur = prev[cur]; }
  return keep;
}

// ------------------------------------------------------------ сравнение

function mkChange(type, path, extra) {
  return { type, path, ...extra };
}

export function diff(a, b, options) {
  const opt = options && options.matcher ? options : makeOptions(options || {});
  const changes = [];
  const ignored = (path) => opt.matcher.size > 0 && opt.matcher.matches(path);
  const emit = (c) => { if (!ignored(c.path)) changes.push(c); };
  const scalarEqual = (x, y) => {
    const t = typeName(x);
    if (t === "number" && opt.tolerance) return Math.abs(x - y) <= opt.tolerance;
    if (t === "string" && opt.ignoreCase) return x.toLowerCase() === y.toLowerCase();
    return x === y;
  };

  const walk = (x, y, path) => {
    if (ignored(path)) return;
    const tx = typeName(x);
    const ty = typeName(y);
    if (tx !== ty) emit(mkChange("changed", path, { old: x, new: y }));
    else if (tx === "object") {
      for (const k of sortedKeys(x, y)) {
        const child = [...path, k];
        if (!has(y, k)) emit(mkChange("removed", child, { old: x[k] }));
        else if (!has(x, k)) emit(mkChange("added", child, { new: y[k] }));
        else walk(x[k], y[k], child);
      }
    } else if (tx === "array") walkArray(x, y, path);
    else if (!scalarEqual(x, y)) emit(mkChange("changed", path, { old: x, new: y }));
  };

  const walkArray = (x, y, path) => {
    const key = chooseArrayKey(x, y, path, opt.arrayKeys);
    if (key !== null) return walkKeyed(x, y, path, key);
    if (opt.ignoreOrder) return walkUnordered(x, y, path);
    for (const seg of align(x, y)) {
      if (seg[0] === "eq") continue;
      const [, ia, jb] = seg;
      const common = Math.min(ia.length, jb.length);
      for (let k = 0; k < common; k++) walk(x[ia[k]], y[jb[k]], [...path, jb[k]]);
      for (const i of ia.slice(common)) emit(mkChange("removed", [...path, i], { old: x[i] }));
      for (const j of jb.slice(common)) emit(mkChange("added", [...path, j], { new: y[j] }));
    }
  };

  const walkUnordered = (x, y, path) => {
    const count = (arr) => {
      const m = new Map();
      for (const v of arr) { const c = canonical(v); m.set(c, (m.get(c) || 0) + 1); }
      return m;
    };
    const cb = count(y);
    const ca = count(x);
    x.forEach((v, i) => {
      const c = canonical(v);
      if ((cb.get(c) || 0) > 0) cb.set(c, cb.get(c) - 1);
      else emit(mkChange("removed", [...path, i], { old: v }));
    });
    y.forEach((v, j) => {
      const c = canonical(v);
      if ((ca.get(c) || 0) > 0) ca.set(c, ca.get(c) - 1);
      else emit(mkChange("added", [...path, j], { new: v }));
    });
  };

  const walkKeyed = (x, y, path, key) => {
    const aIdx = new Map(x.map((v, i) => [keyOf(v, key), i]));
    const bIdx = new Map(y.map((v, j) => [keyOf(v, key), j]));
    x.forEach((v, i) => {
      if (!bIdx.has(keyOf(v, key))) emit(mkChange("removed", [...path, new KeyRef(i, key, v[key])], { old: v }));
    });
    const matchedB = [];
    y.forEach((v, j) => { if (aIdx.has(keyOf(v, key))) matchedB.push(j); });
    const order = matchedB.map((j) => aIdx.get(keyOf(y[j], key)));
    const keep = lisKeep(order);
    const moved = new Set(matchedB.filter((_, p) => !keep.has(p)));
    y.forEach((v, j) => {
      const k = keyOf(v, key);
      const ref = [...path, new KeyRef(j, key, v[key])];
      if (!aIdx.has(k)) { emit(mkChange("added", ref, { new: v })); return; }
      const i = aIdx.get(k);
      if (moved.has(j)) emit(mkChange("moved", ref, { old: i, new: j }));
      walk(x[i], v, ref);
    });
  };

  walk(a, b, []);
  return changes;
}

export function changeToDict(c) {
  const d = { type: c.type, path: formatPath(c.path) };
  if (has(c, "old")) d.old = c.old;
  if (has(c, "new")) d.new = c.new;
  return d;
}

export function summarize(changes) {
  const s = { added: 0, removed: 0, changed: 0, moved: 0 };
  for (const c of changes) s[c.type]++;
  s.total = changes.length;
  return s;
}

// ------------------------------------------------------------ JSON Patch: построение

export function makePatch(a, b, options, withTests = false) {
  const opt = options && options.matcher ? options : makeOptions(options || {});
  const ops = [];
  const ignored = (disp) => opt.matcher.size > 0 && opt.matcher.matches(disp);
  const ptr = (parts) => parts.map((p) => "/" + escapePointer(p)).join("");
  const test = (p, value) => { if (withTests) ops.push({ op: "test", path: p, value: clone(value) }); };

  const walk = (x, y, disp, parts) => {
    if (ignored(disp) || strictEqual(x, y)) return;
    const tx = typeName(x);
    const ty = typeName(y);
    const p = ptr(parts);
    if (tx !== ty || (tx !== "object" && tx !== "array")) {
      test(p, x);
      ops.push({ op: "replace", path: p, value: clone(y) });
    } else if (tx === "object") {
      for (const k of sortedKeys(x, y)) {
        const cd = [...disp, k];
        const cp = [...parts, k];
        if (has(x, k) && has(y, k)) walk(x[k], y[k], cd, cp);
        else if (ignored(cd)) continue;
        else if (has(x, k)) { test(ptr(cp), x[k]); ops.push({ op: "remove", path: ptr(cp) }); }
        else ops.push({ op: "add", path: ptr(cp), value: clone(y[k]) });
      }
    } else {
      const key = chooseArrayKey(x, y, disp, opt.arrayKeys);
      if (key === null) walkLcs(x, y, disp, parts);
      else walkKeyed(x, y, disp, parts, key);
    }
  };

  const walkLcs = (x, y, disp, parts) => {
    let idx = 0;
    for (const seg of align(x, y)) {
      if (seg[0] === "eq") { idx++; continue; }
      const [, ia, jb] = seg;
      const common = Math.min(ia.length, jb.length);
      for (let k = 0; k < common; k++) {
        walk(x[ia[k]], y[jb[k]], [...disp, jb[k]], [...parts, String(idx)]);
        idx++;
      }
      for (const i of ia.slice(common)) {
        if (ignored([...disp, i])) { idx++; continue; }
        const p = ptr([...parts, String(idx)]);
        test(p, x[i]);
        ops.push({ op: "remove", path: p });
      }
      for (const j of jb.slice(common)) {
        if (ignored([...disp, j])) continue;
        ops.push({ op: "add", path: ptr([...parts, String(idx)]), value: clone(y[j]) });
        idx++;
      }
    }
  };

  const walkKeyed = (x, y, disp, parts, key) => {
    const aBy = new Map(x.map((v) => [keyOf(v, key), v]));
    const bKeys = new Set(y.map((v) => keyOf(v, key)));
    const working = x.map((v) => keyOf(v, key));
    for (let i = x.length - 1; i >= 0; i--) {
      if (bKeys.has(working[i]) || ignored([...disp, new KeyRef(i, key, x[i][key])])) continue;
      const p = ptr([...parts, String(i)]);
      test(p, x[i]);
      ops.push({ op: "remove", path: p });
      working.splice(i, 1);
    }
    let pos = 0;
    y.forEach((v, j) => {
      const k = keyOf(v, key);
      const ref = [...disp, new KeyRef(j, key, v[key])];
      if (!aBy.has(k)) {
        if (ignored(ref)) return;
        ops.push({ op: "add", path: ptr([...parts, String(pos)]), value: clone(v) });
        working.splice(pos, 0, k);
      } else {
        const cur = working.indexOf(k);
        if (cur !== pos) {
          ops.push({ op: "move", from: ptr([...parts, String(cur)]), path: ptr([...parts, String(pos)]) });
          working.splice(pos, 0, working.splice(cur, 1)[0]);
        }
        walk(aBy.get(k), v, ref, [...parts, String(pos)]);
      }
      pos++;
    });
  };

  walk(a, b, [], []);
  return ops;
}

// ------------------------------------------------------------ JSON Patch: применение

export class PatchError extends Error {
  constructor(message, index = null) {
    super(index === null ? message : `операция #${index}: ${message}`);
    this.index = index;
  }
}

function arrayIndex(tok, length, pointer, index, allowEnd) {
  if (tok === "-" && allowEnd) return length;
  if (!/^\d+$/.test(tok) || (tok.length > 1 && tok[0] === "0")) {
    throw new PatchError(`плохой индекс массива '${tok}' в '${pointer}'`, index);
  }
  const i = Number(tok);
  const limit = allowEnd ? length : length - 1;
  if (i > limit) throw new PatchError(`индекс ${i} вне массива длины ${length} ('${pointer}')`, index);
  return i;
}

function child(node, tok, pointer, index) {
  const t = typeName(node);
  if (t === "object") {
    if (!has(node, tok)) throw new PatchError(`нет ключа '${tok}' ('${pointer}')`, index);
    return node[tok];
  }
  if (t === "array") return node[arrayIndex(tok, node.length, pointer, index, false)];
  throw new PatchError(`путь '${pointer}' проходит через скаляр`, index);
}

function getAt(doc, pointer, index) {
  let node = doc;
  for (const tok of parsePointer(pointer)) node = child(node, tok, pointer, index);
  return node;
}

function resolveParent(doc, pointer, index) {
  const tokens = parsePointer(pointer);
  if (!tokens.length) return [null, null, tokens];
  let node = doc;
  for (const tok of tokens.slice(0, -1)) node = child(node, tok, pointer, index);
  return [node, tokens[tokens.length - 1], tokens];
}

function addAt(doc, pointer, value, index) {
  const [parent, last, tokens] = resolveParent(doc, pointer, index);
  if (!tokens.length) return value;
  const t = typeName(parent);
  if (t === "object") Object.defineProperty(parent, last, { value, writable: true, enumerable: true, configurable: true });
  else if (t === "array") parent.splice(arrayIndex(last, parent.length, pointer, index, true), 0, value);
  else throw new PatchError(`родитель '${pointer}' не контейнер`, index);
  return doc;
}

function removeAt(doc, pointer, index) {
  const [parent, last, tokens] = resolveParent(doc, pointer, index);
  if (!tokens.length) throw new PatchError("нельзя удалить корень документа", index);
  const t = typeName(parent);
  if (t === "object") {
    if (!has(parent, last)) throw new PatchError(`нет ключа '${last}' ('${pointer}')`, index);
    const v = parent[last];
    delete parent[last];
    return v;
  }
  if (t === "array") return parent.splice(arrayIndex(last, parent.length, pointer, index, false), 1)[0];
  throw new PatchError(`родитель '${pointer}' не контейнер`, index);
}

function requireField(op, field, index) {
  if (!has(op, field)) throw new PatchError(`нет обязательного поля '${field}'`, index);
  return op[field];
}

function pointerField(op, field, index) {
  const v = requireField(op, field, index);
  if (typeof v !== "string") throw new PatchError(`поле '${field}' должно быть строкой`, index);
  try { parsePointer(v); } catch (e) { throw new PatchError(e.message, index); }
  return v;
}

export function applyPatch(doc, patch) {
  if (!Array.isArray(patch)) throw new PatchError("патч должен быть JSON-массивом операций");
  let result = clone(doc);
  patch.forEach((op, index) => {
    if (typeName(op) !== "object") throw new PatchError("операция должна быть объектом", index);
    const name = requireField(op, "op", index);
    const path = pointerField(op, "path", index);
    if (name === "add") result = addAt(result, path, clone(requireField(op, "value", index)), index);
    else if (name === "remove") removeAt(result, path, index);
    else if (name === "replace") {
      const value = clone(requireField(op, "value", index));
      if (path === "") result = value;
      else {
        getAt(result, path, index);
        removeAt(result, path, index);
        result = addAt(result, path, value, index);
      }
    } else if (name === "move" || name === "copy") {
      const src = pointerField(op, "from", index);
      let value;
      if (name === "move") {
        if (path !== src && path.startsWith(src + "/")) throw new PatchError(`нельзя переместить '${src}' внутрь себя`, index);
        if (path === src) { getAt(result, src, index); return; }
        value = removeAt(result, src, index);
      } else value = clone(getAt(result, src, index));
      result = addAt(result, path, value, index);
    } else if (name === "test") {
      const expected = requireField(op, "value", index);
      if (!strictEqual(getAt(result, path, index), expected)) throw new PatchError(`test не прошёл для '${path}'`, index);
    } else throw new PatchError(`неизвестная операция '${name}'`, index);
  });
  return result;
}

// ------------------------------------------------------------ разбор JSON с позицией ошибки

// Сообщения JSON.parse в разных браузерах разные и не всегда содержат позицию,
// поэтому при ошибке документ проходит через маленький сканер, который
// находит смещение первой синтаксической ошибки.
export function findJsonErrorOffset(text) {
  let i = 0;
  const ws = () => { while (i < text.length && " \t\n\r".includes(text[i])) i++; };
  const fail = () => { throw i; };
  const lit = (word) => { if (text.startsWith(word, i)) i += word.length; else fail(); };
  const str = () => {
    i++;
    while (i < text.length) {
      const c = text[i];
      if (c === '"') { i++; return; }
      if (c === "\\") {
        const e = text[i + 1];
        if (e === "u") { if (!/^[0-9a-fA-F]{4}$/.test(text.slice(i + 2, i + 6))) { i += 1; fail(); } i += 6; }
        else if (e !== undefined && '"\\/bfnrt'.includes(e)) i += 2;
        else { i += 1; fail(); }
      } else if (c < " ") fail();
      else i++;
    }
    fail();
  };
  const num = () => {
    const m = /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?/.exec(text.slice(i));
    if (!m) fail();
    i += m[0].length;
  };
  const value = () => {
    ws();
    const c = text[i];
    if (c === "{") {
      i++; ws();
      if (text[i] === "}") { i++; return; }
      for (;;) {
        ws(); if (text[i] !== '"') fail(); str(); ws();
        if (text[i] !== ":") fail(); i++; value(); ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "}") { i++; return; }
        fail();
      }
    } else if (c === "[") {
      i++; ws();
      if (text[i] === "]") { i++; return; }
      for (;;) {
        value(); ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "]") { i++; return; }
        fail();
      }
    } else if (c === '"') str();
    else if (c === "t") lit("true");
    else if (c === "f") lit("false");
    else if (c === "n") lit("null");
    else num();
  };
  try {
    value(); ws();
    return i < text.length ? i : null;
  } catch (pos) {
    if (typeof pos === "number") return pos;
    throw pos;
  }
}

export function parseJsonWithPosition(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (e) {
    let pos = findJsonErrorOffset(text);
    if (pos === null) pos = text.length;
    const before = text.slice(0, pos).split("\n");
    const line = before.length;
    const col = before[before.length - 1].length + 1;
    return { ok: false, error: `${e.message}`, line, col, offset: pos };
  }
}
