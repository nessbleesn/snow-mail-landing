import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("SNOW_MAIL_BASE_URL", "http://127.0.0.1:8091/")
ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "preview"
PREVIEW.mkdir(exist_ok=True)


def mock_analytics(context):
    for pattern in (
        "https://top-fwz1.mail.ru/**",
        "https://privacy-cs.mail.ru/**",
        "https://mc.yandex.ru/**",
        "**://cc.calltracking.ru/**",
    ):
        context.route(pattern, lambda route: route.fulfill(status=204, body=""))


def inspect_page(page, name: str):
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(500)
    load_lazy_images(page)
    page.evaluate("document.documentElement.style.scrollBehavior = 'auto'; window.scrollTo(0, 0)")
    page.wait_for_timeout(250)

    metrics = page.evaluate(
        """() => ({
          title: document.title,
          h1: document.querySelector('h1')?.innerText,
          images: [...document.images].map(img => ({src: img.getAttribute('src'), alt: img.alt, hasAlt: img.hasAttribute('alt'), ok: img.complete && img.naturalWidth > 0})),
          buttons: [...document.querySelectorAll('button, a.button')].map(el => el.textContent.trim()),
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          offenders: [...document.querySelectorAll('body *')]
            .map(el => ({tag: el.tagName, cls: el.className, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right}))
            .filter(item => item.left < -1 || item.right > document.documentElement.clientWidth + 1)
            .slice(0, 12),
          h2Count: document.querySelectorAll('h2').length,
          headings: [...document.querySelectorAll('h1, h2, h3')].map(el => el.textContent.trim()),
          formExists: Boolean(document.querySelector('#lead-form')),
          formVisible: Boolean(document.querySelector('#lead-form')?.getBoundingClientRect().width),
          headerPosition: getComputedStyle(document.querySelector('[data-header]')).position,
          headerTop: document.querySelector('[data-header]').getBoundingClientRect().top,
          headerHeight: document.querySelector('[data-header]').getBoundingClientRect().height
        })"""
    )

    assert metrics["title"] and len(metrics["title"]) > 12
    assert metrics["h1"] and len(metrics["h1"].split()) >= 2
    assert metrics["h2Count"] >= 6
    assert all(not heading.endswith(".") and ". " not in heading for heading in metrics["headings"]), metrics["headings"]
    assert metrics["formExists"] and metrics["formVisible"]
    assert metrics["headerPosition"] == "fixed", metrics["headerPosition"]
    assert abs(metrics["headerTop"]) <= 1
    assert metrics["headerHeight"] <= (90 if page.viewport_size["width"] <= 820 else 96), metrics["headerHeight"]
    assert metrics["overflow"] <= 1, f"{name}: horizontal overflow {metrics['overflow']}px; {metrics['offenders']}"
    assert all(item["ok"] for item in metrics["images"]), metrics["images"]
    assert all(item["hasAlt"] for item in metrics["images"]), metrics["images"]
    return metrics


def load_lazy_images(page):
    page.evaluate(
        """async () => {
          document.documentElement.style.scrollBehavior = 'auto';
          for (const img of document.querySelectorAll("img[loading='lazy']")) {
            img.loading = 'eager';
            img.scrollIntoView({block: 'center'});
            try { await img.decode(); } catch (_) {}
            await new Promise(resolve => setTimeout(resolve, 120));
          }
          window.scrollTo(0, 0);
          await new Promise(resolve => setTimeout(resolve, 120));
        }"""
    )
    page.wait_for_function("() => [...document.images].every(img => img.complete && img.naturalWidth > 0)")


