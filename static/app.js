function escapeHtml(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
window.escapeHtml = escapeHtml;

function setActionStatus(phase, message) {
  const bar = document.getElementById("action-status");
  if (!bar || !message) return;
  const clean = String(message).replace(/[.…]+$/u, "").trim();
  if (!clean) return;
  bar.hidden = false;
  bar.classList.remove("is-loading", "is-ok", "is-error");
  const kind = phase === "error" ? "is-error" : phase === "ok" ? "is-ok" : "is-loading";
  bar.classList.add(kind);
  if (kind === "is-loading") {
    bar.innerHTML = `${escapeHtml(clean)}<span class="status-dots" aria-hidden="true"><i></i><i></i><i></i></span>`;
    try {
      sessionStorage.setItem("osint-status", JSON.stringify({ message: clean, t: Date.now() }));
    } catch (_) { /* ignore quota */ }
  } else {
    bar.textContent = clean;
    try {
      sessionStorage.removeItem("osint-status");
    } catch (_) { /* ignore */ }
  }
}
window.setActionStatus = setActionStatus;

function formAction(form) {
  if (!(form instanceof HTMLFormElement)) return "";
  const submitter = form.querySelector("button[formaction], input[formaction]");
  return (form.getAttribute("action") || (submitter && submitter.getAttribute("formaction")) || "");
}

function busyLabel(form) {
  if (form instanceof HTMLFormElement && form.dataset.busy) return form.dataset.busy;
  const action = formAction(form);
  if (action.includes("/nova") || action.includes("/grafo")) return "Criando caso…";
  if (action.includes("/explodir")) return "Explodindo QSA…";
  if (action.includes("/processar")) return "Processando fila…";
  if (action.includes("/expandir")) return "Expandindo nó…";
  if (action.includes("/consultar")) return "Consultando…";
  if (action.includes("/ferramentas")) return "Buscando…";
  if (action.includes("/alvo")) return "Buscando nesta camada…";
  if (action.includes("/desligar") || action.includes("/apagar")) return "Removendo…";
  if (action.includes("/notas")) return "Gravando anotação…";
  if (action.includes("/ligacoes")) return "Gravando ligação…";
  return "Carregando…";
}

function doneLabel(form, ok) {
  if (!ok) return "Falha. Tente de novo.";
  if (form instanceof HTMLFormElement && form.dataset.done) return form.dataset.done;
  const action = formAction(form);
  if (action.includes("/nova") || action.includes("/grafo")) return "Caso criado.";
  if (action.includes("/consultar")) return "Consulta concluída.";
  if (action.includes("/ferramentas")) return "Ferramenta concluída.";
  if (action.includes("/alvo")) return "Camada carregada.";
  if (action.includes("/historico")) return "Histórico atualizado.";
  if (action.includes("/cadeia")) return "Cadeia atualizada.";
  return "Concluído.";
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const csrf = document.querySelector('meta[name="csrf-token"]');
  if (csrf && !form.querySelector('input[name="csrf_token"]')) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = csrf.getAttribute("content") || "";
    form.appendChild(input);
  }
  if (form.dataset.silent === "1") return;
  const label = busyLabel(form);
  setActionStatus("loading", label);
  form.classList.add("is-busy");
  const btn = event.submitter instanceof HTMLButtonElement
    ? event.submitter
    : form.querySelector("button[type=submit], button:not([type])");
  if (btn && !btn.dataset.locked) {
    btn.dataset.locked = "1";
    btn.dataset.original = btn.textContent || "";
    btn.textContent = label;
  }
});

document.body.addEventListener("htmx:beforeRequest", (event) => {
  const form = event.target && event.target.closest ? event.target.closest("form") : event.target;
  const label = form instanceof HTMLFormElement ? busyLabel(form) : "Carregando…";
  setActionStatus("loading", label);
});
document.body.addEventListener("htmx:afterRequest", (event) => {
  const form = event.target && event.target.closest ? event.target.closest("form") : event.target;
  const ok = !event.detail || event.detail.successful !== false;
  setActionStatus(ok ? "ok" : "error", doneLabel(form, ok));
});
document.body.addEventListener("htmx:sendError", () => {
  setActionStatus("error", "Falha de rede. Tente de novo.");
});

