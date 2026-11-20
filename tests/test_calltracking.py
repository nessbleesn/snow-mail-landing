import os

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("SNOW_MAIL_BASE_URL", "http://127.0.0.1:8091/")


FAKE_CALLTRACKING = """
if (!window.jQuery) throw new Error("Calltracking started without window.jQuery");
window.__calltrackingJqueryVersion = window.jQuery.fn.jquery;
window.__calltrackingPhoneAtLoad = document.querySelector('.header-phone')?.textContent.trim();
window.jQuery('.header-phone').each(function () {
  this.textContent = '+7 (495) 503-51-13';
  this.setAttribute('href', 'tel:+74955035113');
});
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})

        for pattern in (
            "https://top-fwz1.mail.ru/**",
            "https://privacy-cs.mail.ru/**",
            "https://mc.yandex.ru/**",
        ):
            context.route(pattern, lambda route: route.fulfill(status=204, body=""))

        context.route(
            "**://cc.calltracking.ru/**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=FAKE_CALLTRACKING,
            ),
        )

        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )

        page.goto(BASE_URL, wait_until="networkidle")

        assert page.evaluate("window.jQuery?.fn?.jquery") == "3.7.1"
        assert page.evaluate("window.__calltrackingJqueryVersion") == "3.7.1"
        assert page.evaluate("window.__calltrackingPhoneAtLoad") == "+7 (495) 133-65-56"
        assert page.locator("#calltracking-script").count() == 1
        assert page.locator('script[src*="assets/vendor/jquery-3.7.1.min.js"]').count() == 1
        assert page.locator(".header-phone").inner_text().strip() == "+7 (495) 503-51-13"
        assert page.locator(".header-phone").get_attribute("href") == "tel:+74955035113"
        assert not errors, errors

        context.close()
        browser.close()

    print("CALLTRACKING_QA_OK")


if __name__ == "__main__":
    main()
