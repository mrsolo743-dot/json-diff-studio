"""JSON Patch (RFC 6902): построение патча по двум документам и его применение."""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence

from .diff import (Options, _key_of, align, choose_array_key, strict_equal,
                   type_name)
from .paths import KeyRef, PathMatcher, parse_pointer, _escape_pointer

Op = Dict[str, Any]


class PatchError(ValueError):
    """Ошибка применения патча; ``index`` — номер операции (с нуля)."""

    def __init__(self, message: str, index: Optional[int] = None):
        self.index = index
        prefix = f"операция #{index}: " if index is not None else ""
        super().__init__(prefix + message)


# ---------------------------------------------------------------- построение

class _Builder:
    def __init__(self, options: Options, with_tests: bool):
        self.rules = options.array_keys
        self.matcher: PathMatcher = options.matcher
        self.with_tests = with_tests
        self.ops: List[Op] = []

    def ignored(self, disp) -> bool:
        return bool(self.matcher) and self.matcher.matches(disp)

    @staticmethod
    def ptr(parts: Sequence[str]) -> str:
        return "".join("/" + _escape_pointer(str(p)) for p in parts)

    def test(self, ptr: str, value: Any) -> None:
        if self.with_tests:
            self.ops.append({"op": "test", "path": ptr, "value": copy.deepcopy(value)})

    def walk(self, a: Any, b: Any, disp: tuple, ptr: List[str]) -> None:
        if self.ignored(disp) or strict_equal(a, b):
            return
        ta, tb = type_name(a), type_name(b)
        p = self.ptr(ptr)
        if ta != tb or ta not in ("object", "array"):
            self.test(p, a)
            self.ops.append({"op": "replace", "path": p, "value": copy.deepcopy(b)})
        elif ta == "object":
            for k in sorted(set(a) | set(b)):
                child_disp, child_ptr = disp + (k,), ptr + [k]
                if k in a and k in b:
                    self.walk(a[k], b[k], child_disp, child_ptr)
                elif self.ignored(child_disp):
                    continue
                elif k in a:
                    self.test(self.ptr(child_ptr), a[k])
                    self.ops.append({"op": "remove", "path": self.ptr(child_ptr)})
                else:
                    self.ops.append({"op": "add", "path": self.ptr(child_ptr),
                                     "value": copy.deepcopy(b[k])})
        else:
            key = choose_array_key(a, b, disp, self.rules)
            if key is None:
                self.walk_lcs(a, b, disp, ptr)
            else:
                self.walk_keyed(a, b, disp, ptr, key)

    def walk_lcs(self, a: list, b: list, disp: tuple, ptr: List[str]) -> None:
        idx = 0  # индекс в «рабочем» массиве, который постепенно становится b
        for seg in align(a, b):
            if seg[0] == "eq":
                idx += 1
                continue
            ia, jb = seg[1], seg[2]
            common = min(len(ia), len(jb))
            for i, j in zip(ia[:common], jb[:common]):
                self.walk(a[i], b[j], disp + (j,), ptr + [str(idx)])
                idx += 1
            for i in ia[common:]:
                if self.ignored(disp + (i,)):
                    idx += 1
                    continue
                p = self.ptr(ptr + [str(idx)])
                self.test(p, a[i])
                self.ops.append({"op": "remove", "path": p})
            for j in jb[common:]:
                if self.ignored(disp + (j,)):
                    continue
                self.ops.append({"op": "add", "path": self.ptr(ptr + [str(idx)]),
                                 "value": copy.deepcopy(b[j])})
                idx += 1

    def walk_keyed(self, a: list, b: list, disp: tuple, ptr: List[str], key: str) -> None:
        a_by = {_key_of(x, key): x for x in a}
        b_keys = {_key_of(y, key) for y in b}
        working = [_key_of(x, key) for x in a]
        # 1. удаления (с конца, чтобы индексы не сдвигались)
        for i in range(len(a) - 1, -1, -1):
            k = working[i]
            if k in b_keys or self.ignored(disp + (KeyRef(i, key, a[i][key]),)):
                continue
            p = self.ptr(ptr + [str(i)])
            self.test(p, a[i])
            self.ops.append({"op": "remove", "path": p})
            del working[i]
        # 2. вставки, перемещения и вложенные изменения в порядке b
        pos = 0
        for j, y in enumerate(b):
            k = _key_of(y, key)
            ref = disp + (KeyRef(j, key, y[key]),)
            if k not in a_by:
                if self.ignored(ref):
                    continue
                self.ops.append({"op": "add", "path": self.ptr(ptr + [str(pos)]),
                                 "value": copy.deepcopy(y)})
                working.insert(pos, k)
            else:
                cur = working.index(k)
                if cur != pos:
                    self.ops.append({"op": "move", "from": self.ptr(ptr + [str(cur)]),
                                     "path": self.ptr(ptr + [str(pos)])})
                    working.insert(pos, working.pop(cur))
                self.walk(a_by[k], y, ref, ptr + [str(pos)])
            pos += 1


