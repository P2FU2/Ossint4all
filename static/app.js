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
    window.renderConsultGraphs(event.detail && event.detail.target);
  });
})();

(function consultGraphs() {
  const KIND_COLOR = {
    org: "#ffe14a",
    person: "#5eead4",
    profile: "#b8ff57",
    vehicle: "#00ff9c",
    email: "#5eead4",
    owner: "#ff5c7a",
  };

  function draw(el) {
    const raw = el.getAttribute("data-graph");
    if (!raw) return;
    let data;
    try {
      data = JSON.parse(raw);
    } catch (_) {
      return;
    }
    const nodes = data.nodes || [];
    const edges = data.edges || [];
    if (!nodes.length) return;
    const w = el.clientWidth || 640;
    const h = el.clientHeight || 320;
    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.max(70, Math.min(w, h) / 2 - 48);
    const pos = {};
    nodes.forEach((node, idx) => {
      if (idx === 0) {
        pos[node.id] = { x: cx, y: cy };
        return;
      }
      const angle = ((idx - 1) / Math.max(nodes.length - 1, 1)) * Math.PI * 2 - Math.PI / 2;
      pos[node.id] = { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius };
    });
    const lines = edges
      .map((edge) => {
        const a = pos[edge.source];
        const b = pos[edge.target];
        if (!a || !b) return "";
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="rgba(0,255,156,0.35)" />` +
          (edge.label ? `<text x="${mx}" y="${my - 6}" fill="#5f8f6e" font-size="9" text-anchor="middle">${escapeXml(edge.label)}</text>` : "");
      })
      .join("");
    const dots = nodes
      .map((node) => {
        const p = pos[node.id];
        if (!p) return "";
        const fill = KIND_COLOR[node.kind] || "#00ff9c";
        const label = String(node.label || node.id).slice(0, 28);
        return `<circle cx="${p.x}" cy="${p.y}" r="${node === nodes[0] ? 10 : 7}" fill="${fill}" stroke="#020604" stroke-width="2" />` +
          `<text x="${p.x}" y="${p.y + 22}" fill="#c8ffd4" font-size="10" text-anchor="middle">${escapeXml(label)}</text>`;
      })
      .join("");
    el.innerHTML = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="presentation">${lines}${dots}</svg>`;
  }

  function escapeXml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  window.renderConsultGraphs = (root) => {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-graph]").forEach(draw);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => window.renderConsultGraphs(document));
  } else {
    window.renderConsultGraphs(document);
  }
})();
