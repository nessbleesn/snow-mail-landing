import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("SNOW_MAIL_BASE_URL", "http://127.0.0.1:8093/")
ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "preview" / "cross-browser"
PREVIEW.mkdir(parents=True, exist_ok=True)


def collect_errors(page):
    errors = []
    page.on(
        "console",
        lambda message: errors.append(f"console:{message.type}:{message.text}")
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: errors.append(f"pageerror:{error}"))
    page.on("requestfailed", lambda request: errors.append(f"requestfailed:{request.url}"))
    return errors


def load_page(page):
    page.goto(BASE_URL, wait_until="networkidle")
    page.evaluate(
        """() => document.querySelectorAll('img[loading="lazy"]').forEach(image => {
          image.loading = 'eager';
          image.src = image.currentSrc || image.src;
        })"""
    )
    page.wait_for_timeout(350)
    page.evaluate(
        """async () => {
          document.documentElement.style.scrollBehavior = 'auto';
          const step = Math.max(window.innerHeight * 0.75, 480);
          for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
            window.scrollTo(0, y);
            await new Promise(resolve => setTimeout(resolve, 45));
          }
          window.scrollTo(0, 0);
          await new Promise(resolve => setTimeout(resolve, 180));
        }"""
    )
    page.wait_for_function(
        "[...document.images].every(image => image.complete && image.naturalWidth > 0)",
        timeout=15_000,
    )


def inspect_mobile(page, name):
    load_page(page)
    metrics = page.evaluate(
        """() => {
          const viewportWidth = document.documentElement.clientWidth;
          const header = document.querySelector('[data-header]');
          const title = document.querySelector('#event-title');
          const fields = [...document.querySelectorAll(
            '#lead-form input:not([type="hidden"]):not([type="checkbox"]), #lead-form textarea'
          )].map(element => ({
            name: element.name,
            fontSize: parseFloat(getComputedStyle(element).fontSize),
            rect: element.getBoundingClientRect().toJSON()
          }));
          const targets = [...document.querySelectorAll(
            '.button, .text-link, .brand, .header-phone, .consent, .faq summary'
          )].filter(element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          }).map(element => ({
            label: element.textContent.trim().replace(/\\s+/g, ' ').slice(0, 70),
            width: element.getBoundingClientRect().width,
            height: element.getBoundingClientRect().height
          }));
          const visibleTextOffenders = [...document.querySelectorAll('h1, h2, h3, p, label, a, button, summary')]
            .filter(element => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 &&
                (rect.left < -1 || rect.right > viewportWidth + 1);
            })
            .map(element => ({tag: element.tagName, cls: element.className, text: element.textContent.trim().slice(0, 80)}))
            .slice(0, 12);
          return {
            viewportWidth,
            overflow: document.documentElement.scrollWidth - viewportWidth,
            headerPosition: getComputedStyle(header).position,
            headerTop: header.getBoundingClientRect().top,
            headerHeight: header.getBoundingClientRect().height,
            titleLeft: title.getBoundingClientRect().left,
            titleRight: title.getBoundingClientRect().right,
            fields,
            targets,
            visibleTextOffenders,
            imagesOk: [...document.images].every(image => image.complete && image.naturalWidth > 0)
          };
        }"""
    )

    assert metrics["overflow"] <= 1, f"{name}: horizontal overflow {metrics['overflow']}"
    assert metrics["headerPosition"] == "fixed", f"{name}: header is not fixed"
    assert abs(metrics["headerTop"]) <= 1, f"{name}: header top {metrics['headerTop']}"
    assert metrics["headerHeight"] <= 110, f"{name}: header too tall {metrics['headerHeight']}"
    assert metrics["titleLeft"] >= -1 and metrics["titleRight"] <= metrics["viewportWidth"] + 1, metrics
    assert metrics["imagesOk"], f"{name}: image failed to load"
    assert all(field["fontSize"] >= 16 for field in metrics["fields"]), metrics["fields"]
    assert all(target["height"] >= 43 for target in metrics["targets"]), metrics["targets"]
    assert not metrics["visibleTextOffenders"], metrics["visibleTextOffenders"]

    sticky = page.locator("[data-mobile-cta]")
    hero_action_in_view = page.locator(".hero__actions").evaluate(
        """element => {
          const rect = element.getBoundingClientRect();
          return rect.top < window.innerHeight && rect.bottom > 0;
        }"""
    )
    expected_top_state = "true" if page.viewport_size["width"] > 820 or hero_action_in_view else "false"
    assert sticky.get_attribute("aria-hidden") == expected_top_state, (
        f"{name}: sticky CTA state does not match hero CTA visibility"
    )
    if page.viewport_size["width"] <= 820:
        page.locator("#program").scroll_into_view_if_needed()
        page.wait_for_timeout(650)
        assert sticky.get_attribute("aria-hidden") == "false", f"{name}: sticky CTA did not appear"
        assert "is-visible" in (sticky.get_attribute("class") or ""), f"{name}: sticky CTA class missing"
        sticky.click()
        page.wait_for_timeout(650)
        assert sticky.get_attribute("aria-hidden") == "true", f"{name}: sticky CTA covers request form"

    page.goto(BASE_URL, wait_until="networkidle")
    page.locator("[data-cta='header']").click()
    page.wait_for_timeout(650)
    anchor = page.evaluate(
        """() => {
          const header = document.querySelector('[data-header]').getBoundingClientRect();
          const request = document.querySelector('#request').getBoundingClientRect();
          return {headerBottom: header.bottom, requestTop: request.top};
        }"""
    )
    assert anchor["requestTop"] >= anchor["headerBottom"] - 2, f"{name}: anchor hidden {anchor}"

    first_faq = page.locator(".faq details").first
    first_faq.locator("summary").click()
    assert first_faq.get_attribute("open") is not None, f"{name}: FAQ did not open"

    return metrics