window.addEventListener("pageshow", () => {
  let saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem("osint-status") || "null");
  } catch (_) {
    saved = null;
  }
  const cy = document.getElementById("cy");
  if (cy && cy.dataset.statusInit) {
    setActionStatus(cy.dataset.statusPhase || "ok", cy.dataset.statusInit);
    return;
  }
  if (!saved || Date.now() - (saved.t || 0) > 30000) return;
  setActionStatus("ok", "Caso criado.");
});

(function tips() {
  const tip = document.getElementById("tooltip");
  if (!tip) return;
  let active = null;
  let hideTimer = 0;

  function hide() {
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      tip.hidden = true;
      active = null;
    }, 120);
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
    window.clearTimeout(hideTimer);
    const extra = el.classList.contains("inspect-hint") || el.classList.contains("inspect-open") ? " · clique para a ficha" : "";
    tip.textContent = text + extra;
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
  tip.addEventListener("pointerenter", () => window.clearTimeout(hideTimer));
  tip.addEventListener("pointerleave", hide);

  window.showAppTip = (text, x, y) => {
    window.clearTimeout(hideTimer);
    tip.textContent = text;
    tip.hidden = false;
    active = tip;
    place(x, y);
  };
  window.hideAppTip = hide;

  tip.addEventListener("click", (event) => {
    event.preventDefault();
    const text = tip.textContent || "";
    const from = active && active !== tip ? active : null;
    hide();
    if (window.openInspect) {
      window.openInspect({
        title: from ? (from.textContent || "").trim().slice(0, 80) || "hint" : "hint",
        kind: "hint",
        meta: text,
        url: "",
        when: "",
      });
    }
  });
})();

