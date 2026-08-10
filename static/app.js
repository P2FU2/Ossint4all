/* Helpers mínimos do painel */
function csrfFromMeta() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") || "" : "";
}

function syncFormCsrf(form) {
  if (!(form instanceof HTMLFormElement)) return;
  const token = csrfFromMeta();
  if (!token) return;
  let input = form.querySelector('input[name="csrf_token"]');
  if (!input) {
    input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    form.appendChild(input);
  }
  input.value = token;
}

document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-confirm]");
  if (!el) return;
  const msg = el.getAttribute("data-confirm") || "Confirmar ação?";
  if (!window.confirm(msg)) {
    ev.preventDefault();
    ev.stopImmediatePropagation();
  }
});

/* Garante CSRF válido mesmo se o macro Jinja/HTMX deixou o campo vazio */
document.addEventListener(
  "submit",
  (ev) => {
    const form = ev.target;
    if (form instanceof HTMLFormElement) syncFormCsrf(form);
  },
  true
);

document.body.addEventListener("htmx:afterSwap", (ev) => {
  const root = ev.detail && ev.detail.elt;
  if (!root || !root.querySelector) return;
  const fresh = root.querySelector('input[name="csrf_token"]');
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (fresh && fresh.value && meta) {
    meta.setAttribute("content", fresh.value);
  }
});

/* Tooltips em position:fixed — evitam corte por overflow dos cards */
(function () {
  let balloon = null;
  let activeTip = null;
  let pinned = false; // toque/click: mantém aberto até fora

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
    activeTip = null;
    pinned = false;
  }

  function placeBalloon(tipEl) {
    const el = ensureBalloon();
    const rect = tipEl.getBoundingClientRect();
    const margin = 12;
    const gap = 10;
    const bw = el.offsetWidth;
    const bh = el.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let left = rect.left + rect.width / 2 - bw / 2;
    left = Math.max(margin, Math.min(left, vw - bw - margin));

    // Prefere acima; se não couber, abaixo; se ainda apertado no mobile, abaixo com clamp
    let top = rect.top - bh - gap;
    let place = "above";
    if (top < margin) {
      top = rect.bottom + gap;
      place = "below";
    }
    if (top + bh > vh - margin) {
      top = Math.max(margin, Math.min(rect.top - bh - gap, vh - bh - margin));
      place = top < rect.top ? "above" : "below";
    }
    el.dataset.place = place;
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
  }

  function show(tipEl, { pin = false } = {}) {
    const text = tipEl.getAttribute("data-tip");
    if (!text) return;
    const el = ensureBalloon();
    el.textContent = text;
    el.classList.add("is-visible");
    activeTip = tipEl;
    pinned = pin;
    // medir após pintar
    requestAnimationFrame(() => placeBalloon(tipEl));
  }

  document.addEventListener("mouseover", (ev) => {
    const tip = ev.target.closest(".tip[data-tip]");
    if (!tip || pinned) return;
    show(tip);
  });
  document.addEventListener("mouseout", (ev) => {
    if (pinned) return;
    const tip = ev.target.closest(".tip[data-tip]");
    if (!tip) return;
    const to = ev.relatedTarget;
    if (to && tip.contains(to)) return;
    hide();
  });
  document.addEventListener("focusin", (ev) => {
    const tip = ev.target.closest(".tip[data-tip]");
    if (tip) show(tip, { pin: true });
  });
  document.addEventListener("focusout", (ev) => {
    const tip = ev.target.closest(".tip[data-tip]");
    if (!tip) return;
    const to = ev.relatedTarget;
    if (to && tip.contains(to)) return;
    hide();
  });

  // Toque / click: tip ao lado do botão não dispara o submit
  document.addEventListener(
    "click",
    (ev) => {
      const tip = ev.target.closest(".tip[data-tip]");
      if (tip) {
        ev.preventDefault();
        ev.stopPropagation();
        if (activeTip === tip && pinned) {
          hide();
        } else {
          show(tip, { pin: true });
        }
        return;
      }
      if (pinned && balloon && !balloon.contains(ev.target)) {
        hide();
      }
    },
    true
  );

  window.addEventListener(
    "scroll",
    () => {
      if (activeTip && pinned) {
        placeBalloon(activeTip);
      } else {
        hide();
      }
    },
    true
  );
  window.addEventListener("resize", () => {
    if (activeTip) placeBalloon(activeTip);
    else hide();
  });
})();

/* Duração/ETA ao vivo entre refreshes HTMX (a cada 1s) */
(function () {
  function formatDuration(secs) {
    secs = Math.max(0, Math.floor(secs));
    if (secs < 60) return secs + "s";
    const mins = Math.floor(secs / 60);
    const s = secs % 60;
    if (mins < 60) return mins + "m " + s + "s";
    const hours = Math.floor(mins / 60);
    const m = mins % 60;
    return hours + "h " + m + "m";
  }

  function tickLiveProgress() {
    const cards = document.querySelectorAll("[data-live-progress='1'][data-started-at]");
    const wallNow = Date.now();
    cards.forEach((card) => {
      const started = Date.parse(card.getAttribute("data-started-at") || "");
      if (!Number.isFinite(started)) return;
      const durEl = card.querySelector(".js-live-duration");
      if (durEl) durEl.textContent = formatDuration((wallNow - started) / 1000);

      const etaRaw = card.getAttribute("data-eta-seconds");
      const etaEl = card.querySelector(".js-live-eta");
      if (!etaEl || etaRaw === null || etaRaw === "") return;
      const etaBase = parseFloat(etaRaw);
      if (!Number.isFinite(etaBase)) {
        etaEl.textContent = "—";
        return;
      }
      // Compensa skew: usa instante do HTML do servidor como âncora
      const serverNow = Date.parse(card.getAttribute("data-server-now") || "");
      const anchor = Number.isFinite(serverNow) ? serverNow : wallNow;
      const remaining = etaBase - (wallNow - anchor) / 1000;
      etaEl.textContent = remaining <= 0 ? "0s" : formatDuration(remaining);
    });
  }

  setInterval(tickLiveProgress, 1000);
  document.body.addEventListener("htmx:afterSwap", tickLiveProgress);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tickLiveProgress);
  } else {
    tickLiveProgress();
  }
})();
