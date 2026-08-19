document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const csrf = document.querySelector('meta[name="csrf-token"]');
  if (!csrf) return;
  if (form.querySelector('input[name="csrf_token"]')) return;
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = "csrf_token";
  input.value = csrf.getAttribute("content") || "";
  form.appendChild(input);
});

(function tips() {
  const tip = document.getElementById("tooltip");
  if (!tip) return;
  let active = null;

  function hide() {
    tip.hidden = true;
    active = null;
  }

  function place(x, y) {
    const pad = 12;
    const w = tip.offsetWidth || 240;
    const h = tip.offsetHeight || 40;
    tip.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, x + pad))}px`;
    tip.style.top = `${Math.max(8, Math.min(window.innerHeight - h - 8, y + pad))}px`;
  }

  function show(el, x, y) {
    const text = el.getAttribute("data-tip");
    if (!text) return;
    tip.textContent = text;
    tip.hidden = false;
    active = el;
    place(x, y);
  }

  document.addEventListener("pointerover", (event) => {
    const el = event.target.closest("[data-tip]");
    if (el) show(el, event.clientX, event.clientY);
  });
  document.addEventListener("pointermove", (event) => {
    if (!active || tip.hidden) return;
    if (active.hasAttribute("data-tip")) place(event.clientX, event.clientY);
  });
  document.addEventListener("pointerout", (event) => {
    const el = event.target.closest("[data-tip]");
    if (el && el === active) hide();
  });
  document.addEventListener("focusin", (event) => {
    const el = event.target.closest("[data-tip]");
    if (!el) return;
    const box = el.getBoundingClientRect();
    show(el, box.left, box.bottom);
  });
  document.addEventListener("focusout", hide);
  window.showAppTip = (text, x, y) => {
    tip.textContent = text;
    tip.hidden = false;
    active = tip;
    place(x, y);
  };
  window.hideAppTip = hide;
})();

(function consultUX() {
  const input = document.getElementById("q");
  if (!input) return;
  const hint = document.getElementById("consult-hint");

  function applyMode(chip) {
    const ph = chip && chip.getAttribute("data-ph");
    const tip = chip && chip.getAttribute("data-tip");
    if (ph) input.placeholder = ph;
    if (hint && tip) hint.textContent = tip + " · Enter consulta · / foca o campo";
  }

  document.querySelectorAll(".mode-chip").forEach((chip) => {
    const radio = chip.querySelector("input");
    if (radio && radio.checked) applyMode(chip);
    chip.addEventListener("click", () => applyMode(chip));
    if (radio) radio.addEventListener("change", () => applyMode(chip));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    const tag = (event.target && event.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || event.target.isContentEditable) return;
    event.preventDefault();
    input.focus();
    input.select();
  });

  const caseSearch = document.getElementById("case-search");
  if (caseSearch) {
    caseSearch.addEventListener("input", () => {
      const q = caseSearch.value.trim().toLowerCase();
      document.querySelectorAll(".case-card[data-search]").forEach((card) => {
        const hay = card.getAttribute("data-search") || "";
        card.hidden = Boolean(q) && !hay.includes(q);
      });
    });
  }

  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail && event.detail.target && event.detail.target.id === "consult-result") {
      const empty = document.querySelector(".consult-empty");
      if (empty) empty.remove();
      const now = document.querySelector(".flow-rail li:nth-child(2)");
      const next = document.querySelector(".flow-rail li:nth-child(3)");
      if (now) {
        now.classList.remove("is-now");
        now.classList.add("is-done");
      }
      if (next) {
        next.classList.remove("is-next");
        next.classList.add("is-now");
      }
    }
  });
})();
