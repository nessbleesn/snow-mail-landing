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
  const form = document.querySelector("#lead-form");
  const status = document.querySelector("#form-status");
  const calculator = document.querySelector("[data-calculator]");
  const groupRange = calculator?.querySelector("[data-group-range]");
  const groupOutput = calculator?.querySelector("[data-group-output]");
  const unitPriceOutput = calculator?.querySelector("[data-unit-price]");
  const totalPriceOutput = calculator?.querySelector("[data-total-price]");
  const calculatorNote = calculator?.querySelector("[data-calculator-note]");

  document.querySelectorAll("[data-year]").forEach((node) => {
    node.textContent = String(new Date().getFullYear());
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

  if (hero && !reducedMotion && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    hero.addEventListener("pointermove", (event) => {
      const rect = hero.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width - 0.5) * -12;
      const y = ((event.clientY - rect.top) / rect.height - 0.5) * -8;
      hero.style.setProperty("--hero-x", `${x.toFixed(2)}px`);
      hero.style.setProperty("--hero-y", `${y.toFixed(2)}px`);
    }, { passive: true });
    hero.addEventListener("pointerleave", () => {
      hero.style.setProperty("--hero-x", "0px");
      hero.style.setProperty("--hero-y", "0px");
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
      calculatorNote.textContent = count > threshold
        ? `Для группы ${count} детей действует базовая цена ${formatRubles(unitPrice)} с ребёнка; формат и итоговые условия подтвердит менеджер.`
        : count === threshold
          ? `Для группы ${threshold}+ действует цена ${formatRubles(unitPrice)} с ребёнка.`
          : `Для группы до ${threshold - 1} детей действует цена ${formatRubles(unitPrice)} с ребёнка.`;
    }

    const childrenInput = form?.elements.namedItem("children");
    if (childrenInput && source !== "form") childrenInput.value = String(count);
  }

  if (groupRange) {
    updateCalculator(groupRange.value, "range");
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

  function serializeForm(target) {
    return Object.fromEntries(new FormData(target).entries());
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return { demo: false };
    } finally {
      window.clearTimeout(timeout);
    }
  }

  if (form) {
    captureAttribution();

    const childrenInput = form.elements.namedItem("children");
    childrenInput?.addEventListener("input", () => updateCalculator(childrenInput.value, "form"));
    form.addEventListener("reset", () => window.setTimeout(() => updateCalculator(15, "reset"), 0));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      setStatus("", "");

      if (!form.checkValidity()) {
        form.reportValidity();
        setStatus("Проверьте обязательные поля — некоторые данные ещё не заполнены.", "error");
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
          setStatus("Спасибо! Заявка сохранена в демо-режиме. Перед публикацией подключим отправку в CRM.", "success");
        } else {
          setStatus("Заявка отправлена. Мы свяжемся с вами, чтобы подтвердить дату и детали.", "success");
          form.reset();
          captureAttribution();
        }
      } catch (error) {
        const message = error.name === "AbortError"
          ? "Сервер отвечает слишком долго. Попробуйте отправить заявку ещё раз."
          : "Не удалось отправить заявку. Проверьте соединение и повторите попытку.";
        setStatus(message, "error");
      } finally {
        button.disabled = false;
        button.textContent = originalText;
        form.removeAttribute("aria-busy");
      }
    });
  }
})();
