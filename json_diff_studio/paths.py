"""Пути внутри JSON-документа: форматирование, JSON Pointer и шаблоны игнорирования.

Путь — это кортеж токенов:
  * ``str``      — ключ объекта;
  * ``int``      — индекс массива;
  * ``KeyRef``   — элемент массива, сопоставленный по ключу (``[id=7]``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple, Union

_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class KeyRef:
    """Элемент массива, найденный по значению ключа (индекс — в новом документе)."""

    index: int
    key: str
    value: Any


Token = Union[str, int, KeyRef]
Path = Tuple[Token, ...]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def format_path(path: Sequence[Token]) -> str:
    """``("users", KeyRef(2, "id", 7), "email")`` → ``$.users[id=7].email``."""
    out = ["$"]
    for tok in path:
        if isinstance(tok, KeyRef):
            out.append(f"[{tok.key}={_dump(tok.value)}]")
        elif isinstance(tok, int):
            out.append(f"[{tok}]")
        elif _IDENT.match(tok):
            out.append("." + tok)
        else:
            out.append("[" + _dump(tok) + "]")
    return "".join(out)


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def to_pointer(path: Sequence[Token]) -> str:
    """Путь → JSON Pointer (RFC 6901). ``KeyRef`` превращается в свой индекс."""
    parts = []
    for tok in path:
        if isinstance(tok, KeyRef):
            parts.append(str(tok.index))
        elif isinstance(tok, int):
            parts.append(str(tok))
        else:
            parts.append(_escape_pointer(tok))
    return "".join("/" + p for p in parts)


def parse_pointer(pointer: str) -> List[str]:
    """JSON Pointer → список «сырых» токенов-строк."""
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer должен начинаться с '/': {pointer!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]


# ---------------------------------------------------------------- шаблоны

# Сегменты шаблона:
#   ("key", name)    .name  или ["name"]
#   ("index", n)     [3]
#   ("any",)         .*  или [*]
#   ("deep",)        ..  (любая глубина, включая ноль)
#   ("keyref", k, v) [id=7]

class PatternError(ValueError):
    pass


def parse_pattern(text: str) -> List[tuple]:
    s = text.strip()
    if not s.startswith("$"):
        raise PatternError(f"шаблон должен начинаться с '$': {text!r}")
    i, n = 1, len(s)
    segs: List[tuple] = []
    while i < n:
        c = s[i]
        if s.startswith("..", i):
            segs.append(("deep",))
            i += 2
            if i < n and s[i] not in ".[":
                m = re.match(r"\*|[A-Za-z_$][A-Za-z0-9_$]*", s[i:])
                if not m:
                    raise PatternError(f"ожидался ключ после '..' в {text!r}")
                name = m.group(0)
                segs.append(("any",) if name == "*" else ("key", name))
                i += len(name)
        elif c == ".":
            m = re.match(r"\*|[A-Za-z_$][A-Za-z0-9_$]*", s[i + 1:])
            if not m:
                raise PatternError(f"ожидался ключ после '.' в {text!r}")
            name = m.group(0)
            segs.append(("any",) if name == "*" else ("key", name))
            i += 1 + len(name)
        elif c == "[":
            end = _find_bracket_end(s, i, text)
            body = s[i + 1:end]
            i = end + 1
            segs.append(_parse_bracket(body, text))
        else:
            raise PatternError(f"неожиданный символ {c!r} в шаблоне {text!r}")
    return segs


def _find_bracket_end(s: str, start: int, text: str) -> int:
    in_str = False
    i = start + 1
    while i < len(s):
        ch = s[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "]":
            return i
        i += 1
    raise PatternError(f"незакрытая '[' в шаблоне {text!r}")


def _parse_bracket(body: str, text: str) -> tuple:
    body = body.strip()
    if body == "*":
        return ("any",)
    if re.fullmatch(r"\d+", body):
        return ("index", int(body))
    if body.startswith('"'):
        try:
            return ("key", json.loads(body))
        except json.JSONDecodeError as exc:
            raise PatternError(f"плохая строка {body} в {text!r}") from exc
    m = re.fullmatch(r"([A-Za-z_$][A-Za-z0-9_$]*)=(.+)", body)
    if m:
        try:
            value = json.loads(m.group(2))
        except json.JSONDecodeError:
            value = m.group(2)
        return ("keyref", m.group(1), value)
    raise PatternError(f"не понимаю сегмент [{body}] в {text!r}")


def _seg_matches(seg: tuple, tok: Token) -> bool:
    kind = seg[0]
    if kind == "any":
        return True
    if kind == "key":
        return isinstance(tok, str) and tok == seg[1]
    if kind == "index":
        if isinstance(tok, KeyRef):
            return tok.index == seg[1]
        return isinstance(tok, int) and not isinstance(tok, bool) and tok == seg[1]
    if kind == "keyref":
        return (isinstance(tok, KeyRef) and tok.key == seg[1]
                and isinstance(tok.value, bool) == isinstance(seg[2], bool)
                and tok.value == seg[2])
    return False


def match_pattern(segs: Sequence[tuple], path: Sequence[Token]) -> bool:
    """Полное совпадение пути с шаблоном (с поддержкой ``..``)."""
    def rec(si: int, pi: int) -> bool:
        if si == len(segs):
            return pi == len(path)
        seg = segs[si]
        if seg[0] == "deep":
            return any(rec(si + 1, k) for k in range(pi, len(path) + 1))
        if pi == len(path):
            return False
        return _seg_matches(seg, path[pi]) and rec(si + 1, pi + 1)

    return rec(0, 0)


class PathMatcher:
    """Набор шаблонов; ``matches(path)`` — совпал ли хоть один."""

    def __init__(self, patterns: Sequence[str] = ()):
        self.sources = list(patterns)
        self.compiled = [parse_pattern(p) for p in patterns]

    def __bool__(self) -> bool:
        return bool(self.compiled)

    def matches(self, path: Sequence[Token]) -> bool:
        return any(match_pattern(c, path) for c in self.compiled)
