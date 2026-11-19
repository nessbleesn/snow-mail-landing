(function () {
  "use strict";

  const config = window.SNOW_MAIL_CONFIG || {};
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const header = document.querySelector("[data-header]");
  const navLinks = [...document.querySelectorAll("[data-nav-section]")];
  const navSections = navLinks
    .map((link) => document.getElementById(link.dataset.navSection))
    .filter(Boolean);
  const hero = document.querySelector("[data-hero]");
  const heroPhoto = hero?.querySelector(".hero__photo");
  const form = document.querySelector("#lead-form");
  const status = document.querySelector("#form-status");
  const calculator = document.querySelector("[data-calculator]");
  const groupRange = calculator?.querySelector("[data-group-range]");
  const groupOutput = calculator?.querySelector("[data-group-output]");
  const unitPriceOutput = calculator?.querySelector("[data-unit-price]");
  const totalPriceOutput = calculator?.querySelector("[data-total-price]");
  const calculatorNote = calculator?.querySelector("[data-calculator-note]");
  const mobileCta = document.querySelector("[data-mobile-cta]");
  const formStartedAt = Date.now();

  document.querySelectorAll("[data-year]").forEach((node) => {
    node.textContent = String(new Date().getFullYear());
  });

  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    if (link.classList.contains("skip-link")) return;
    const hash = link.getAttribute("href");
    if (!hash || hash.length < 2) return;

    link.addEventListener("click", (event) => {
      const target = document.querySelector(hash);
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start"
      });
      if (window.location.hash !== hash) window.history.pushState(null, "", hash);
    });
  });

  function updateActiveSection() {
    if (!navSections.length) return;
    const line = (header?.getBoundingClientRect().height || 0) + Math.min(window.innerHeight * 0.22, 180);
    let activeId = "";

    navSections.forEach((section) => {
      const rect = section.getBoundingClientRect();
      if (rect.top <= line && rect.bottom > line) activeId = section.id;
    });

    navLinks.forEach((link) => {
      if (link.dataset.navSection === activeId) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  function updateScrollState() {
    header?.classList.toggle("is-scrolled", window.scrollY > 18);
    updateActiveSection();
  }

  let scrollFrame = 0;
  const queueScrollUpdate = () => {
    if (scrollFrame) return;
    scrollFrame = window.requestAnimationFrame(() => {
      scrollFrame = 0;
      updateScrollState();
    });
  };
  updateScrollState();
  window.addEventListener("scroll", queueScrollUpdate, { passive: true });
  window.addEventListener("resize", queueScrollUpdate, { passive: true });

  if (hero && heroPhoto && !reducedMotion && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    hero.addEventListener("pointermove", (event) => {
      const rect = hero.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width - 0.5) * -12;
      const y = ((event.clientY - rect.top) / rect.height - 0.5) * -8;
      heroPhoto.style.setProperty("--hero-x", `${x.toFixed(2)}px`);
      heroPhoto.style.setProperty("--hero-y", `${y.toFixed(2)}px`);
    }, { passive: true });
    hero.addEventListener("pointerleave", () => {
      heroPhoto.style.setProperty("--hero-x", "0px");
      heroPhoto.style.setProperty("--hero-y", "0px");
    });
  }

  const revealItems = document.querySelectorAll("[data-reveal]");
  if (reducedMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -8%" });
    revealItems.forEach((item) => observer.observe(item));
  }

  document.querySelectorAll("[data-cta]").forEach((link) => {
    link.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("snowmail:cta", {
        detail: { placement: link.dataset.cta }
      }));
    });
  });

  if (mobileCta) {
    const mobileViewport = window.matchMedia("(max-width: 820px)");
    const heroActions = document.querySelector(".hero__actions");
    const requestSection = document.querySelector("#request");
    const footerCta = document.querySelector(".site-footer__cta");

    const isInViewport = (element) => {
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      return rect.top < window.innerHeight && rect.bottom > 0;
    };

    const updateMobileCta = () => {
      const heroActionVisible = isInViewport(heroActions);
      const requestVisible = isInViewport(requestSection);
      const footerVisible = isInViewport(footerCta);
      const show = mobileViewport.matches && !heroActionVisible && !requestVisible && !footerVisible;
      mobileCta.classList.toggle("is-visible", show);
      mobileCta.setAttribute("aria-hidden", show ? "false" : "true");
      mobileCta.tabIndex = show ? 0 : -1;
    };

    let mobileCtaFrame = 0;
    const queueMobileCtaUpdate = () => {
      if (mobileCtaFrame) return;
      mobileCtaFrame = window.requestAnimationFrame(() => {
        mobileCtaFrame = 0;
        updateMobileCta();
      });
    };

    if ("IntersectionObserver" in window) {
      const ctaObserver = new IntersectionObserver(queueMobileCtaUpdate, { threshold: 0.08 });
      [heroActions, requestSection, footerCta].filter(Boolean).forEach((node) => ctaObserver.observe(node));
    }

    window.addEventListener("scroll", queueMobileCtaUpdate, { passive: true });
    window.addEventListener("resize", queueMobileCtaUpdate, { passive: true });

    if (typeof mobileViewport.addEventListener === "function") {
      mobileViewport.addEventListener("change", updateMobileCta);
    } else {
      mobileViewport.addListener(updateMobileCta);
    }
    updateMobileCta();
  }

  const rubles = new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0
  });

  function formatRubles(value) {
    return rubles.format(value).replace(/\u00a0/g, " ");
  }

  function updateCalculator(rawCount, source) {
    if (!calculator || !groupRange) return;
    const eventData = config.event || {};
    const rangeMin = Number(eventData.calculatorMin || groupRange.min || 10);
    const rangeMax = Number(eventData.calculatorMax || groupRange.max || 30);
    const count = Math.max(rangeMin, Math.round(Number(rawCount) || rangeMin));
    const rangeValue = Math.min(count, rangeMax);
    const threshold = Number(eventData.groupPriceFrom || 15);
    const unitPrice = count >= threshold
      ? Number(eventData.groupPrice || 5500)
      : Number(eventData.basePrice || 6000);
    const progress = ((rangeValue - rangeMin) / Math.max(rangeMax - rangeMin, 1)) * 100;

    groupRange.value = String(rangeValue);
    groupRange.style.setProperty("--range-progress", `${progress}%`);
    if (groupOutput) groupOutput.value = String(count);
    if (unitPriceOutput) unitPriceOutput.textContent = formatRubles(unitPrice);
    if (totalPriceOutput) totalPriceOutput.textContent = formatRubles(count * unitPrice);

    if (calculatorNote) {
      const formatNote = count > threshold ? " Менеджер уточнит формат программы." : "";
      calculatorNote.textContent = `Для группы из ${count} детей цена составляет ${formatRubles(unitPrice)} за ребёнка.${formatNote}`;
    }

    const childrenInput = form?.elements.namedItem("children");
    if (childrenInput && source === "range") childrenInput.value = String(count);
  }

  if (groupRange) {
    updateCalculator(groupRange.value, "init");
    groupRange.addEventListener("input", () => updateCalculator(groupRange.value, "range"));
  }

  function captureAttribution() {
    const keys = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];
    const query = new URLSearchParams(window.location.search);
    let saved = {};

    try {
      saved = JSON.parse(sessionStorage.getItem("snowMailAttribution") || "{}");
    } catch (_) {
      saved = {};
    }

    keys.forEach((key) => {
      if (!saved[key] && query.get(key)) saved[key] = query.get(key);
    });
    if (!saved.referrer) saved.referrer = document.referrer || "direct";

    try {
      sessionStorage.setItem("snowMailAttribution", JSON.stringify(saved));
    } catch (_) {
      // The form remains usable when storage is unavailable.
    }

    keys.forEach((key) => {
      const input = form?.elements.namedItem(key);
      if (input) input.value = saved[key] || "";
    });
    if (form?.elements.namedItem("page_url")) form.elements.namedItem("page_url").value = window.location.href;
    if (form?.elements.namedItem("referrer")) form.elements.namedItem("referrer").value = saved.referrer || "direct";
  }

  function createRequestId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();

    const bytes = new Uint8Array(16);
    if (window.crypto?.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] = Math.floor(Math.random() * 256);
      }
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }

  function serializeForm(target) {
    const data = new FormData(target);
    return {
      ...Object.fromEntries(data.entries()),
      consent: data.has("consent"),
      request_id: createRequestId(),
      elapsed_ms: Date.now() - formStartedAt
    };
  }

  function setStatus(message, state) {
    if (!status) return;
    status.textContent = message;
    status.dataset.state = state || "";
  }

  async function submitLead(payload) {
    if (!config.formEndpoint) {
      try {
        localStorage.setItem("snowMailLastLead", JSON.stringify({ ...payload, savedAt: new Date().toISOString() }));
      } catch (_) {
        // Demo success does not depend on storage.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      return { demo: true };
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(config.formEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(`HTTP ${response.status}`);
      return { demo: false, leadId: body.leadId || null };
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function trackLeadSuccess() {
    try {
      window._tmr = window._tmr || [];
      window._tmr.push({ type: "reachGoal", id: 3794718, goal: "lead-success" });
    } catch (_) {
      // Analytics must not affect the form result.
    }

    try {
      if (typeof window.ym === "function") {
        window.ym(107188789, "reachGoal", "snezhnaya_pochta_form_success");
      }
    } catch (_) {
      // Analytics must not affect the form result.
    }
  }

  if (form) {
    captureAttribution();

    const childrenInput = form.elements.namedItem("children");
    childrenInput?.addEventListener("input", () => updateCalculator(childrenInput.value, "form"));
    form.addEventListener("reset", () => window.setTimeout(() => updateCalculator(15, "init"), 0));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      setStatus("", "");

      if (!form.checkValidity()) {
        form.reportValidity();
        setStatus("Заполните обязательные поля.", "error");
        return;
      }

      const button = form.querySelector("button[type='submit']");
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = "Отправляем…";
      form.setAttribute("aria-busy", "true");

      try {
        const result = await submitLead(serializeForm(form));
        if (result.demo) {
          setStatus("Пока заявки не принимаются. Скоро здесь можно будет записаться на квест.", "error");
        } else {
          setStatus("Заявка отправлена. Менеджер свяжется с вами, чтобы подтвердить дату и детали.", "success");
          window.dispatchEvent(new CustomEvent("snowmail:lead-success", {
            detail: { leadId: result.leadId }
          }));
          window.dataLayer = window.dataLayer || [];
          window.dataLayer.push({
            event: "snow_mail_lead_success",
            form_id: "lead-form",
            lead_id: result.leadId
          });
          trackLeadSuccess();
          form.reset();
          captureAttribution();
        }
      } catch (error) {
        setStatus("Не удалось отправить заявку. Попробуйте ещё раз.", "error");
      } finally {
        button.disabled = false;
        button.textContent = originalText;
        form.removeAttribute("aria-busy");
      }
    });
  }
})();