def main():
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()

        desktop_context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        mock_analytics(desktop_context)
        desktop = desktop_context.new_page()
        lead_calls = []

        def lead_success(route):
            lead_calls.append(route.request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"ok":true,"leadId":12345}',
            )

        desktop.route("**/snow-mail/api/lead", lead_success)
        desktop_errors = []
        desktop.on("console", lambda msg: desktop_errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        desktop.on("pageerror", lambda error: desktop_errors.append(f"pageerror:{error}"))
        desktop.on("requestfailed", lambda request: desktop_errors.append(f"requestfailed:{request.url}"))
        results["desktop"] = inspect_page(desktop, "desktop")
        seo = desktop.evaluate(
            """() => ({
              title: document.title,
              description: document.querySelector('meta[name="description"]')?.content,
              robots: document.querySelector('meta[name="robots"]')?.content,
              canonical: document.querySelector('link[rel="canonical"]')?.href,
              ogTitle: document.querySelector('meta[property="og:title"]')?.content,
              ogDescription: document.querySelector('meta[property="og:description"]')?.content,
              ogImage: document.querySelector('meta[property="og:image"]')?.content,
              ogImageWidth: document.querySelector('meta[property="og:image:width"]')?.content,
              ogImageHeight: document.querySelector('meta[property="og:image:height"]')?.content,
              twitterCard: document.querySelector('meta[name="twitter:card"]')?.content,
              twitterImage: document.querySelector('meta[name="twitter:image"]')?.content,
              schemas: [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(script => JSON.parse(script.textContent))
            })"""
        )
        assert 45 <= len(seo["title"]) <= 65, seo["title"]
        assert 120 <= len(seo["description"]) <= 160, seo["description"]
        assert "index" in seo["robots"] and "max-image-preview:large" in seo["robots"], seo["robots"]
        assert seo["canonical"] == "https://parkskazka.ru/snow-mail/", seo["canonical"]
        assert seo["ogTitle"] and seo["ogDescription"]
        assert seo["ogImage"] == "https://parkskazka.ru/snow-mail/assets/snow-mail-social-v1.jpg"
        assert seo["ogImageWidth"] == "1200" and seo["ogImageHeight"] == "630"
        assert seo["twitterCard"] == "summary_large_image"
        assert seo["twitterImage"] == seo["ogImage"]
        assert desktop.locator('script[src*="cc.calltracking.ru/phone.4d847.16824.async.js"]').count() == 1
        schema_types = {
            item.get("@type")
            for schema in seo["schemas"]
            for item in schema.get("@graph", [])
        }
        assert {"WebPage", "ImageObject", "Event", "WebSite"}.issubset(schema_types), schema_types
        desktop.goto(
            BASE_URL + "?utm_source=yandex&utm_medium=cpc&utm_campaign=snow-mail&utm_content=hero&utm_term=kids",
            wait_until="networkidle",
        )
        desktop.wait_for_timeout(500)
        desktop.screenshot(path=PREVIEW / "desktop-hero.png")
        desktop.locator("#price").scroll_into_view_if_needed()
        desktop.wait_for_timeout(250)
        assert abs(desktop.locator("[data-header]").bounding_box()["y"]) <= 1
        assert desktop.locator("[data-header]").bounding_box()["height"] <= 96
        desktop.evaluate("document.documentElement.style.setProperty('--topbar-h', '1000px')")
        desktop.wait_for_timeout(500)
        assert desktop.locator("[data-header]").bounding_box()["height"] <= 96
        assert desktop.locator("[data-nav-section='price']").get_attribute("aria-current") == "location"
        desktop.screenshot(path=PREVIEW / "desktop-header-scrolled.png")
        desktop.goto(BASE_URL, wait_until="networkidle")
        load_lazy_images(desktop)
        desktop.add_style_tag(content=".site-header{position:absolute!important}.mobile-cta{display:none!important}.js [data-reveal]{opacity:1!important;transform:none!important;transition:none!important}")
        desktop.wait_for_timeout(100)
        desktop.screenshot(path=PREVIEW / "desktop-full.png", full_page=True)

        form = desktop.locator("#lead-form")
        form.scroll_into_view_if_needed()
        form.locator("button[type='submit']").click()
        assert desktop.locator("#form-status[data-state='error']").is_visible()
        form.locator("input[name='name']").fill("Anna")
        form.locator("input[name='phone']").fill("+7 999 000-00-00")
        form.locator("input[name='date']").fill("2026-12-20")
        form.locator("input[name='children']").fill("15")
        form.locator("input[name='consent']").check()
        form.locator("button[type='submit']").click()
        desktop.locator("#form-status[data-state='success']").wait_for(state="visible")
        assert "Заявка отправлена" in desktop.locator("#form-status").inner_text()
        assert len(lead_calls) == 1
        lead = lead_calls[0]
        assert lead["consent"] is True
        assert lead["utm_source"] == "yandex"
        assert lead["utm_medium"] == "cpc"
        assert lead["utm_campaign"] == "snow-mail"
        assert lead["utm_content"] == "hero"
        assert lead["utm_term"] == "kids"
        assert lead["elapsed_ms"] >= 700
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", lead["request_id"], re.I)
        assert desktop.evaluate("window.dataLayer.some(item => item.event === 'snow_mail_lead_success' && item.lead_id === 12345)")

        desktop.locator("[data-group-range]").fill("10")
        assert "6 000" in desktop.locator("[data-unit-price]").inner_text()
        assert "60 000" in desktop.locator("[data-total-price]").inner_text()
        assert desktop.locator("input[name='children']").input_value() == "10"
        desktop.locator("[data-group-range]").fill("15")
        assert "5 500" in desktop.locator("[data-unit-price]").inner_text()
        assert "82 500" in desktop.locator("[data-total-price]").inner_text()
        assert not desktop_errors, desktop_errors
        desktop_context.close()

        mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mock_analytics(mobile_context)
        mobile = mobile_context.new_page()
        mobile_errors = []
        mobile.on("console", lambda msg: mobile_errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        mobile.on("pageerror", lambda error: mobile_errors.append(f"pageerror:{error}"))
        mobile.on("requestfailed", lambda request: mobile_errors.append(f"requestfailed:{request.url}"))
        results["mobile"] = inspect_page(mobile, "mobile")
        mobile.goto(BASE_URL, wait_until="networkidle")
        mobile.wait_for_timeout(500)
        load_lazy_images(mobile)
        mobile.screenshot(path=PREVIEW / "mobile-hero.png")
        assert mobile.locator("[data-header]").is_visible()
        mobile_header_box = mobile.locator("[data-header]").bounding_box()
        mobile_media_box = mobile.locator(".hero__media").bounding_box()
        mobile_title_box = mobile.locator("#event-title").bounding_box()
        mobile_ornaments_box = mobile.locator(".hero__liquid-decor").bounding_box()
        assert mobile_header_box and mobile_media_box
        assert abs(mobile_media_box["y"] - mobile_header_box["height"]) <= 1, (mobile_header_box, mobile_media_box)
        assert 340 <= mobile_media_box["height"] <= 390, mobile_media_box
        assert mobile_title_box and abs(
            (mobile_media_box["y"] + mobile_media_box["height"])
            - (mobile_title_box["y"] + mobile_title_box["height"])
        ) <= 12, (mobile_media_box, mobile_title_box)
        assert mobile_ornaments_box and (
            mobile_ornaments_box["y"] + mobile_ornaments_box["height"]
            <= mobile_media_box["y"] + mobile_media_box["height"] + 1
        ), (mobile_media_box, mobile_ornaments_box)
        assert mobile.locator(".hero__photo").evaluate("el => getComputedStyle(el).objectFit") == "cover"
        assert mobile.locator(".site-header .brand").get_attribute("href") == "https://parkskazka.ru/meropriyatiya"
        assert mobile.locator(".header-phone").is_visible()
        assert mobile.locator(".header-phone").get_attribute("href") == "tel:+74951336556"
        assert mobile.locator("[data-mobile-cta]").get_attribute("aria-hidden") == "true"
        mobile.locator("#program").scroll_into_view_if_needed()
        mobile.wait_for_timeout(700)
        mobile.locator("#program").screenshot(path=PREVIEW / "mobile-program.png")
        program_photo_ratio = mobile.locator(".program-card--photo").first.evaluate(
            "el => el.querySelector('.program-card__photo').getBoundingClientRect().height / el.getBoundingClientRect().height"
        )
        assert program_photo_ratio >= 0.57, program_photo_ratio
        assert mobile.locator("[data-mobile-cta]").get_attribute("aria-hidden") == "false"
        assert "is-visible" in (mobile.locator("[data-mobile-cta]").get_attribute("class") or "")
        mobile.screenshot(path=PREVIEW / "mobile-sticky-cta.png")
        mobile.locator("[data-mobile-cta]").click()
        mobile.wait_for_timeout(700)
        assert mobile.locator("[data-mobile-cta]").get_attribute("aria-hidden") == "true"
        mobile.locator("#request").scroll_into_view_if_needed()
        mobile.wait_for_timeout(200)
        assert abs(mobile.locator("[data-header]").bounding_box()["y"]) <= 1
        assert mobile.locator("[data-header]").bounding_box()["height"] <= 90
        mobile.add_style_tag(content=".site-header{position:absolute!important}.mobile-cta{display:none!important}.js [data-reveal]{opacity:1!important;transform:none!important;transition:none!important}")
        mobile.wait_for_timeout(100)
        mobile.screenshot(path=PREVIEW / "mobile-full.png", full_page=True)
        mobile.locator("#story").screenshot(path=PREVIEW / "mobile-story.png")
        mobile.locator("#request").screenshot(path=PREVIEW / "mobile-form.png")
        checkbox_box = mobile.locator(".consent input").bounding_box()
        assert checkbox_box and abs(checkbox_box["width"] - checkbox_box["height"]) <= 1, checkbox_box
        assert checkbox_box["width"] <= 22, checkbox_box
        assert not mobile_errors, mobile_errors
        mobile_context.close()

        for width, height in [(1024, 768), (768, 900)]:
            responsive_context = browser.new_context(viewport={"width": width, "height": height})
            mock_analytics(responsive_context)
            responsive = responsive_context.new_page()
            results[f"responsive_{width}"] = inspect_page(responsive, f"responsive_{width}")
            responsive.evaluate("document.getElementById('price').scrollIntoView()")
            responsive.wait_for_timeout(180)
            assert abs(responsive.locator("[data-header]").bounding_box()["y"]) <= 1
            responsive_context.close()

        reference_context = browser.new_context(viewport={"width": 1047, "height": 729})
        mock_analytics(reference_context)
        reference = reference_context.new_page()
        results["reference_1047"] = inspect_page(reference, "reference_1047")
        assert reference.locator(".dispatch-card").count() == 0
        assert reference.locator(".hero__liquid-decor").count() == 1
        assert reference.locator(".liquid-bauble").count() == 3
        assert reference.get_by_role("heading", name="Три аниматора").count() == 1
        assert reference.get_by_role("img", name="Иллюстрация новогоднего сладкого подарка в красном мешочке").count() == 1
        assert reference.locator(".scroll-progress, .hero__availability, .hero__facts, .hero__edge-label, .hero__flight-path, .hero-marquee").count() == 0
        media_box = reference.locator(".hero__media").bounding_box()
        title_box = reference.locator("#event-title").bounding_box()
        assert media_box and media_box["x"] <= 1 and media_box["width"] >= 1046, media_box
        assert title_box and title_box["x"] >= 0 and title_box["x"] + title_box["width"] <= 1047, title_box
        reference.screenshot(path=PREVIEW / "hero-1047-fixed.png")
        reference_context.close()

        narrow_context = browser.new_context(viewport={"width": 360, "height": 800}, reduced_motion="reduce")
        mock_analytics(narrow_context)
        narrow = narrow_context.new_page()
        results["narrow_reduced"] = inspect_page(narrow, "narrow_reduced")
        assert narrow.locator("[data-reveal]").first.is_visible()
        assert narrow.locator(".liquid-bauble--ice").evaluate("el => getComputedStyle(el).animationName") == "none"
        assert narrow.locator(".liquid-bauble--ice").evaluate("el => getComputedStyle(el).opacity") == "1"
        narrow_context.close()

        stress_context = browser.new_context(viewport={"width": 320, "height": 720})
        mock_analytics(stress_context)
        stress = stress_context.new_page()
        results["stress_320"] = inspect_page(stress, "stress_320")
        assert stress.locator(".header-phone").is_visible()
        assert stress.locator(".header-phone").bounding_box()["width"] > 70
        assert stress.locator(".liquid-bauble--ice").is_visible()
        assert stress.locator(".liquid-bauble--cranberry").is_visible()
        assert stress.locator(".liquid-bauble--gold").is_visible()
        stress_context.close()

        forced_context = browser.new_context(viewport={"width": 390, "height": 844}, forced_colors="active")
        mock_analytics(forced_context)
        forced = forced_context.new_page()
        forced.goto(BASE_URL, wait_until="networkidle")
        assert forced.locator(".hero__liquid-decor").is_hidden()
        forced_context.close()

        no_js_context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
        mock_analytics(no_js_context)
        no_js = no_js_context.new_page()
        no_js.goto(BASE_URL, wait_until="networkidle")
        assert no_js.locator("#event-title").is_visible()
        assert no_js.locator("#story .route__step").first.is_visible()
        assert no_js.locator("#lead-form").is_visible()
        no_js_context.close()

        browser.close()

    print("QA_OK")
    for name, metrics in results.items():
        print(name, {"overflow": metrics["overflow"], "images": len(metrics["images"]), "h2": metrics["h2Count"]})


if __name__ == "__main__":
    main()