def main():
    results = {}
    with sync_playwright() as playwright:
        cases = [
            ("chromium", "android_pixel_7", playwright.devices["Pixel 7"]),
            ("chromium", "android_galaxy_s9", playwright.devices["Galaxy S9+"]),
            (
                "chromium",
                "android_yandex",
                {
                    **playwright.devices["Pixel 7"],
                    "user_agent": (
                        "Mozilla/5.0 (Linux; arm_64; Android 14; Pixel 7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 "
                        "YaBrowser/25.10.0.0 Mobile Safari/537.36"
                    ),
                },
            ),
            ("webkit", "iphone_13", playwright.devices["iPhone 13"]),
            ("webkit", "iphone_se", playwright.devices["iPhone SE"]),
            ("webkit", "iphone_13_landscape", playwright.devices["iPhone 13 landscape"]),
            ("webkit", "iphone_15", playwright.devices["iPhone 15"]),
            ("webkit", "iphone_15_pro_max", playwright.devices["iPhone 15 Pro Max"]),
            (
                "webkit",
                "iphone_16_pro",
                {
                    **playwright.devices["iPhone 15 Pro"],
                    "viewport": {"width": 402, "height": 874},
                    "screen": {"width": 402, "height": 874},
                },
            ),
            (
                "webkit",
                "iphone_16_pro_max",
                {
                    **playwright.devices["iPhone 15 Pro Max"],
                    "viewport": {"width": 440, "height": 956},
                    "screen": {"width": 440, "height": 956},
                },
            ),
            (
                "webkit",
                "iphone_16_pro_max_landscape",
                {
                    **playwright.devices["iPhone 15 Pro Max landscape"],
                    "viewport": {"width": 956, "height": 440},
                    "screen": {"width": 956, "height": 440},
                },
            ),
            (
                "webkit",
                "iphone_17_pro",
                {
                    **playwright.devices["iPhone 15 Pro"],
                    "viewport": {"width": 402, "height": 874},
                    "screen": {"width": 402, "height": 874},
                },
            ),
            (
                "webkit",
                "iphone_17_pro_max",
                {
                    **playwright.devices["iPhone 15 Pro Max"],
                    "viewport": {"width": 440, "height": 956},
                    "screen": {"width": 440, "height": 956},
                },
            ),
        ]

        for engine_name, case_name, context_options in cases:
            browser_type = getattr(playwright, engine_name)
            browser = browser_type.launch(headless=True)
            context = browser.new_context(**context_options)
            page = context.new_page()
            errors = collect_errors(page)
            metrics = inspect_mobile(page, case_name)
            assert not errors, f"{case_name}: {errors}"
            results[case_name] = {
                "engine": engine_name,
                "viewport": page.viewport_size,
                "overflow": metrics["overflow"],
                "headerHeight": round(metrics["headerHeight"], 2),
                "minTargetHeight": round(min(target["height"] for target in metrics["targets"]), 2),
                "minFieldFont": min(field["fontSize"] for field in metrics["fields"]),
                "stickyCta": "ok",
            }
            if case_name in {"android_yandex", "iphone_13", "iphone_13_landscape"}:
                page.screenshot(path=PREVIEW / f"{case_name}.png", full_page=True)
            context.close()
            browser.close()

        browser = playwright.webkit.launch(headless=True)
        reduced_context = browser.new_context(**playwright.devices["iPhone 13"], reduced_motion="reduce")
        reduced = reduced_context.new_page()
        load_page(reduced)
        reduced_names = reduced.evaluate(
            """() => ({
              tree: getComputedStyle(document.querySelector('.liquid-bauble__icon--tree')).animationName,
              bauble: getComputedStyle(document.querySelector('.liquid-bauble--ice')).animationName,
              reveal: getComputedStyle(document.querySelector('[data-reveal]')).transitionDuration
            })"""
        )
        assert reduced_names["tree"] == "none", reduced_names
        assert reduced_names["bauble"] == "none", reduced_names
        results["iphone_reduced_motion"] = reduced_names
        reduced_context.close()

        text_context = browser.new_context(**playwright.devices["iPhone SE"])
        text_page = text_context.new_page()
        text_page.goto(BASE_URL, wait_until="networkidle")
        text_page.add_style_tag(content="html { font-size: 200% !important; }")
        text_page.wait_for_timeout(300)
        text_metrics = text_page.evaluate(
            """() => ({
              overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
              headerHeight: document.querySelector('[data-header]').getBoundingClientRect().height,
              interactiveOffenders: [...document.querySelectorAll('a, button, input, textarea, summary')]
                .filter(element => {
                  const rect = element.getBoundingClientRect();
                  const style = getComputedStyle(element);
                  return style.display !== 'none' && rect.width > 0 &&
                    (rect.left < -1 || rect.right > document.documentElement.clientWidth + 1);
                }).map(element => element.outerHTML.slice(0, 120)).slice(0, 10)
            })"""
        )
        assert text_metrics["overflow"] <= 1, text_metrics
        assert not text_metrics["interactiveOffenders"], text_metrics
        results["iphone_text_200"] = text_metrics
        text_context.close()
        browser.close()

    print("CROSS_BROWSER_QA_OK")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
