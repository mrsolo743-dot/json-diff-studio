from json_diff_studio import diff
from json_diff_studio.report import render_json, render_text, short


def test_short_truncates():
    assert short("x" * 100, 10).endswith("…")
    assert len(short("x" * 100, 10)) == 10


def test_text_empty_and_color():
    assert render_text([]) == "Различий нет.\n"
    out = render_text(diff({"a": 1}, {"a": 2}), color=True)
    assert "\033[33m" in out


def test_text_type_change_note():
    out = render_text(diff({"a": 1}, {"a": "1"}))
    assert "(тип изменён)" in out


def test_json_has_pointer():
    out = render_json(diff({"a/b": 1}, {}))
    assert '"pointer": "/a~1b"' in out
