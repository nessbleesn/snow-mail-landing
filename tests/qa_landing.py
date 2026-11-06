import os
from pathlib import Path
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("SNOW_MAIL_BASE_URL", "http://127.0.0.1:8091/")
ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "preview"
PREVIEW.mkdir(exist_ok=True)


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
        desktop = desktop_context.new_page()
        desktop_errors = []
        desktop.on("console", lambda msg: desktop_errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        desktop.on("pageerror", lambda error: desktop_errors.append(f"pageerror:{error}"))
        desktop.on("requestfailed", lambda request: desktop_errors.append(f"requestfailed:{request.url}"))
        results["desktop"] = inspect_page(desktop, "desktop")
        desktop.goto(BASE_URL, wait_until="networkidle")
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
        assert len(desktop.locator("#form-status").inner_text()) > 20

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
        mobile.locator("#request").scroll_into_view_if_needed()
        mobile.wait_for_timeout(200)
        assert abs(mobile.locator("[data-header]").bounding_box()["y"]) <= 1
        assert mobile.locator("[data-header]").bounding_box()["height"] <= 90
        mobile.add_style_tag(content=".site-header{position:absolute!important}.mobile-cta{display:none!important}.js [data-reveal]{opacity:1!important;transform:none!important;transition:none!important}")
        mobile.wait_for_timeout(100)
        mobile.screenshot(path=PREVIEW / "mobile-full.png", full_page=True)
        mobile.locator("#story").screenshot(path=PREVIEW / "mobile-story.png")
        mobile.locator("#request").screenshot(path=PREVIEW / "mobile-form.png")
        assert not mobile_errors, mobile_errors
        mobile_context.close()

        for width, height in [(1024, 768), (768, 900)]:
            responsive_context = browser.new_context(viewport={"width": width, "height": height})
            responsive = responsive_context.new_page()
            results[f"responsive_{width}"] = inspect_page(responsive, f"responsive_{width}")
            responsive.evaluate("document.getElementById('price').scrollIntoView()")
            responsive.wait_for_timeout(180)
            assert abs(responsive.locator("[data-header]").bounding_box()["y"]) <= 1
            responsive_context.close()

        reference_context = browser.new_context(viewport={"width": 1047, "height": 729})
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
        narrow = narrow_context.new_page()
        results["narrow_reduced"] = inspect_page(narrow, "narrow_reduced")
        assert narrow.locator("[data-reveal]").first.is_visible()
        assert narrow.locator(".liquid-bauble--ice").evaluate("el => getComputedStyle(el).animationName") == "none"
        assert narrow.locator(".liquid-bauble--ice").evaluate("el => getComputedStyle(el).opacity") == "1"
        narrow_context.close()

        stress_context = browser.new_context(viewport={"width": 320, "height": 720})
        stress = stress_context.new_page()
        results["stress_320"] = inspect_page(stress, "stress_320")
        assert stress.locator(".liquid-bauble--ice").is_visible()
        assert stress.locator(".liquid-bauble--cranberry").is_hidden()
        assert stress.locator(".liquid-bauble--gold").is_hidden()
        stress_context.close()

        forced_context = browser.new_context(viewport={"width": 390, "height": 844}, forced_colors="active")
        forced = forced_context.new_page()
        forced.goto(BASE_URL, wait_until="networkidle")
        assert forced.locator(".hero__liquid-decor").is_hidden()
        forced_context.close()

        no_js_context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
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
