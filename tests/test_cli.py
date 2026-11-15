import json

import pytest

from json_diff_studio.cli import main


@pytest.fixture
def files(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"v": 1, "ts": "x", "list": [{"id": 1, "n": "a"}, {"id": 2, "n": "b"}]}),
                 encoding="utf-8")
    b.write_text(json.dumps({"v": 2, "ts": "y", "list": [{"id": 2, "n": "b"}, {"id": 1, "n": "A"}]}),
                 encoding="utf-8")
    return tmp_path, str(a), str(b)


def test_diff_text(files, capsys):
    _, a, b = files
    assert main(["diff", a, b, "-k", "id", "-i", "$.ts", "--color", "never"]) == 0
    out = capsys.readouterr().out
    assert "~ $.v: 1 → 2" in out
    assert "↕ $.list[id=" in out
    assert "$.ts" not in out
    assert "Итого: 3" in out


def test_exit_code_flag(files, tmp_path):
    _, a, b = files
    assert main(["diff", a, b, "--exit-code", "-q", "-o", str(tmp_path / "o.txt")]) == 1
    assert main(["diff", a, a, "--exit-code"]) == 0


def test_diff_json_format(files, capsys):
    _, a, b = files
    main(["diff", a, b, "-f", "json", "--ignore-key", "ts"])
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["total"] == len(data["changes"])
    assert {"type": "changed", "path": "$.v", "old": 1, "new": 2, "pointer": "/v"} in data["changes"]


def test_patch_apply_verify_roundtrip(files, capsys):
    tmp, a, b = files
    patch = tmp / "p.json"
    out = tmp / "out.json"
    assert main(["patch", a, b, "-k", "id", "-o", str(patch)]) == 0
    assert main(["apply", a, str(patch), "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(open(b, encoding="utf-8").read())
    capsys.readouterr()
    assert main(["verify", a, b, str(patch)]) == 0
    assert capsys.readouterr().out.startswith("OK")


def test_verify_detects_bad_patch(files, capsys):
    tmp, a, b = files
    bad = tmp / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert main(["verify", a, b, str(bad)]) == 1
    assert "ПРОВАЛ" in capsys.readouterr().out
    broken = tmp / "broken.json"
    broken.write_text('[{"op":"remove","path":"/nope"}]', encoding="utf-8")
    assert main(["verify", a, b, str(broken)]) == 1


def test_html_report(files, tmp_path):
    _, a, b = files
    target = tmp_path / "r.html"
    assert main(["diff", a, b, "-f", "html", "-o", str(target), "-q", "--title", "Конфиг </script>"]) == 0
    html = target.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "Конфиг &lt;/script&gt;" in html
    assert html.count("</script>") == 1
    assert '"path": "$.v"' in html or '"path":"$.v"' in html


def test_patch_format_with_tests(files, capsys):
    _, a, b = files
    main(["diff", a, b, "-f", "patch", "--with-tests"])
    ops = json.loads(capsys.readouterr().out)
    assert ops[0]["op"] == "test"


def test_bad_json_reports_position(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": 1,\n "b": }', encoding="utf-8")
    assert main(["diff", str(bad), str(bad)]) == 2
    err = capsys.readouterr().err
    assert "строка 2" in err


def test_missing_file_and_bad_pattern(tmp_path, capsys):
    assert main(["diff", str(tmp_path / "no.json"), str(tmp_path / "no.json")]) == 2
    good = tmp_path / "g.json"
    good.write_text("{}", encoding="utf-8")
    assert main(["diff", str(good), str(good), "-i", "nope"]) == 2
    assert "шаблон" in capsys.readouterr().err


def test_stdin(files, monkeypatch, capsys):
    import io
    _, a, _ = files
    monkeypatch.setattr("sys.stdin", io.StringIO('{"v": 1}'))
    main(["diff", "-", a, "--color", "never"])
    assert "+ $.list" in capsys.readouterr().out


def test_apply_error(files, tmp_path, capsys):
    _, a, _ = files
    p = tmp_path / "p.json"
    p.write_text('[{"op":"test","path":"/v","value":999}]', encoding="utf-8")
    assert main(["apply", a, str(p)]) == 2
    assert "test не прошёл" in capsys.readouterr().err