(function inspectPanel() {
  const overlay = document.getElementById("inspect-modal");
  const titleEl = document.getElementById("inspect-title");
  const kindEl = document.getElementById("inspect-kind");
  const metaEl = document.getElementById("inspect-meta");
  const factsEl = document.getElementById("inspect-facts");
  const listsEl = document.getElementById("inspect-lists");
  const actionsEl = document.getElementById("inspect-actions");
  const closeBtn = document.getElementById("inspect-close");
  const shell = document.querySelector(".app-shell");
  let lastFocus = null;
  if (!overlay || !titleEl || !actionsEl) return;

  const KIND_LABEL = {
    fonte: "Fonte",
    perfil: "Perfil",
    link: "Endereço",
    socio: "Sócio",
    empresa: "Empresa",
    sancao: "Sanção",
    processo: "Processo",
    diario: "Diário",
    mencao: "Menção",
    relacionada: "Relacionada",
    item: "Item",
    host: "Host",
    fato: "Fato",
    evento: "Evento",
    event: "Evento",
    hint: "Hint",
    achado: "Achado da cadeia",
    social: "Rede",
    web: "Menção web",
    id: "Identificador",
    org: "Organização",
    owner: "Dono citado",
    vehicle: "Veículo",
    plate: "Placa",
    alert: "Alerta",
    node: "Nó da árvore",
    noticia: "Notícia",
    imagem: "Imagem",
  };
  const KIND_WHY = {
    fonte: "Portal ou registro público citado nesta consulta. Não é acesso privilegiado.",
    perfil: "URL canônica pública. HTTP 200 não prova que a conta é da pessoa.",
    link: "Endereço público apontado pelo conector. Não abre fora do painel.",
    hint: "Texto de ajuda da interface. Não é um dado coletado na fonte.",
    fato: "Campo estruturado desta consulta. Pode virar nova busca no painel.",
    mencao: "Trecho público onde o identificador apareceu.",
    processo: "Comunicação, capa ou menção processual pública. Não é o inteiro teor do tribunal.",
    diario: "Publicação em diário oficial ou DJEN. Não substitui certidão.",
    sancao: "Registro em lista oficial (CEIS, CNEP, TCU) ou menção de condenação em fonte .gov.",
    social: "Rede ou perfil público derivado do identificador.",
    web: "Menção em busca pública. Título não é prova.",
    achado: "Item acumulado na cadeia de consultas relacionadas.",
    node: "Entidade da árvore desta consulta.",
    noticia: "Matéria ou menção em busca pública. Título não é prova nem confirma o alvo.",
    imagem: "Miniatura pública. Não é foto oficial nem prova de identidade.",
  };

  function parsePayload(raw) {
    if (!raw) return null;
    if (typeof raw === "object") return raw;
    try {
      return JSON.parse(raw);
    } catch (_) {
      return { title: String(raw), kind: "item", meta: "", url: "", when: "" };
    }
  }

  function guessSeed(...parts) {
    const text = parts.filter(Boolean).join(" ");
    const email = text.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
    if (email) return { modo: "EMAIL", q: email[0] };
    const at = text.match(/(^|[\s>])@([A-Za-z0-9._-]{2,32})\b/);
    if (at) return { modo: "USERNAME", q: "@" + at[2] };
    const gh = text.match(/github\.com\/([A-Za-z0-9._-]{2,32})/i);
    if (gh) return { modo: "USERNAME", q: "@" + gh[1] };
    const plate = text.match(/\b[A-Z]{3}-?\d[A-Z0-9]\d{2}\b/i);
    if (plate) return { modo: "PLATE", q: plate[0].toUpperCase() };
    const cnpj = text.match(/\b\d{2}\.?\d{3}\.?\d{3}\/?0001-?\d{2}\b/) || text.match(/\b\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2}\b/);
    if (cnpj && cnpj[0].replace(/\D/g, "").length === 14) return { modo: "CNPJ", q: cnpj[0] };
    const cpf = text.match(/\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/);
    if (cpf && cpf[0].replace(/\D/g, "").length === 11) return { modo: "CPF", q: cpf[0] };
    return null;
  }

  function hostOf(url) {
    try {
      return new URL(url, window.location.origin).hostname.replace(/^www\./, "");
    } catch (_) {
      return "";
    }
  }

  function copyText(text) {
    const value = text || "";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).catch(() => {});
      return;
    }
    const box = document.createElement("textarea");
    box.value = value;
    document.body.appendChild(box);
    box.select();
    document.execCommand("copy");
    box.remove();
  }

  function fillSearch(q, modo) {
    const input = document.getElementById("q");
    if (input) input.value = q;
    document.querySelectorAll(".consult-form input[name=modo]").forEach((radio) => {
      radio.checked = radio.value === modo;
    });
  }

  function runConsult(q, modo) {
    fillSearch(q, modo);
    close();
    const form = document.querySelector("form.consult-form[action='/app/consultar'], form.consult-form[hx-post='/app/consultar']");
    if (form) {
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
      return;
    }
    const csrf = document.querySelector('meta[name="csrf-token"]');
    const target = document.querySelector(".consult-result");
    if (window.htmx && csrf && target) {
      window.htmx.ajax("POST", "/app/consultar", {
        target,
        swap: "innerHTML",
        values: { csrf_token: csrf.getAttribute("content") || "", q, modo },
      });
      return;
    }
    window.location.assign("/app?modo=" + encodeURIComponent(modo) + "&q=" + encodeURIComponent(q));
  }

  function fact(label, value) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    const text = String(value || "").trim();
    dt.textContent = label;
    dd.textContent = !text || text === "—" || text === "None" ? "não informado" : text;
    wrap.append(dt, dd);
    return wrap;
  }

  function asPairs(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) {
      return raw
        .map((item) => (Array.isArray(item) ? [item[0], item[1]] : [item.label || item[0], item.value || item[1]]))
        .filter((item) => item[0]);
    }
    return Object.entries(raw);
  }

  function renderList(title, items) {
    if (!listsEl || !items || !items.length) return;
    const kicker = document.createElement("p");
    kicker.className = "section-kicker";
    kicker.textContent = title;
    const ul = document.createElement("ul");
    ul.className = "inspect-list";
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = typeof item === "string" ? item : [item.name, item.papel, item.meta].filter(Boolean).join(" · ");
      ul.appendChild(li);
    });
    listsEl.append(kicker, ul);
  }

  function action(label, onClick, primary) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = primary ? "btn primary" : "btn";
    btn.textContent = label;
    btn.addEventListener("click", onClick);
    return btn;
  }

  function paintFacts(data) {
    const title = String(data.title || "ficha").trim() || "ficha";
    const kind = String(data.kind || "item");
    const meta = String(data.meta || "");
    const url = String(data.url || "");
    const when = String(data.when || "");
    const seed = guessSeed(title, meta, url, ...(asPairs(data.facts).map((pair) => pair[1])));
    titleEl.textContent = title;
    kindEl.textContent = KIND_LABEL[kind] || kind || "ficha";
    metaEl.textContent = meta || KIND_WHY[kind] || "Detalhe desta fonte, sem sair do painel.";
    factsEl.replaceChildren();
    factsEl.appendChild(fact("tipo", KIND_LABEL[kind] || kind));
    if (when) factsEl.appendChild(fact("data da consulta", when));
    asPairs(data.facts).forEach(([label, value]) => {
      if (!label) return;
      if (when && String(label).toLowerCase() === "data da consulta") return;
      factsEl.appendChild(fact(label, value));
    });
    if (url) {
      factsEl.appendChild(fact("endereço", url));
      const host = hostOf(url);
      if (host) factsEl.appendChild(fact("host", host));
    }
    if (data.error) factsEl.appendChild(fact("fonte", data.error));
    factsEl.appendChild(fact("leitura", KIND_WHY[kind] || "Item interno da consulta. Clique nas ações abaixo."));
    if (seed) factsEl.appendChild(fact("consultável", seed.q + " · " + seed.modo));
    if (listsEl) listsEl.replaceChildren();
    const thumb = String(data.thumb || "").trim();
    if (listsEl && thumb.startsWith("http")) {
      const kicker = document.createElement("p");
      kicker.className = "section-kicker";
      kicker.textContent = "miniatura pública";
      const img = document.createElement("img");
      img.className = "inspect-thumb";
      img.src = thumb;
      img.alt = title;
      img.referrerPolicy = "no-referrer";
      listsEl.append(kicker, img);
    }
    renderList("sócios / QSA", data.socios || []);
    renderList("participações", data.participacoes || []);
    return { title, kind, meta, url, when, seed };
  }

  function openInspect(raw) {
    const data = parsePayload(raw) || {};
    if (window.hideAppTip) window.hideAppTip();
    const painted = paintFacts(data);
    const lines = [painted.title, painted.kind, painted.meta, painted.when, painted.url]
      .concat(asPairs(data.facts).map((pair) => pair[0] + ": " + pair[1]))
      .concat(data.socios || [])
      .concat(data.participacoes || [])
      .filter(Boolean);
    actionsEl.replaceChildren();
    actionsEl.appendChild(action("copiar título", () => copyText(painted.title)));
    if (painted.url) actionsEl.appendChild(action("copiar URL", () => copyText(painted.url)));
    actionsEl.appendChild(action("copiar ficha", () => copyText(lines.join("\n"))));
    if (painted.seed) {
      actionsEl.appendChild(action("consultar isto", () => runConsult(painted.seed.q, painted.seed.modo), true));
      actionsEl.appendChild(action("colocar no campo", () => {
        fillSearch(painted.seed.q, painted.seed.modo);
        close();
        const input = document.getElementById("q");
        if (input) input.focus();
      }));
    }
    lastFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    overlay.hidden = false;
    overlay.setAttribute("aria-hidden", "false");
    if (shell) shell.setAttribute("aria-hidden", "true");
    document.body.classList.add("inspect-open-body");
    if (closeBtn) closeBtn.focus();
    if (painted.seed && painted.seed.modo === "CNPJ" && !data.enriched) {
      factsEl.appendChild(fact("ficha oficial", "buscando na Receita…"));
      fetch("/app/ficha.json?q=" + encodeURIComponent(painted.seed.q) + "&modo=CNPJ")
        .then((resp) => (resp.ok ? resp.json() : Promise.reject()))
        .then((ficha) => {
          if (overlay.hidden) return;
          paintFacts({
            title: ficha.title || painted.title,
            kind: ficha.kind || "empresa",
            meta: ficha.meta || painted.meta,
            url: painted.url,
            when: painted.when || (ficha.facts && ficha.facts[0] && ficha.facts[0][1]) || "",
            facts: ficha.facts || [],
            socios: ficha.socios || [],
            participacoes: ficha.participacoes || data.participacoes || [],
            error: ficha.error || "",
            enriched: true,
          });
        })
        .catch(() => {
          if (!overlay.hidden) factsEl.appendChild(fact("ficha oficial", "indisponível nesta passagem"));
        });
    }
  }

  function close() {
    overlay.hidden = true;
    overlay.setAttribute("aria-hidden", "true");
    if (shell) shell.removeAttribute("aria-hidden");
    document.body.classList.remove("inspect-open-body");
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
    lastFocus = null;
  }

  window.openInspect = openInspect;

  closeBtn && closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  document.addEventListener("keydown", (event) => {
    if (overlay.hidden) return;
    if (event.key === "Escape") {
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusables = [...overlay.querySelectorAll("button")];
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  document.addEventListener("click", (event) => {
    const ext = event.target.closest("a[href]");
    if (ext) {
      const href = ext.getAttribute("href") || "";
      if (/^https?:/i.test(href) || href.startsWith("//")) {
        event.preventDefault();
        event.stopPropagation();
        openInspect({
          title: (ext.textContent || "").trim() || "fonte",
          kind: "fonte",
          meta: ext.getAttribute("data-tip") || "Link externo bloqueado. Use copiar URL se precisar do endereço.",
          url: ext.href,
          when: "",
        });
        return;
      }
    }
    const node = event.target.closest(".tree-node");
    if (node) {
      event.preventDefault();
      const packed = node.getAttribute("data-inspect");
      if (packed) {
        openInspect(packed);
      } else {
        openInspect({
          title: node.getAttribute("data-title") || "nó",
          kind: node.getAttribute("data-kind") || "node",
          meta: node.getAttribute("data-meta") || "",
          url: node.getAttribute("data-url") || "",
          when: "",
        });
      }
      return;
    }
    const source = event.target.closest("[data-inspect]");
    if (source) {
      event.preventDefault();
      openInspect(source.getAttribute("data-inspect"));
      return;
    }
    const hint = event.target.closest(".inspect-hint, .tree-caption, .tree-key, .tree-reads li");
    if (hint && !hint.closest("#inspect-modal")) {
      event.preventDefault();
      openInspect({
        title: (hint.textContent || "").trim().slice(0, 90) || "hint",
        kind: "hint",
        meta: hint.getAttribute("data-tip") || (hint.textContent || "").trim(),
        url: "",
        when: "",
      });
    }
  }, true);
})();

(function chainAndHistoryUX() {
  document.body.addEventListener("input", (event) => {
    const box = event.target;
    if (!box || box.id !== "history-search") return;
    const needle = box.value.trim().toLowerCase();
    document.querySelectorAll(".history-list li[data-search]").forEach((row) => {
      const hay = row.getAttribute("data-search") || "";
      row.hidden = Boolean(needle) && !hay.includes(needle);
    });
  });
  document.body.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-chain-export]");
    if (!btn) return;
    const area = btn.parentElement && btn.parentElement.querySelector(".chain-export");
    const text = area ? area.value : "";
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => {});
    }
    btn.textContent = "copiado";
    window.setTimeout(() => {
      btn.textContent = "copiar fio";
    }, 1200);
  });
})();

