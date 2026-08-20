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
    dt.textContent = label;
    dd.textContent = value;
    wrap.append(dt, dd);
    return wrap;
  }

  function action(label, onClick, primary) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = primary ? "btn primary" : "btn";
    btn.textContent = label;
    btn.addEventListener("click", onClick);
    return btn;
  }

  function openInspect(raw) {
    const data = parsePayload(raw) || {};
    const title = String(data.title || "ficha").trim() || "ficha";
    const kind = String(data.kind || "item");
    const meta = String(data.meta || "");
    const url = String(data.url || "");
    const when = String(data.when || "");
    const seed = guessSeed(title, meta, url);
    if (window.hideAppTip) window.hideAppTip();
    titleEl.textContent = title;
    kindEl.textContent = KIND_LABEL[kind] || kind || "ficha";
    metaEl.textContent = meta || KIND_WHY[kind] || "Detalhe desta fonte, sem sair do painel.";
    factsEl.replaceChildren();
    factsEl.appendChild(fact("tipo", KIND_LABEL[kind] || kind));
    if (when) factsEl.appendChild(fact("quando", when));
    if (url) {
      factsEl.appendChild(fact("endereço", url));
      const host = hostOf(url);
      if (host) factsEl.appendChild(fact("host", host));
    }
    factsEl.appendChild(fact("leitura", KIND_WHY[kind] || "Item interno da consulta. Clique nas ações abaixo."));
    if (seed) factsEl.appendChild(fact("consultável", seed.q + " · " + seed.modo));
    actionsEl.replaceChildren();
    actionsEl.appendChild(action("copiar título", () => copyText(title)));
    if (url) actionsEl.appendChild(action("copiar URL", () => copyText(url)));
    actionsEl.appendChild(
      action("copiar ficha", () =>
        copyText([title, kind, meta, when, url].filter(Boolean).join("\n"))
      )
    );
    if (seed) {
      actionsEl.appendChild(action("consultar isto", () => runConsult(seed.q, seed.modo), true));
      actionsEl.appendChild(action("colocar no campo", () => {
        fillSearch(seed.q, seed.modo);
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
      openInspect({
        title: node.getAttribute("data-title") || "nó",
        kind: node.getAttribute("data-kind") || "node",
        meta: node.getAttribute("data-meta") || "",
        url: node.getAttribute("data-url") || "",
        when: "",
      });
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
        return (
          `<g class="tree-node kind-${escapeXml(node.kind)}${seed}" transform="translate(${p.x - CARD_W / 2},${p.y})" data-title="${escapeXml(title)}" data-meta="${escapeXml(node.meta || info.hint || "")}" data-kind="node" style="cursor:pointer">` +
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
      (reads ? `<p class="tree-reads-kicker">Como ler esta árvore</p><ul class="tree-reads">${reads}</ul>` : "");
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
