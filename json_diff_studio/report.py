"""Отчёты: текст для терминала, JSON и автономный HTML."""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional, Sequence

from .diff import MISSING, Change, summarize

SYMBOLS = {"added": "+", "removed": "-", "changed": "~", "moved": "↕"}
COLORS = {"added": "32", "removed": "31", "changed": "33", "moved": "36"}
LABELS_RU = {"added": "добавлено", "removed": "удалено", "changed": "изменено",
             "moved": "перемещено"}


def short(value: Any, limit: int = 80) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def change_line(c: Change, limit: int = 80) -> str:
    if c.type == "added":
        return f"{c.path_str}: {short(c.new, limit)}"
    if c.type == "removed":
        return f"{c.path_str}: {short(c.old, limit)}"
    if c.type == "moved":
        return f"{c.path_str}: позиция {c.old} → {c.new}"
    note = " (тип изменён)" if c.type_changed else ""
    return f"{c.path_str}: {short(c.old, limit)} → {short(c.new, limit)}{note}"


def render_text(changes: Sequence[Change], color: bool = False, limit: int = 80) -> str:
    if not changes:
        return "Различий нет.\n"
    lines = []
    for c in changes:
        line = f"{SYMBOLS[c.type]} {change_line(c, limit)}"
        if color:
            line = f"\033[{COLORS[c.type]}m{line}\033[0m"
        lines.append(line)
    s = summarize(changes)
    lines.append("")
    lines.append(
        f"Итого: {s['total']} — добавлено {s['added']}, удалено {s['removed']}, "
        f"изменено {s['changed']}, перемещено {s['moved']}")
    return "\n".join(lines) + "\n"


def render_json(changes: Sequence[Change]) -> str:
    payload = {"summary": summarize(changes),
               "changes": [dict(c.to_dict(), pointer=c.pointer) for c in changes]}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _safe_json(data: Any) -> str:
    """JSON для вставки внутрь <script>: экранируем «</» и спецсимволы."""
    return (json.dumps(data, ensure_ascii=False)
            .replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e3e2dc;
--add:#1f7a3d;--add-bg:#e5f4ea;--rem:#b42318;--rem-bg:#fbe9e7;--chg:#9a6700;--chg-bg:#fdf3d8;
--mov:#0b6b8a;--mov-bg:#e1f1f7;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--text:#ececea;--muted:#a2a29c;
--line:#33332f;--add:#6fd08f;--add-bg:#173322;--rem:#ff8a7a;--rem-bg:#3a1c18;--chg:#f2c14e;
--chg-bg:#3a2f12;--mov:#6cc7e6;--mov-bg:#123240;--accent:#8ea2ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 20px;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.card span{color:var(--muted);font-size:13px}
.card.added b{color:var(--add)}.card.removed b{color:var(--rem)}.card.changed b{color:var(--chg)}.card.moved b{color:var(--mov)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.bar button{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit;font-size:14px}
.bar button[aria-pressed=true]{border-color:var(--accent);color:var(--accent);font-weight:600}
.bar input{flex:1;min-width:180px;border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:8px;padding:7px 10px;font:inherit}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:13px;color:var(--muted);font-weight:600}
td code{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.tag{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:600;white-space:nowrap}
.tag.added{color:var(--add);background:var(--add-bg)}.tag.removed{color:var(--rem);background:var(--rem-bg)}
.tag.changed{color:var(--chg);background:var(--chg-bg)}.tag.moved{color:var(--mov);background:var(--mov-bg)}
.empty{padding:28px;text-align:center;color:var(--muted)}
details{margin-top:22px}
summary{cursor:pointer;font-weight:600}
pre{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace}
@media (max-width:640px){th:nth-child(4),td:nth-child(4){display:none}}
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
<p class="sub">__SUBTITLE__</p>
<div class="cards" id="cards"></div>
<div class="bar" id="bar">
<button data-f="all" aria-pressed="true">Все</button>
<button data-f="added" aria-pressed="false">Добавлено</button>
<button data-f="removed" aria-pressed="false">Удалено</button>
<button data-f="changed" aria-pressed="false">Изменено</button>
<button data-f="moved" aria-pressed="false">Перемещено</button>
<input id="q" type="search" placeholder="Поиск по пути или значению">
</div>
<table><thead><tr><th>Тип</th><th>Путь</th><th>Было</th><th>Стало</th></tr></thead><tbody id="rows"></tbody></table>
<details><summary>JSON Patch (RFC 6902) — операций: <span id="opcount"></span></summary><pre id="patch"></pre></details>
</main>
<script>
const DATA = __DATA__;
const LABELS = {added:"добавлено",removed:"удалено",changed:"изменено",moved:"перемещено"};
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const show = v => v === undefined ? "" : JSON.stringify(v, null, 2);
let filter = "all";
function renderCards(){
  const s = DATA.summary;
  document.getElementById("cards").innerHTML = [["total","Всего"],["added","Добавлено"],["removed","Удалено"],["changed","Изменено"],["moved","Перемещено"]]
    .map(([k,l]) => `<div class="card ${k}"><b>${s[k]}</b><span>${l}</span></div>`).join("");
}
function renderRows(){
  const q = document.getElementById("q").value.trim().toLowerCase();
  const rows = DATA.changes.filter(c => (filter === "all" || c.type === filter) &&
    (!q || (c.path + " " + show(c.old) + " " + show(c.new)).toLowerCase().includes(q)));
  document.getElementById("rows").innerHTML = rows.length ? rows.map(c =>
    `<tr><td><span class="tag ${c.type}">${LABELS[c.type]}</span></td><td><code>${esc(c.path)}</code></td>` +
    `<td><code>${esc(c.type === "moved" ? "позиция " + c.old : show(c.old))}</code></td>` +
    `<td><code>${esc(c.type === "moved" ? "позиция " + c.new : show(c.new))}</code></td></tr>`).join("")
    : `<tr><td colspan="4" class="empty">${DATA.changes.length ? "Ничего не найдено" : "Различий нет"}</td></tr>`;
}
document.getElementById("bar").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  filter = b.dataset.f;
  document.querySelectorAll("#bar button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  renderRows();
});
document.getElementById("q").addEventListener("input", renderRows);
document.getElementById("patch").textContent = JSON.stringify(DATA.patch, null, 2);
document.getElementById("opcount").textContent = DATA.patch.length;
renderCards(); renderRows();
</script>
</body>
</html>
"""


def render_html(changes: Sequence[Change], patch: List[Dict[str, Any]],
                left: str = "a.json", right: str = "b.json",
                title: str = "Сравнение JSON") -> str:
    data = {"summary": summarize(changes),
            "changes": [c.to_dict() for c in changes],
            "patch": patch}
    return (HTML_TEMPLATE
            .replace("__TITLE__", html.escape(title))
            .replace("__SUBTITLE__", f"{html.escape(left)} → {html.escape(right)}")
            .replace("__DATA__", _safe_json(data)))