(function consultUX() {
  const input = document.getElementById("q");
  if (!input) return;
  const hint = document.getElementById("consult-hint");

  function applyMode(chip) {
    const ph = chip && chip.getAttribute("data-ph");
    const tip = chip && chip.getAttribute("data-tip");
    if (ph) input.placeholder = ph;
    if (hint && tip) {
      hint.textContent = tip + " · Enter consulta · / foca o campo";
      hint.setAttribute("data-tip", tip);
    }
  }

  function syncFromHistory(form) {
    const qVal = form.querySelector('[name="q"]');
    const mVal = form.querySelector('[name="modo"]');
    if (qVal) input.value = qVal.value;
    if (!mVal) return;
    document.querySelectorAll(".consult-form input[name=modo]").forEach((radio) => {
      radio.checked = radio.value === mVal.value;
      if (radio.checked) applyMode(radio.closest(".mode-chip"));
    });
  }

  document.body.addEventListener("submit", (event) => {
    const form = event.target;
    if (form && form.classList && form.classList.contains("history-replay")) {
      syncFromHistory(form);
    }
  });

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

  document.body.addEventListener("htmx:timeout", (event) => {
    const target = (event.detail && event.detail.target) || document.getElementById("consult-result") || document.getElementById("tool-result");
    if (target) {
      target.innerHTML = "<div class='result-banner error' role='alert'>A busca em massa passou de 45s. Tente de novo com um único identificador, ou use o tipo específico (e-mail, CPF, CNPJ).</div>";
    }
  });
  document.body.addEventListener("htmx:responseError", (event) => {
    const target = (event.detail && event.detail.target) || document.getElementById("consult-result") || document.getElementById("tool-result");
    if (target) {
      target.innerHTML = "<div class='result-banner error' role='alert'>A busca falhou no servidor. Confira o valor e tente outra vez.</div>";
    }
  });
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
    window.renderConsultGraphs(document.getElementById("consult-chain"));
    const chainMark = document.querySelector(".flow-rail li:nth-child(4)");
    if (chainMark && document.querySelector(".chain-box.is-linked")) {
      chainMark.classList.remove("is-next");
      chainMark.classList.add("is-now");
    }
  });
  document.body.addEventListener("htmx:oobAfterSwap", (event) => {
    window.renderConsultGraphs(event.detail && event.detail.target);
  });
})();

