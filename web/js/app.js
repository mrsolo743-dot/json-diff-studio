// Интерфейс веб-песочницы json-diff-studio.
import {
  applyPatch, changeToDict, diff, makeOptions, makePatch, parseJsonWithPosition, strictEqual, summarize,
} from "./core.js";

const $ = (id) => document.getElementById(id);
const STORE_KEY = "json-diff-studio:v1";
const LABELS = { added: "добавлено", removed: "удалено", changed: "изменено", moved: "перемещено" };

const EXAMPLE = {
  left: {
    service: "orders-api", version: "1.4.2", updatedAt: "2026-11-01T10:00:00Z",
    limits: { rps: 200, burst: 50, timeoutSec: 2.5 },
    features: ["search", "export", "webhooks"],
    users: [
      { id: 1, name: "Алия", role: "admin", email: "aliya@example.com" },
      { id: 2, name: "Данияр", role: "editor", email: "daniyar@example.com" },
      { id: 3, name: "Мария", role: "viewer", email: "maria@example.com" },
    ],
    debug: true,
  },
  right: {
    service: "orders-api", version: "1.5.0", updatedAt: "2026-11-12T09:30:00Z",
    limits: { rps: 250, burst: 50, timeoutSec: 2.5000001 },
    features: ["search", "audit-log", "export", "webhooks"],
    users: [
      { id: 3, name: "Мария", role: "editor", email: "maria@example.com" },
      { id: 1, name: "Алия", role: "admin", email: "aliya@example.kz" },
      { id: 4, name: "Ерлан", role: "viewer", email: "erlan@example.com" },
    ],
    debug: "false",
  },
  options: { keys: "id", ignore: "$.updatedAt", tol: "0.000001" },
};

const state = { changes: [], patch: [], filter: "all", a: undefined, b: undefined };

// ------------------------------------------------------------ хранение (необязательно)

function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      left: $("left").value, right: $("right").value, keys: $("opt-keys").value,
      ignore: $("opt-ignore").value, tol: $("opt-tol").value, icase: $("opt-case").checked,
      order: $("opt-order").checked, tests: $("opt-tests").checked, auto: $("opt-auto").checked,
      theme: document.documentElement.dataset.theme || "",
    }));
  } catch { /* хранилище недоступно — работаем без него */ }
}