def make_patch(a: Any, b: Any, options: Optional[Options] = None,
               with_tests: bool = False) -> List[Op]:
    """Патч RFC 6902, превращающий ``a`` в ``b``.

    Учитываются только ``array_keys`` и ``ignore``: допуск для чисел, регистр
    строк и порядок массивов на патч не влияют — он всегда точный.
    """
    builder = _Builder(options or Options(), with_tests)
    builder.walk(a, b, (), [])
    return builder.ops


# ---------------------------------------------------------------- применение

_MISSING = object()


def _resolve_parent(doc: Any, pointer: str, index: int):
    tokens = parse_pointer(pointer)
    if not tokens:
        return None, None, tokens
    node = doc
    for depth, tok in enumerate(tokens[:-1]):
        node = _child(node, tok, pointer, index)
    return node, tokens[-1], tokens


def _array_index(tok: str, length: int, pointer: str, index: int, allow_end: bool) -> int:
    if tok == "-" and allow_end:
        return length
    if not tok.isdigit() or (len(tok) > 1 and tok[0] == "0"):
        raise PatchError(f"плохой индекс массива {tok!r} в {pointer!r}", index)
    i = int(tok)
    limit = length if allow_end else length - 1
    if i > limit:
        raise PatchError(f"индекс {i} вне массива длины {length} ({pointer!r})", index)
    return i


def _child(node: Any, tok: str, pointer: str, index: int) -> Any:
    if isinstance(node, dict):
        if tok not in node:
            raise PatchError(f"нет ключа {tok!r} ({pointer!r})", index)
        return node[tok]
    if isinstance(node, list):
        return node[_array_index(tok, len(node), pointer, index, allow_end=False)]
    raise PatchError(f"путь {pointer!r} проходит через скаляр", index)


def _get(doc: Any, pointer: str, index: int) -> Any:
    node = doc
    for tok in parse_pointer(pointer):
        node = _child(node, tok, pointer, index)
    return node


def _require(op: Op, field: str, index: int) -> Any:
    if field not in op:
        raise PatchError(f"нет обязательного поля {field!r}", index)
    return op[field]


def _pointer(op: Op, field: str, index: int) -> str:
    value = _require(op, field, index)
    if not isinstance(value, str):
        raise PatchError(f"поле {field!r} должно быть строкой", index)
    try:
        parse_pointer(value)
    except ValueError as exc:
        raise PatchError(str(exc), index) from exc
    return value


def _add(doc: Any, pointer: str, value: Any, index: int) -> Any:
    parent, last, tokens = _resolve_parent(doc, pointer, index)
    if not tokens:
        return value
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list):
        parent.insert(_array_index(last, len(parent), pointer, index, allow_end=True), value)
    else:
        raise PatchError(f"родитель {pointer!r} не контейнер", index)
    return doc


def _remove(doc: Any, pointer: str, index: int):
    parent, last, tokens = _resolve_parent(doc, pointer, index)
    if not tokens:
        raise PatchError("нельзя удалить корень документа", index)
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError(f"нет ключа {last!r} ({pointer!r})", index)
        return doc, parent.pop(last)
    if isinstance(parent, list):
        return doc, parent.pop(_array_index(last, len(parent), pointer, index, allow_end=False))
    raise PatchError(f"родитель {pointer!r} не контейнер", index)


def apply_patch(doc: Any, patch: Sequence[Op]) -> Any:
    """Применяет патч к копии документа. Атомарно: при ошибке исходник не меняется."""
    if not isinstance(patch, list):
        raise PatchError("патч должен быть JSON-массивом операций")
    result = copy.deepcopy(doc)
    for index, op in enumerate(patch):
        if not isinstance(op, dict):
            raise PatchError("операция должна быть объектом", index)
        name = _require(op, "op", index)
        path = _pointer(op, "path", index)
        if name == "add":
            result = _add(result, path, copy.deepcopy(_require(op, "value", index)), index)
        elif name == "remove":
            result, _ = _remove(result, path, index)
        elif name == "replace":
            value = copy.deepcopy(_require(op, "value", index))
            if path == "":
                result = value
            else:
                _get(result, path, index)  # цель обязана существовать
                result, _ = _remove(result, path, index)
                result = _add(result, path, value, index)
        elif name in ("move", "copy"):
            src = _pointer(op, "from", index)
            if name == "move":
                if path != src and path.startswith(src + "/"):
                    raise PatchError(f"нельзя переместить {src!r} внутрь себя", index)
                if path == src:
                    _get(result, src, index)
                    continue
                result, value = _remove(result, src, index)
            else:
                value = copy.deepcopy(_get(result, src, index))
            result = _add(result, path, value, index)
        elif name == "test":
            expected = _require(op, "value", index)
            actual = _get(result, path, index)
            if not strict_equal(actual, expected):
                raise PatchError(f"test не прошёл для {path!r}", index)
        else:
            raise PatchError(f"неизвестная операция {name!r}", index)
    return result
