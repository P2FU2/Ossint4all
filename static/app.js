/* Helpers mínimos do painel */
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-confirm]");
  if (!el) return;
  const msg = el.getAttribute("data-confirm") || "Confirmar ação?";
  if (!window.confirm(msg)) {
    ev.preventDefault();
    ev.stopImmediatePropagation();
  }
});

/* Tooltips em position:fixed — evitam corte por overflow dos cards */
(function () {
  let balloon = null;

  function ensureBalloon() {
    if (balloon) return balloon;
    balloon = document.createElement("div");
    balloon.className = "tip-balloon";
    balloon.setAttribute("role", "tooltip");
    document.body.appendChild(balloon);
    return balloon;
  }

  function hide() {
    if (!balloon) return;
    balloon.classList.remove("is-visible");
  }

  function show(tipEl) {
    const text = tipEl.getAttribute("data-tip");
    if (!text) return;
    const el = ensureBalloon();
    el.textContent = text;
    el.classList.add("is-visible");

    const rect = tipEl.getBoundingClientRect();
    const margin = 10;
    const bw = el.offsetWidth;
    const bh = el.offsetHeight;

    let left = rect.left + rect.width / 2 - bw / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - bw - margin));

    let top = rect.top - bh - 10;
    let place = "above";
    if (top < margin) {
      top = rect.bottom + 10;
      place = "below";
    }
    el.dataset.place = place;
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
  }

  document.addEventListener("mouseover", (ev) => {
    const tip = ev.target.closest(".tip[data-tip]");
    if (tip) show(tip);
  });
  document.addEventListener("mouseout", (ev) => {
    const tip = ev.target.closest(".tip[data-tip]");
    if (!tip) return;
    const to = ev.relatedTarget;
    if (to && tip.contains(to)) return;
    hide();
  });
  document.addEventListener("focusin", (ev) => {
    const tip = ev.target.closest(".tip[data-tip]");
    if (tip) show(tip);
  });
  document.addEventListener("focusout", (ev) => {
    if (ev.target.closest(".tip[data-tip]")) hide();
  });
  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
})();
