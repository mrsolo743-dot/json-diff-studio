"""Пересобирает fixtures/cases.json — общие фикстуры для Python и JS.

Ожидаемые результаты считает Python-реализация; после пересборки
просмотрите `git diff fixtures/cases.json` глазами, прежде чем коммитить.

    python tools/gen_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from json_diff_studio import Options, apply_patch, diff, make_patch  # noqa: E402

CASES = [
    {"name": "равные документы", "a": {"x": [1, 2, {"y": None}]}, "b": {"x": [1, 2, {"y": None}]}},
    {"name": "скаляры в корне", "a": 1, "b": "1"},
    {"name": "ключи объекта", "a": {"a": 1, "b": 2, "c": {"d": 3}},
     "b": {"a": 1, "c": {"d": 4, "e": 5}, "f": [1]}},
    {"name": "true не равно 1", "a": {"flag": True, "n": 1}, "b": {"flag": 1, "n": 1.0}},
    {"name": "вставка в середину массива", "a": [1, 2, 3, 4], "b": [1, 2, 99, 3, 4]},
    {"name": "удаление и замена в массиве", "a": ["a", "b", "c", "d", "e"], "b": ["a", "x", "d", "e", "f"]},
    {"name": "вложенные объекты в массиве", "a": [{"n": 1, "v": "a"}, {"n": 2, "v": "b"}],
     "b": [{"n": 1, "v": "a"}, {"n": 2, "v": "B"}, {"n": 3, "v": "c"}]},
    {"name": "массив по ключу id",
     "a": {"users": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}]},
     "b": {"users": [{"id": 3, "name": "C"}, {"id": 1, "name": "A2"}, {"id": 4, "name": "D"}]},
     "options": {"arrayKeys": ["id"]}},
    {"name": "ключ только для одного пути",
     "a": {"x": [{"id": 1}, {"id": 2}], "y": [{"id": 1}, {"id": 2}]},
     "b": {"x": [{"id": 2}, {"id": 1}], "y": [{"id": 2}, {"id": 1}]},
     "options": {"arrayKeys": ["$.x=id"]}},
    {"name": "ключ не уникален — откат к LCS",
     "a": [{"id": 1, "v": 1}, {"id": 1, "v": 2}], "b": [{"id": 1, "v": 1}, {"id": 1, "v": 3}],
     "options": {"arrayKeys": ["id"]}},
    {"name": "игнорирование путей",
     "a": {"meta": {"updatedAt": "t1", "by": "x"}, "items": [{"id": 1, "ts": 5, "v": 1}]},
     "b": {"meta": {"updatedAt": "t2", "by": "y"}, "items": [{"id": 1, "ts": 9, "v": 2}]},
     "options": {"ignore": ["$.meta.updatedAt", "$.items[*].ts"]}},
    {"name": "игнорирование ключа на любой глубине",
     "a": {"etag": "1", "a": {"etag": "2", "b": [{"etag": "3", "c": 1}]}},
     "b": {"etag": "9", "a": {"etag": "8", "b": [{"etag": "7", "c": 2}]}},
     "options": {"ignoreKeys": ["etag"]}},
    {"name": "допуск для чисел", "a": {"pi": 3.14159, "e": 2.7}, "b": {"pi": 3.1416, "e": 2.8},
     "options": {"tolerance": 0.001}},
    {"name": "без учёта регистра", "a": ["Hello", "World"], "b": ["hello", "Мир"],
     "options": {"ignoreCase": True}},
    {"name": "без учёта порядка", "a": {"tags": ["a", "b", "c", "c"]}, "b": {"tags": ["c", "a", "d", "c"]},
     "options": {"ignoreOrder": True}},
    {"name": "смена типа", "a": {"v": [1, 2]}, "b": {"v": {"0": 1, "1": 2}}},
    {"name": "особые ключи", "a": {"a/b": 1, "m~n": 2, "with space": 3, "": 4},
     "b": {"a/b": 10, "m~n": 20, "with space": 30, "": 40}},
    {"name": "патч с test-операциями", "a": {"a": 1, "b": [1, 2]}, "b": {"a": 2, "b": [1]}, "withTests": True},
    {"name": "перестановка по ключу и правки",
     "a": [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": "c", "v": 3}, {"k": "d", "v": 4}],
     "b": [{"k": "d", "v": 4}, {"k": "b", "v": 20}, {"k": "a", "v": 1}, {"k": "c", "v": 3}],
     "options": {"arrayKeys": ["k"]}},
    {"name": "пустые контейнеры", "a": {"a": [], "b": {}}, "b": {"a": [1], "b": {"x": None}}},
]


def main() -> None:
    out = []
    for case in CASES:
        opts = Options.from_dict(case.get("options"))
        changes = [c.to_dict() for c in diff(case["a"], case["b"], opts)]
        patch = make_patch(case["a"], case["b"], opts, case.get("withTests", False))
        applied = apply_patch(case["a"], patch)
        entry = dict(case)
        entry["changes"] = changes
        entry["patch"] = patch
        entry["patched"] = applied
        out.append(entry)
    target = ROOT / "fixtures" / "cases.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"записано {len(out)} кейсов в {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
