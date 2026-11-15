"""Сквозная проверка веб-песочницы в Chromium (Playwright).

Запуск: python -m pytest tests/e2e
Если Playwright или браузер не установлены, тесты пропускаются.
"""
import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture(scope="module")
def server():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(WEB))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"Chromium недоступен: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context()
    pg = ctx.new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(server)
    pg.wait_for_selector("#results:not([hidden])")
    yield pg
    assert errors == [], f"ошибки в консоли: {errors}"
    ctx.close()


def card(pg, kind):
    return pg.locator(f".card.{kind} b").inner_text()


def test_example_loads_and_compares(page):
    assert card(page, "total") == "9"
    assert card(page, "moved") == "1"
    paths = page.locator(".changes .path").all_inner_texts()
    assert "$.users[id=3]" in paths
    assert "$.updatedAt" not in paths
    assert "$.limits.timeoutSec" not in paths


def test_filter_and_search(page):
    page.click('#filters button[data-f="added"]')
    assert page.locator(".changes li").count() == 2
    page.click('#filters button[data-f="all"]')
    page.fill("#search", "aliya")
    assert page.locator(".changes li").count() == 1


def test_patch_tab_and_apply(page):
    page.click("#tab-patch")
    patch = json.loads(page.locator("#patch-out").inner_text())
    assert any(op["op"] == "move" for op in patch)
    page.click("#tab-apply")
    page.click("#btn-apply")
    status = page.locator("#apply-status").inner_text()
    # updatedAt игнорируется, поэтому патч не меняет его — результат отличается от B
    assert "отличается" in status
    page.fill("#opt-ignore", "")
    page.click("#btn-compare")
    page.click("#btn-use-current")
    page.click("#btn-apply")
    assert "совпадает с B" in page.locator("#apply-status").inner_text()


def test_invalid_json_shows_position(page):
    page.fill("#left", '{"a": 1,\n  "b": }')
    page.click("#btn-compare")
    assert "строка 2" in page.locator("#left-status").inner_text()
    assert page.locator("#results").is_hidden()
    assert "Исправьте" in page.locator("#global-error").inner_text()


def test_swap_and_auto_compare(page):
    page.fill("#left", '{"x": 1}')
    page.fill("#right", '{"x": 2, "y": 3}')
    page.wait_for_function("document.querySelector('.card.total b')?.textContent === '2'")
    page.click("#btn-swap")
    assert page.locator(".changes li.removed").count() == 1


def test_equal_documents(page):
    page.fill("#left", "[1, 2, 3]")
    page.fill("#right", "[1, 2, 3]")
    page.click("#btn-compare")
    assert "равны" in page.locator("#cards").inner_text()


def test_bad_pattern_reports_error(page):
    page.fill("#opt-ignore", "nope")
    page.click("#btn-compare")
    assert "Настройки" in page.locator("#global-error").inner_text()


def test_theme_toggle_and_persistence(page, server):
    page.click("#btn-theme")
    theme = page.evaluate("document.documentElement.dataset.theme")
    assert theme in ("dark", "light")
    page.fill("#left", '{"saved": true}')
    page.click("#btn-compare")
    page.reload()
    page.wait_for_selector("#results:not([hidden])")
    assert '"saved"' in page.input_value("#left")


def test_mobile_layout_no_horizontal_scroll(browser, server):
    ctx = browser.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_selector("#results:not([hidden])")
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    ctx.close()
