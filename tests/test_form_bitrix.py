import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "**/snow-mail/api/lead"


class StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_):
        pass


def fill_form(page):
    form = page.locator("#lead-form")
    form.locator('[name="name"]').fill("Тестовый клиент")
    form.locator('[name="phone"]').fill("8 (999) 000-11-22")
    form.locator('[name="date"]').fill("2026-12-20")
    form.locator('[name="children"]').fill("15")
    form.locator('[name="age"]').fill("7-8 лет")
    form.locator('[name="comment"]').fill("Локальная проверка без рабочей CRM")
    form.locator('[name="consent"]').check()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            calls = []
            page.route(
                "https://top-fwz1.mail.ru/**",
                lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
            )
            page.route(
                "https://mc.yandex.ru/**",
                lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
            )

            def lead_success(route):
                calls.append(route.request.post_data_json)
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"ok": True, "leadId": 12345}),
                )

            page.route(ENDPOINT, lead_success)
            page.goto(
                base
                + "?utm_source=yandex&utm_medium=cpc&utm_campaign=snow-mail"
                + "&utm_content=hero&utm_term=novogodniy-kvest",
                wait_until="networkidle",
            )
            page.wait_for_timeout(800)
            assert page.evaluate(
                "window._tmr.some(item => item.id === '3794718' && item.type === 'pageView')"
            )
            assert page.evaluate(
                "window.ym.a.some(args => args[0] === 107188789 && args[1] === 'init')"
            )
            page.evaluate(
                """() => {
                  window.__leadSuccess = null;
                  window.addEventListener('snowmail:lead-success', event => {
                    window.__leadSuccess = event.detail;
                  }, {once: true});
                }"""
            )
            fill_form(page)
            page.locator("#lead-form").evaluate("form => form.requestSubmit()")
            page.locator('#form-status[data-state="success"]').wait_for()

            assert len(calls) == 1, calls
            payload = calls[0]
            assert payload["name"] == "Тестовый клиент"
            assert payload["consent"] is True
            assert payload["website"] == ""
            assert payload["elapsed_ms"] >= 700
            assert re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                payload["request_id"],
                re.I,
            )
            assert [
                payload["utm_source"],
                payload["utm_medium"],
                payload["utm_campaign"],
                payload["utm_content"],
                payload["utm_term"],
            ] == ["yandex", "cpc", "snow-mail", "hero", "novogodniy-kvest"]
            assert page.evaluate("window.__leadSuccess.leadId") == 12345
            assert page.evaluate(
                "window.dataLayer.some(item => item.event === 'snow_mail_lead_success' && item.lead_id === 12345)"
            )
            assert page.evaluate(
                "window._tmr.filter(item => item.type === 'reachGoal' && item.id === 3794718 && item.goal === 'lead-success').length === 1"
            )
            assert page.evaluate(
                "window.ym.a.filter(args => args[0] === 107188789 && args[1] === 'reachGoal' && args[2] === 'snezhnaya_pochta_form_success').length === 1"
            )

            page.goto(base, wait_until="networkidle")
            assert page.locator('[name="utm_source"]').input_value() == "yandex"
            assert page.locator('[name="utm_campaign"]').input_value() == "snow-mail"

            page.unroute(ENDPOINT)

            def lead_failure(route):
                calls.append(route.request.post_data_json)
                route.fulfill(
                    status=502,
                    content_type="application/json",
                    body='{"ok":false,"error":"sanitized"}',
                )

            page.route(ENDPOINT, lead_failure)
            page.wait_for_timeout(800)
            fill_form(page)
            page.locator("#lead-form").evaluate("form => form.requestSubmit()")
            page.locator('#form-status[data-state="error"]').wait_for()
            assert "Не удалось отправить заявку" in page.locator("#form-status").inner_text()
            assert page.locator('[name="name"]').input_value() == "Тестовый клиент"
            assert calls[0]["request_id"] != calls[1]["request_id"]
            assert page.evaluate(
                "!window._tmr.some(item => item.type === 'reachGoal' && item.goal === 'lead-success')"
            )
            assert page.evaluate(
                "!window.ym.a.some(args => args[1] === 'reachGoal' && args[2] === 'snezhnaya_pochta_form_success')"
            )
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    print("FORM_BITRIX_MOCK_OK")


if __name__ == "__main__":
    main()