function restore() {
  let data = null;
  try { data = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch { data = null; }
  if (!data) return false;
  $("left").value = data.left || "";
  $("right").value = data.right || "";
  $("opt-keys").value = data.keys || "";
  $("opt-ignore").value = data.ignore || "";
  $("opt-tol").value = data.tol || "";
  $("opt-case").checked = Boolean(data.icase);
  $("opt-order").checked = Boolean(data.order);
  $("opt-tests").checked = Boolean(data.tests);
  $("opt-auto").checked = data.auto !== false;
  if (data.theme) document.documentElement.dataset.theme = data.theme;
  return Boolean(data.left || data.right);
}

// ------------------------------------------------------------ вспомогательное

/** Делит строку по запятым, не трогая запятые внутри [...] и "...". */
export function splitList(text) {
  const out = [];
  let cur = "";
  let depth = 0;
  let inStr = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inStr) {
      cur += ch;
      if (ch === "\\") { cur += text[++i] || ""; continue; }
      if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') inStr = true;
    else if (ch === "[") depth++;
    else if (ch === "]") depth = Math.max(0, depth - 1);
    if ((ch === "," || ch === "\n") && depth === 0) { if (cur.trim()) out.push(cur.trim()); cur = ""; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

const show = (v) => (v === undefined ? "" : JSON.stringify(v, null, 2));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function parseSide(side) {
  const area = $(side);
  const status = $(`${side}-status`);
  const text = area.value;
  if (!text.trim()) {
    area.classList.remove("invalid");
    status.className = "status";
    status.textContent = "Пусто";
    return { ok: false, empty: true };
  }
  const r = parseJsonWithPosition(text);
  area.classList.toggle("invalid", !r.ok);
  status.className = r.ok ? "status" : "status bad";
  if (r.ok) {
    const kind = Array.isArray(r.value) ? `массив, ${r.value.length} эл.` : typeof r.value === "object" && r.value
      ? `объект, ${Object.keys(r.value).length} ключ.` : "скаляр";
    status.textContent = `Корректный JSON · ${kind} · ${text.length.toLocaleString("ru-RU")} символов`;
  } else {
    status.textContent = `Ошибка JSON: строка ${r.line}, столбец ${r.col}`;
  }
  return r;
}

function readOptions() {
  return makeOptions({
    arrayKeys: splitList($("opt-keys").value),
    ignore: splitList($("opt-ignore").value),
    tolerance: Number($("opt-tol").value) || 0,
    ignoreCase: $("opt-case").checked,
    ignoreOrder: $("opt-order").checked,
  });
}

// ------------------------------------------------------------ сравнение

function compare() {
  const err = $("global-error");
  err.textContent = "";
  const a = parseSide("left");
  const b = parseSide("right");
  save();
  if (!a.ok || !b.ok) {
    $("results").hidden = true;
    if (!a.empty && !b.empty) err.textContent = "Исправьте ошибки JSON, чтобы сравнить документы.";
    return;
  }
  let opts;
  try {
    opts = readOptions();
  } catch (e) {
    err.textContent = `Настройки: ${e.message}`;
    $("results").hidden = true;
    return;
  }
  state.a = a.value;
  state.b = b.value;
  state.changes = diff(a.value, b.value, opts).map(changeToDict);
  state.patch = makePatch(a.value, b.value, opts, $("opt-tests").checked);
  $("results").hidden = false;
  renderCards();
  renderChanges();
  renderPatch();
}

function renderCards() {
  const s = summarize(state.changes);
  const items = [["total", "Всего"], ["added", "Добавлено"], ["removed", "Удалено"], ["changed", "Изменено"], ["moved", "Перемещено"]];
  $("cards").innerHTML = s.total === 0
    ? '<div class="card same"><b>0</b><span>Документы равны с учётом настроек</span></div>'
    : items.map(([k, l]) => `<div class="card ${k}"><b>${s[k]}</b><span>${l}</span></div>`).join("");
}

function renderChanges() {
  const q = $("search").value.trim().toLowerCase();
  const rows = state.changes.filter((c) => (state.filter === "all" || c.type === state.filter)
    && (!q || `${c.path} ${show(c.old)} ${show(c.new)}`.toLowerCase().includes(q)));
  if (!rows.length) {
    $("changes").innerHTML = `<li class="empty">${state.changes.length ? "Ничего не найдено" : "Различий нет"}</li>`;
    return;
  }
  $("changes").innerHTML = rows.map((c) => {
    let vals;
    if (c.type === "added") vals = `<span class="new">${esc(show(c.new))}</span>`;
    else if (c.type === "removed") vals = `<span class="gone">${esc(show(c.old))}</span>`;
    else if (c.type === "moved") vals = `позиция ${c.old} → ${c.new}`;
    else vals = `<span class="old">${esc(show(c.old))}</span> → <span class="new">${esc(show(c.new))}</span>`;
    return `<li class="${c.type}"><span class="tag ${c.type}">${LABELS[c.type]}</span>`
      + `<span class="path">${esc(c.path)}</span><span class="vals">${vals}</span></li>`;
  }).join("");
}

function renderPatch() {
  const text = JSON.stringify(state.patch, null, 2);
  $("patch-out").textContent = text;
  $("patch-count").textContent = `Операций: ${state.patch.length}`;
  if (!$("apply-patch").dataset.touched) $("apply-patch").value = text;
}

// ------------------------------------------------------------ применение патча

function runApply() {
  const status = $("apply-status");
  const a = parseSide("left");
  if (!a.ok) { status.className = "bad"; status.textContent = "Документ A некорректен"; return; }
  const p = parseJsonWithPosition($("apply-patch").value);
  if (!p.ok) { status.className = "bad"; status.textContent = `Патч: ошибка JSON, строка ${p.line}, столбец ${p.col}`; return; }
  try {
    const result = applyPatch(a.value, p.value);
    $("apply-out").textContent = JSON.stringify(result, null, 2);
    const b = parseSide("right");
    if (b.ok && strictEqual(result, b.value)) { status.className = "ok"; status.textContent = "Готово: результат совпадает с B"; }
    else { status.className = ""; status.textContent = "Готово: результат отличается от B"; }
  } catch (e) {
    $("apply-out").textContent = "";
    status.className = "bad";
    status.textContent = e.message;
  }
}

// ------------------------------------------------------------ события

let timer = null;
function scheduleCompare() {
  if (!$("opt-auto").checked) { save(); return; }
  clearTimeout(timer);
  timer = setTimeout(compare, 250);
}

function selectTab(name) {
  for (const t of ["changes", "patch", "apply"]) {
    $(`tab-${t}`).setAttribute("aria-selected", String(t === name));
    $(`panel-${t}`).hidden = t !== name;
  }
}

function loadExample() {
  $("left").value = JSON.stringify(EXAMPLE.left, null, 2);
  $("right").value = JSON.stringify(EXAMPLE.right, null, 2);
  $("opt-keys").value = EXAMPLE.options.keys;
  $("opt-ignore").value = EXAMPLE.options.ignore;
  $("opt-tol").value = EXAMPLE.options.tol;
  delete $("apply-patch").dataset.touched;
  compare();
}

function init() {
  const restored = restore();
  for (const id of ["left", "right", "opt-keys", "opt-ignore", "opt-tol"]) $(id).addEventListener("input", scheduleCompare);
  for (const id of ["opt-case", "opt-order", "opt-tests"]) $(id).addEventListener("change", scheduleCompare);
  $("opt-auto").addEventListener("change", save);
  $("btn-compare").addEventListener("click", compare);
  $("btn-example").addEventListener("click", loadExample);
  $("btn-swap").addEventListener("click", () => {
    const l = $("left").value;
    $("left").value = $("right").value;
    $("right").value = l;
    compare();
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); compare(); }
  });
  document.querySelectorAll("[data-format]").forEach((btn) => btn.addEventListener("click", () => {
    const side = btn.dataset.format;
    const r = parseSide(side);
    if (r.ok) { $(side).value = JSON.stringify(r.value, null, 2); scheduleCompare(); }
  }));
  document.querySelectorAll("[data-clear]").forEach((btn) => btn.addEventListener("click", () => {
    $(btn.dataset.clear).value = "";
    compare();
  }));
  document.querySelectorAll("[data-load]").forEach((input) => input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    $(input.dataset.load).value = await file.text();
    input.value = "";
    compare();
  }));
  $("filters").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.filter = b.dataset.f;
    $("filters").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderChanges();
  });
  $("search").addEventListener("input", renderChanges);
  for (const t of ["changes", "patch", "apply"]) $(`tab-${t}`).addEventListener("click", () => selectTab(t));
  $("btn-copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("patch-out").textContent);
      $("btn-copy").textContent = "Скопировано";
    } catch {
      $("btn-copy").textContent = "Не удалось";
    }
    setTimeout(() => { $("btn-copy").textContent = "Копировать"; }, 1500);
  });
  $("btn-download").addEventListener("click", () => {
    const blob = new Blob([$("patch-out").textContent + "\n"], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "patch.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $("apply-patch").addEventListener("input", () => { $("apply-patch").dataset.touched = "1"; });
  $("btn-use-current").addEventListener("click", () => {
    delete $("apply-patch").dataset.touched;
    renderPatch();
  });
  $("btn-apply").addEventListener("click", runApply);
  $("btn-theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    save();
  });

  if (restored) compare();
  else loadExample();
}

init();
