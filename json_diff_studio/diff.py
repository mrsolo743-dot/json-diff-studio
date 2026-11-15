"""Ядро структурного сравнения двух JSON-документов."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .paths import KeyRef, Path, PathMatcher, format_path, parse_pattern, to_pointer

MISSING = object()

# Если после отсечения общих начала и конца массивов произведение длин
# больше этого порога, LCS не считается — элементы сравниваются по позициям.
LCS_LIMIT = 2_000_000


# ---------------------------------------------------------------- типы

def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"не JSON-значение: {type(value).__name__}")


def strict_equal(a: Any, b: Any) -> bool:
    """Точное равенство по правилам JSON (``true`` ≠ ``1``, ``1`` == ``1.0``)."""
    ta, tb = type_name(a), type_name(b)
    if ta != tb:
        return False
    if ta == "array":
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b))
    if ta == "object":
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    return a == b


def _normalize(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


def canonical(value: Any) -> str:
    """Каноническая строка значения — для хеширования при выравнивании."""
    return json.dumps(_normalize(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def is_scalar(value: Any) -> bool:
    return not isinstance(value, (list, dict))


# ---------------------------------------------------------------- настройки

@dataclass
class ArrayKey:
    """Правило «сопоставлять элементы массива по ключу» (опционально — по шаблону пути)."""

    key: str
    where: Optional[str] = None  # шаблон пути массива; None — любой массив

    def __post_init__(self) -> None:
        self._segs = parse_pattern(self.where) if self.where else None

    @classmethod
    def parse(cls, spec: str) -> "ArrayKey":
        """``id`` или ``$.users=id``."""
        if "=" in spec and spec.strip().startswith("$"):
            where, key = spec.rsplit("=", 1)
            return cls(key=key.strip(), where=where.strip())
        return cls(key=spec.strip())

    def applies(self, path: Sequence[Any]) -> bool:
        from .paths import match_pattern
        return self._segs is None or match_pattern(self._segs, path)


@dataclass
class Options:
    array_keys: List[ArrayKey] = field(default_factory=list)
    ignore: List[str] = field(default_factory=list)
    tolerance: float = 0.0
    ignore_case: bool = False
    ignore_order: bool = False

    def __post_init__(self) -> None:
        self.matcher = PathMatcher(self.ignore)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Options":
        """Настройки из словаря (формат общих фикстур Python/JS)."""
        data = data or {}
        keys = [ArrayKey.parse(s) for s in data.get("arrayKeys", [])]
        ignore = list(data.get("ignore", []))
        ignore += [f"$..{k}" if _is_ident(k) else f'$..["{k}"]'
                   for k in data.get("ignoreKeys", [])]
        return cls(array_keys=keys, ignore=ignore,
                   tolerance=float(data.get("tolerance", 0) or 0),
                   ignore_case=bool(data.get("ignoreCase", False)),
                   ignore_order=bool(data.get("ignoreOrder", False)))


def _is_ident(text: str) -> bool:
    import re
    return re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", text) is not None


# ---------------------------------------------------------------- изменения

@dataclass
class Change:
    type: str            # added | removed | changed | moved
    path: Path
    old: Any = MISSING
    new: Any = MISSING

    @property
    def path_str(self) -> str:
        return format_path(self.path)

    @property
    def pointer(self) -> str:
        return to_pointer(self.path)

    @property
    def type_changed(self) -> bool:
        return (self.type == "changed" and self.old is not MISSING
                and self.new is not MISSING and type_name(self.old) != type_name(self.new))

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type, "path": self.path_str}
        if self.old is not MISSING:
            d["old"] = self.old
        if self.new is not MISSING:
            d["new"] = self.new
        return d


# ---------------------------------------------------------------- выравнивание массивов

def lcs_pairs(a: Sequence[Any], b: Sequence[Any]) -> List[Tuple[int, int]]:
    """Пары индексов (i, j) наибольшей общей подпоследовательности по точному равенству."""
    ha = [canonical(x) for x in a]
    hb = [canonical(x) for x in b]
    n, m = len(ha), len(hb)
    pre = 0
    while pre < n and pre < m and ha[pre] == hb[pre]:
        pre += 1
    suf = 0
    while suf < n - pre and suf < m - pre and ha[n - 1 - suf] == hb[m - 1 - suf]:
        suf += 1
    pairs = [(k, k) for k in range(pre)]
    xa, xb = ha[pre:n - suf], hb[pre:m - suf]
    p, q = len(xa), len(xb)
    if p and q and p * q <= LCS_LIMIT:
        # dp[i][j] — длина LCS суффиксов xa[i:], xb[j:]
        dp = [[0] * (q + 1) for _ in range(p + 1)]
        for i in range(p - 1, -1, -1):
            row, nxt = dp[i], dp[i + 1]
            ai = xa[i]
            for j in range(q - 1, -1, -1):
                if ai == xb[j]:
                    row[j] = nxt[j + 1] + 1
                else:
                    row[j] = nxt[j] if nxt[j] >= row[j + 1] else row[j + 1]
        i = j = 0
        while i < p and j < q:
            if xa[i] == xb[j]:
                pairs.append((pre + i, pre + j))
                i += 1
                j += 1
            elif dp[i + 1][j] >= dp[i][j + 1]:
                i += 1
            else:
                j += 1
    pairs += [(n - suf + k, m - suf + k) for k in range(suf)]
    return pairs


def align(a: Sequence[Any], b: Sequence[Any]) -> Iterator[tuple]:
    """Сегменты выравнивания: ``("eq", i, j)`` и ``("gap", [i…], [j…])``."""
    pi = pj = 0
    for i, j in lcs_pairs(a, b) + [(len(a), len(b))]:
        if i > pi or j > pj:
            yield ("gap", list(range(pi, i)), list(range(pj, j)))
        if i < len(a) and j < len(b):
            yield ("eq", i, j)
        pi, pj = i + 1, j + 1


def _key_of(item: Any, key: str) -> Optional[str]:
    if not isinstance(item, dict) or key not in item or not is_scalar(item[key]):
        return None
    return canonical(item[key])


def choose_array_key(a: list, b: list, path: Sequence[Any],
                     rules: Sequence[ArrayKey]) -> Optional[str]:
    """Ключ для сопоставления элементов массива или None (если правило не подходит)."""
    if not a and not b:
        return None
    for rule in rules:
        if not rule.applies(path):
            continue
        ok = True
        for arr in (a, b):
            seen = set()
            for item in arr:
                k = _key_of(item, rule.key)
                if k is None or k in seen:
                    ok = False
                    break
                seen.add(k)
            if not ok:
                break
        if ok:
            return rule.key
    return None


def lis_keep(seq: Sequence[int]) -> set:
    """Позиции seq, входящие в наибольшую возрастающую подпоследовательность."""
    import bisect
    tails: List[int] = []
    tails_idx: List[int] = []
    prev = [-1] * len(seq)
    for pos, v in enumerate(seq):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v)
            tails_idx.append(pos)
        else:
            tails[k] = v
            tails_idx[k] = pos
        prev[pos] = tails_idx[k - 1] if k else -1
    keep = set()
    cur = tails_idx[-1] if tails_idx else -1
    while cur != -1:
        keep.add(cur)
        cur = prev[cur]
    return keep


# ---------------------------------------------------------------- сравнение

class Differ:
    def __init__(self, options: Optional[Options] = None):
        self.opt = options or Options()
        self.changes: List[Change] = []

    def run(self, a: Any, b: Any) -> List[Change]:
        self.changes = []
        self._walk(a, b, ())
        return self.changes

    # -- helpers
    def _ignored(self, path: Path) -> bool:
        return bool(self.opt.matcher) and self.opt.matcher.matches(path)

    def _emit(self, change: Change) -> None:
        if not self._ignored(change.path):
            self.changes.append(change)

    def _scalar_equal(self, a: Any, b: Any) -> bool:
        t = type_name(a)
        if t == "number" and self.opt.tolerance:
            return abs(a - b) <= self.opt.tolerance
        if t == "string" and self.opt.ignore_case:
            return a.lower() == b.lower()
        return a == b

    # -- walk
    def _walk(self, a: Any, b: Any, path: Path) -> None:
        if self._ignored(path):
            return
        ta, tb = type_name(a), type_name(b)
        if ta != tb:
            self._emit(Change("changed", path, a, b))
        elif ta == "object":
            for k in sorted(set(a) | set(b)):
                child = path + (k,)
                if k not in b:
                    self._emit(Change("removed", child, old=a[k]))
                elif k not in a:
                    self._emit(Change("added", child, new=b[k]))
                else:
                    self._walk(a[k], b[k], child)
        elif ta == "array":
            self._walk_array(a, b, path)
        elif not self._scalar_equal(a, b):
            self._emit(Change("changed", path, a, b))

    def _walk_array(self, a: list, b: list, path: Path) -> None:
        key = choose_array_key(a, b, path, self.opt.array_keys)
        if key is not None:
            self._walk_keyed(a, b, path, key)
        elif self.opt.ignore_order:
            self._walk_unordered(a, b, path)
        else:
            for seg in align(a, b):
                if seg[0] == "eq":
                    continue
                ia, jb = seg[1], seg[2]
                common = min(len(ia), len(jb))
                for i, j in zip(ia[:common], jb[:common]):
                    self._walk(a[i], b[j], path + (j,))
                for i in ia[common:]:
                    self._emit(Change("removed", path + (i,), old=a[i]))
                for j in jb[common:]:
                    self._emit(Change("added", path + (j,), new=b[j]))

    def _walk_unordered(self, a: list, b: list, path: Path) -> None:
        cb = Counter(canonical(x) for x in b)
        ca = Counter(canonical(x) for x in a)
        for i, x in enumerate(a):
            c = canonical(x)
            if cb[c] > 0:
                cb[c] -= 1
            else:
                self._emit(Change("removed", path + (i,), old=x))
        for j, x in enumerate(b):
            c = canonical(x)
            if ca[c] > 0:
                ca[c] -= 1
            else:
                self._emit(Change("added", path + (j,), new=x))

    def _walk_keyed(self, a: list, b: list, path: Path, key: str) -> None:
        a_idx = {_key_of(x, key): i for i, x in enumerate(a)}
        b_idx = {_key_of(x, key): j for j, x in enumerate(b)}
        for i, x in enumerate(a):
            if _key_of(x, key) not in b_idx:
                self._emit(Change("removed", path + (KeyRef(i, key, x[key]),), old=x))
        matched_b = [j for j, y in enumerate(b) if _key_of(y, key) in a_idx]
        order = [a_idx[_key_of(b[j], key)] for j in matched_b]
        keep = lis_keep(order)
        moved = {matched_b[p] for p in range(len(matched_b)) if p not in keep}
        for j, y in enumerate(b):
            k = _key_of(y, key)
            ref = path + (KeyRef(j, key, y[key]),)
            if k not in a_idx:
                self._emit(Change("added", ref, new=y))
                continue
            i = a_idx[k]
            if j in moved:
                self._emit(Change("moved", ref, old=i, new=j))
            self._walk(a[i], y, ref)


def diff(a: Any, b: Any, options: Optional[Options] = None) -> List[Change]:
    """Список изменений, превращающих документ ``a`` в документ ``b``."""
    return Differ(options).run(a, b)


def summarize(changes: Sequence[Change]) -> Dict[str, int]:
    counts = {"added": 0, "removed": 0, "changed": 0, "moved": 0}
    for c in changes:
        counts[c.type] += 1
    counts["total"] = len(changes)
    return counts
