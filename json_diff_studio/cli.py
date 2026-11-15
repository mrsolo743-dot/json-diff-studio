"""Командная строка: ``json-diff-studio diff|patch|apply|verify``."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List, Optional, Sequence

from . import __version__
from .diff import ArrayKey, Options, diff
from .patch import PatchError, apply_patch, make_patch
from .paths import PatternError
from .report import render_html, render_json, render_text

EXIT_SAME, EXIT_DIFF, EXIT_ERROR = 0, 1, 2


class CliError(Exception):
    pass


def load_json(path: str) -> Any:
    try:
        if path == "-":
            text = sys.stdin.read()
        else:
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
    except OSError as exc:
        raise CliError(f"не удалось прочитать {path}: {exc.strerror or exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"{path}: некорректный JSON — {exc.msg} "
                       f"(строка {exc.lineno}, столбец {exc.colno})") from exc


def write_output(text: str, output: Optional[str]) -> None:
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def _add_compare_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("настройки сравнения")
    g.add_argument("-k", "--array-key", action="append", default=[], metavar="[ПУТЬ=]КЛЮЧ",
                   help="сопоставлять элементы массивов по ключу: id или '$.users=id'")
    g.add_argument("-i", "--ignore", action="append", default=[], metavar="ШАБЛОН",
                   help="игнорировать путь: '$.meta.updatedAt', '$..timestamp', '$.items[*].tmp'")
    g.add_argument("--ignore-key", action="append", default=[], metavar="КЛЮЧ",
                   help="игнорировать ключ на любой глубине (то же, что '$..КЛЮЧ')")


def _add_report_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("настройки отчёта (на патч не влияют)")
    g.add_argument("-t", "--tolerance", type=float, default=0.0, metavar="X",
                   help="считать числа равными, если |a-b| <= X")
    g.add_argument("--ignore-case", action="store_true", help="сравнивать строки без учёта регистра")
    g.add_argument("--ignore-order", action="store_true",
                   help="сравнивать массивы без ключа как мультимножества")


def build_options(args: argparse.Namespace) -> Options:
    try:
        return Options.from_dict({
            "arrayKeys": args.array_key,
            "ignore": args.ignore,
            "ignoreKeys": args.ignore_key,
            "tolerance": getattr(args, "tolerance", 0.0),
            "ignoreCase": getattr(args, "ignore_case", False),
            "ignoreOrder": getattr(args, "ignore_order", False),
        })
    except PatternError as exc:
        raise CliError(f"шаблон пути: {exc}") from exc


def _use_color(mode: str, output: Optional[str]) -> bool:
    if mode == "always":
        return True
    if mode == "never" or output:
        return False
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def cmd_diff(args: argparse.Namespace) -> int:
    a, b = load_json(args.left), load_json(args.right)
    opts = build_options(args)
    changes = diff(a, b, opts)
    fmt = args.format
    if fmt == "text":
        out = render_text(changes, color=_use_color(args.color, args.output), limit=args.width)
    elif fmt == "json":
        out = render_json(changes)
    elif fmt == "patch":
        out = json.dumps(make_patch(a, b, opts, args.with_tests), ensure_ascii=False, indent=2) + "\n"
    else:
        out = render_html(changes, make_patch(a, b, opts), args.left, args.right,
                          title=args.title or "Сравнение JSON")
    write_output(out, args.output)
    if args.output and not args.quiet:
        print(f"Записано: {args.output} (изменений: {len(changes)})", file=sys.stderr)
    return EXIT_DIFF if changes and args.exit_code else EXIT_SAME


def cmd_patch(args: argparse.Namespace) -> int:
    a, b = load_json(args.left), load_json(args.right)
    ops = make_patch(a, b, build_options(args), args.with_tests)
    write_output(json.dumps(ops, ensure_ascii=False, indent=2) + "\n", args.output)
    return EXIT_SAME


def cmd_apply(args: argparse.Namespace) -> int:
    doc, patch = load_json(args.document), load_json(args.patch)
    try:
        result = apply_patch(doc, patch)
    except PatchError as exc:
        raise CliError(f"патч не применился — {exc}") from exc
    indent = None if args.compact else 2
    write_output(json.dumps(result, ensure_ascii=False, indent=indent) + "\n", args.output)
    return EXIT_SAME


def cmd_verify(args: argparse.Namespace) -> int:
    a, b, patch = load_json(args.left), load_json(args.right), load_json(args.patch)
    try:
        result = apply_patch(a, patch)
    except PatchError as exc:
        print(f"ПРОВАЛ: патч не применился — {exc}")
        return EXIT_DIFF
    rest = diff(result, b, build_options(args))
    if rest:
        print(f"ПРОВАЛ: после применения патча осталось различий: {len(rest)}")
        print(render_text(rest), end="")
        return EXIT_DIFF
    print(f"OK: патч из {len(patch)} операций превращает {args.left} в {args.right}")
    return EXIT_SAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="json-diff-studio",
        description="Структурное сравнение JSON и JSON Patch (RFC 6902).")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("diff", help="показать различия между двумя JSON")
    p.add_argument("left", help="исходный файл (или - для stdin)")
    p.add_argument("right", help="новый файл")
    p.add_argument("-f", "--format", choices=["text", "json", "patch", "html"], default="text")
    p.add_argument("-o", "--output", help="записать в файл вместо stdout")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p.add_argument("--width", type=int, default=80, help="обрезать значения в тексте до N символов")
    p.add_argument("--title", help="заголовок HTML-отчёта")
    p.add_argument("--with-tests", action="store_true",
                   help="для --format patch: добавлять test-операции перед remove/replace")
    p.add_argument("--exit-code", action="store_true",
                   help="код выхода 1, если различия есть (как у diff)")
    p.add_argument("-q", "--quiet", action="store_true")
    _add_compare_options(p)
    _add_report_options(p)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("patch", help="построить JSON Patch из двух документов")
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("-o", "--output")
    p.add_argument("--with-tests", action="store_true",
                   help="добавлять test-операции перед remove/replace")
    _add_compare_options(p)
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("apply", help="применить JSON Patch к документу")
    p.add_argument("document")
    p.add_argument("patch")
    p.add_argument("-o", "--output")
    p.add_argument("--compact", action="store_true", help="вывести JSON в одну строку")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", help="проверить, что патч превращает left в right")
    p.add_argument("left")
    p.add_argument("right")
    p.add_argument("patch")
    _add_compare_options(p)
    _add_report_options(p)
    p.set_defaults(func=cmd_verify)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