(function consultGraphs() {
  const KIND = {
    email: { title: "E-mail", hint: "Identificador consultado" },
    profile: { title: "Perfil", hint: "URL pública (HTTP 200)" },
    org: { title: "Empresa", hint: "Pessoa jurídica / QSA" },
    person: { title: "Pessoa", hint: "Sócio, titular ou menção" },
    vehicle: { title: "Veículo", hint: "Placa ou modelo citado" },
    owner: { title: "Pessoa", hint: "Possível proprietário" },
  };
  const REL = {
    "deriva @user": "O local-part do e-mail foi testado como username.",
    deriva: "Identificador derivado do valor consultado.",
    "perfil público": "URL canônica pública respondeu HTTP 200.",
    perfil: "URL canônica pública respondeu HTTP 200.",
    identidade: "Avatar público ligado ao hash do e-mail.",
    avatar: "Avatar público ligado ao hash do e-mail.",
    "sócio no QSA": "Consta no quadro societário público da Receita.",
    sócio: "Consta no quadro societário público da Receita.",
    "sócio PJ": "Empresa figura como sócia pessoa jurídica.",
    "também sócio": "A mesma pessoa aparece no QSA de outra empresa.",
    "possível dono": "Nome extraído de texto público — não é o DETRAN.",
    modelo: "Marca/modelo citados no mesmo trecho que a placa.",
    menciona: "Menção pública no mesmo documento.",
  };
  const CARD_W = 188;
  const CARD_H = 58;
  const GAP_X = 22;
  const GAP_Y = 86;

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

    const byId = {};
    nodes.forEach((n) => {
      byId[n.id] = n;
    });
    const outgoing = {};
    const incoming = {};
    nodes.forEach((n) => {
      outgoing[n.id] = [];
      incoming[n.id] = [];
    });
    edges.forEach((e) => {
      if (!byId[e.source] || !byId[e.target]) return;
      outgoing[e.source].push(e);
      incoming[e.target].push(e);
    });
    const root = nodes.find((n) => !(incoming[n.id] || []).length) || nodes[0];
    const children = {};
    const parentOf = {};
    nodes.forEach((n) => {
      children[n.id] = [];
    });
    const seen = new Set([root.id]);
    const queue = [root.id];
    while (queue.length) {
      const id = queue.shift();
      const links = (outgoing[id] || []).concat(incoming[id] || []);
      links.forEach((edge) => {
        const other = edge.source === id ? edge.target : edge.source;
        if (seen.has(other) || !byId[other]) return;
        seen.add(other);
        children[id].push(other);
        parentOf[other] = { id, edge };
        queue.push(other);
      });
    }
    nodes.forEach((n) => {
      if (seen.has(n.id)) return;
      seen.add(n.id);
      children[root.id].push(n.id);
      parentOf[n.id] = { id: root.id, edge: { label: "relacionado", explain: "Vínculo inferido nesta consulta." } };
    });

    const subtree = {};
    function measure(id) {
      const kids = children[id] || [];
      if (!kids.length) {
        subtree[id] = CARD_W;
        return CARD_W;
      }
      const width = kids.reduce((sum, kid, idx) => sum + measure(kid) + (idx ? GAP_X : 0), 0);
      subtree[id] = Math.max(CARD_W, width);
      return subtree[id];
    }
    measure(root.id);

    const pos = {};
    function place(id, left, depth) {
      const kids = children[id] || [];
      const width = subtree[id];
      pos[id] = { x: left + width / 2, y: 28 + depth * (CARD_H + GAP_Y), depth };
      let cursor = left;
      kids.forEach((kid) => {
        place(kid, cursor, depth + 1);
        cursor += subtree[kid] + GAP_X;
      });
    }
    place(root.id, 16, 0);

    const maxDepth = Math.max(0, ...Object.values(pos).map((p) => p.depth));
    const w = Math.max(el.clientWidth || 640, subtree[root.id] + 32);
    const h = 48 + (maxDepth + 1) * (CARD_H + GAP_Y);

    const kindsUsed = [...new Set(nodes.map((n) => n.kind))];
    const lines = Object.keys(parentOf)
      .map((childId) => {
        const link = parentOf[childId];
        const a = pos[link.id];
        const b = pos[childId];
        if (!a || !b) return "";
        const ax = a.x;
        const ay = a.y + CARD_H;
        const bx = b.x;
        const by = b.y;
        const mid = (ay + by) / 2;
        const label = (link.edge && (link.edge.label || "")) || "";
        return (
          `<path d="M ${ax} ${ay} V ${mid} H ${bx} V ${by}" fill="none" stroke="#3d5348" stroke-width="1.2"/>` +
          (label
            ? `<rect x="${(ax + bx) / 2 - 52}" y="${mid - 8}" width="104" height="16" rx="2" fill="#0b120f"/>` +
              `<text x="${(ax + bx) / 2}" y="${mid + 3}" text-anchor="middle" class="tree-edge">${escapeXml(label)}</text>`
            : "")
        );
      })
      .join("");

    const cards = nodes
      .map((node) => {
        const p = pos[node.id];
        if (!p) return "";
        const info = KIND[node.kind] || { title: node.kind, hint: "" };
        const title = String(node.label || node.id);
        const sub = String(node.meta || info.hint || "").slice(0, 42);
        const seed = node.id === root.id ? " is-seed" : "";
        const kindKey = node.kind === "org" ? "empresa" : node.kind === "person" ? "socio" : "node";
        const inspect = escapeXml(
          JSON.stringify({
            title,
            kind: kindKey,
            meta: node.meta || info.hint || "",
            when: data.consulted_at || "",
            facts: node.facts || [],
            socios: node.socios || [],
            participacoes: node.participacoes || [],
          })
        );
        return (
          `<g class="tree-node kind-${escapeXml(node.kind)}${seed}" transform="translate(${p.x - CARD_W / 2},${p.y})" data-title="${escapeXml(title)}" data-meta="${escapeXml(node.meta || info.hint || "")}" data-kind="${kindKey}" data-inspect="${inspect}" style="cursor:pointer">` +
          `<rect width="${CARD_W}" height="${CARD_H}" rx="3"/>` +
          `<text class="tree-kicker" x="10" y="16">${escapeXml(info.title)}</text>` +
          `<text class="tree-title" x="10" y="34">${escapeXml(title.slice(0, 26))}</text>` +
          `<text class="tree-sub" x="10" y="50">${escapeXml(sub)}</text>` +
          `</g>`
        );
      })
      .join("");

    const reads = Object.keys(parentOf)
      .map((childId) => {
        const link = parentOf[childId];
        const from = byId[link.id];
        const to = byId[childId];
        if (!from || !to) return "";
        const why = (link.edge && (link.edge.explain || REL[link.edge.label])) || REL[link.edge && link.edge.label] || "Vínculo encontrado nesta consulta.";
        return `<li><strong>${escapeXml(from.label)}</strong> → <strong>${escapeXml(to.label)}</strong> — ${escapeXml(why)}</li>`;
      })
      .join("");

    const legend = kindsUsed
      .map((kind) => {
        const info = KIND[kind] || { title: kind, hint: "" };
        return `<span class="tree-key kind-${escapeXml(kind)}"><i></i>${escapeXml(info.title)} · ${escapeXml(info.hint)}</span>`;
      })
      .join("");

    const caption = data.caption || "Cada caixa é uma entidade. A linha no meio diz como ela se liga ao alvo.";
    el.classList.add("is-tree");
    el.innerHTML =
      `<p class="tree-caption">${escapeXml(caption)}</p>` +
      `<div class="tree-board"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="Árvore de vínculos">${lines}${cards}</svg></div>` +
      `<div class="tree-key-row">${legend}</div>` +
      (reads ? `<ul class="tree-reads">${reads}</ul>` : "");
  }

  function escapeXml(text) {
    return escapeHtml(text);
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
