(function () {
  const root = document.getElementById("cy");
  if (!root || typeof cytoscape === "undefined") return;

  const colors = {
    PERSON: "#5d7a88",
    ORG: "#8a7d55",
    CASE: "#8a5d5d",
    PROFILE: "#5e7a62",
    ASSET: "#4f7a68",
    VEHICLE: "#4f7a68",
    PUBLICATION: "#6a7a70",
    NOTE: "#b8a15a",
  };

  const UF_CENTER = {
    AC: [-9.97, -67.81], AL: [-9.67, -35.74], AM: [-3.12, -60.02], AP: [0.03, -51.07],
    BA: [-12.97, -38.5], CE: [-3.72, -38.54], DF: [-15.79, -47.88], ES: [-20.32, -40.34],
    GO: [-16.68, -49.25], MA: [-2.53, -44.3], MG: [-19.92, -43.94], MS: [-20.44, -54.65],
    MT: [-15.6, -56.1], PA: [-1.46, -48.5], PB: [-7.12, -34.86], PE: [-8.05, -34.88],
    PI: [-5.09, -42.8], PR: [-25.43, -49.27], RJ: [-22.91, -43.17], RN: [-5.79, -35.21],
    RO: [-8.76, -63.9], RR: [2.82, -60.67], RS: [-30.03, -51.23], SC: [-27.59, -48.55],
    SE: [-10.91, -37.07], SP: [-23.55, -46.63], TO: [-10.18, -48.33],
  };

  let payload = { nodes: [], edges: [] };
  let map;

  function toElements(data) {
    const nodes = (data.nodes || []).map((n) => ({
      data: {
        id: n.id,
        name: n.label,
        label: n.seed ? n.label + " · alvo" : n.label + " · g" + (n.depth || 0),
        type: n.type,
        seed: n.seed,
        status: n.status || "confirmed",
        depth: n.depth || 0,
        confidence: n.confidence || 0,
        key: n.key || "",
        kind: (n.attrs || {}).kind || "",
        attrs: n.attrs || {},
      },
    }));
    const edges = (data.edges || []).map((e) => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.grau ? e.type + " · g" + e.grau : e.type,
        note: e.note || "",
        grau: e.grau || "",
      },
    }));
    return nodes.concat(edges);
  }

  const cy = cytoscape({
    container: root,
    elements: [],
    layout: { name: "preset" },
    minZoom: 0.15,
    maxZoom: 2.4,
    wheelSensitivity: 0.25,
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          color: "#d7e4dc",
          "font-size": 11,
          "font-family": "IBM Plex Mono, monospace",
          "text-wrap": "ellipsis",
          "text-max-width": 148,
          "text-valign": "center",
          "text-halign": "center",
          "min-zoomed-font-size": 8,
          shape: "round-rectangle",
          "background-color": "#121a16",
          "border-width": 1.4,
          "border-color": "#5e7a62",
          width: 168,
          height: 44,
          padding: "6px",
        },
      },
      { selector: 'node[type = "ORG"]', style: { "border-color": colors.ORG } },
      { selector: 'node[type = "CASE"]', style: { "border-color": colors.CASE } },
      { selector: 'node[type = "PROFILE"]', style: { "border-color": colors.PROFILE } },
      { selector: 'node[type = "ASSET"]', style: { "border-color": colors.ASSET } },
      { selector: 'node[type = "VEHICLE"]', style: { "border-color": colors.VEHICLE } },
      { selector: 'node[type = "PUBLICATION"]', style: { "border-color": colors.PUBLICATION } },
      { selector: 'node[type = "PERSON"]', style: { "border-color": colors.PERSON } },
      { selector: 'node[type = "NOTE"]', style: { "border-color": colors.NOTE, "background-color": "#1c1a10" } },
      { selector: 'node[kind = "diagram"]', style: { width: 210, height: 64, "border-color": "#d4b45a", "background-color": "#1c1810", "text-wrap": "wrap", "text-max-width": 190 } },
      { selector: "node[?seed]", style: { width: 188, height: 50, "border-color": "#6f9b82", "border-width": 2, "background-color": "#15241c" } },
      { selector: 'node[status = "unconfirmed"]', style: { "border-style": "dashed", "border-color": "#c4a35a", "opacity": 0.85 } },
      { selector: "node:selected", style: { "border-color": "#00ff9c", "border-width": 2.4, "background-color": "#163024" } },
      {
        selector: "edge",
        style: {
          width: 1.1,
          "line-color": "#3d5348",
          "target-arrow-color": "#3d5348",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          "control-point-step-size": 28,
          label: "data(label)",
          "font-size": 8,
          "font-family": "IBM Plex Mono, monospace",
          color: "#8aa394",
          "text-background-color": "#080d0a",
          "text-background-opacity": 0.9,
          "text-background-padding": 2,
        },
      },
    ],
  });

  function visibleElements() {
    const nodes = cy.nodes().filter((node) => node.style("display") !== "none");
    return nodes.closedNeighborhood().filter((el) => {
      if (el.isEdge()) return el.source().visible() && el.target().visible();
      return el.visible();
    });
  }

  function networkLayoutOpts() {
    const n = Math.max(1, cy.nodes(":visible").length);
    const repulsion = Math.min(72000, 18000 + n * 220);
    const edgeLen = Math.min(260, 110 + Math.sqrt(n) * 16);
    return {
      name: "cose",
      animate: false,
      randomize: !laidOnce && n > 24,
      fit: true,
      padding: 56,
      nodeDimensionsIncludeLabels: true,
      nodeOverlap: 40,
      nodeRepulsion: () => repulsion,
      idealEdgeLength: () => edgeLen,
      edgeElasticity: () => 0.35,
      gravity: 0.12,
      numIter: n > 80 ? 900 : 1400,
      componentSpacing: 140,
      nestingFactor: 1.2,
    };
  }

  let laidOnce = false;

  function applyLayout(view) {
    const eles = visibleElements();
    if (!eles.nodes().length) return;
    if (view === "arvore") {
      const seeds = eles.nodes().filter((node) => node.data("seed"));
      eles.layout({
        name: "breadthfirst",
        directed: true,
        roots: seeds.length ? seeds : undefined,
        spacingFactor: 1.9,
        avoidOverlap: true,
        nodeDimensionsIncludeLabels: true,
        padding: 48,
        animate: false,
        fit: true,
      }).run();
      laidOnce = true;
      return;
    }
    eles.layout(networkLayoutOpts()).run();
    laidOnce = true;
  }

  function renderSplit() {
    const box = document.getElementById("split-list");
    if (!box) return;
    const orgs = (payload.nodes || []).filter((n) => n.type === "ORG");
    if (!orgs.length) {
      box.innerHTML = "<p class='lede'>Nenhuma empresa no grafo ainda.</p>";
      return;
    }
    box.innerHTML =
      "<h2>Empresas</h2><table class='table'><thead><tr><th>Nome</th><th>Situação</th><th>Local</th></tr></thead><tbody>" +
      orgs
        .map((n) => {
          const a = n.attrs || {};
          const loc = [a.municipio, a.uf].filter(Boolean).join(" / ");
          const note = a.nota ? " · nota" : "";
          return `<tr data-id="${n.id}"><td>${n.label}${note}</td><td>${a.situacao || "—"}</td><td>${loc || "—"}</td></tr>`;
        })
        .join("") +
      "</tbody></table>";
    box.querySelectorAll("tr[data-id]").forEach((row) => {
      row.addEventListener("click", () => {
        window.location.href = root.dataset.entityBase + row.dataset.id;
      });
    });
  }

  function markerLatLng(node) {
    const a = node.attrs || {};
    if (a.lat != null && a.lng != null) return [Number(a.lat), Number(a.lng)];
    const uf = String(a.uf || "").toUpperCase();
    const center = UF_CENTER[uf];
    if (!center) return null;
    let extra = 0;
    const city = String(a.municipio || "");
    for (let i = 0; i < city.length; i += 1) extra += city.charCodeAt(i);
    return [center[0] + (extra % 7) * 0.08, center[1] + (extra % 5) * 0.08];
  }

  function escapeHtml(text) {
    if (typeof window.escapeHtml === "function") {
      return window.escapeHtml(text);
    }
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderMap() {
    const el = document.getElementById("org-map");
    if (!el || typeof L === "undefined") return;
    const orgs = (payload.nodes || []).filter((n) => n.type === "ORG");
    if (map) {
      map.remove();
      map = null;
    }
    el.classList.add("is-ready");
    map = L.map(el, {
      zoomControl: false,
      attributionControl: true,
      fadeAnimation: false,
    }).setView([-14.2, -51.9], 4);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: "OSM · CARTO · scan_geo",
      subdomains: "abcd",
      maxZoom: 18,
    }).addTo(map);
    const icon = L.divIcon({
      className: "geo-mark",
      html: '<span class="geo-pulse"></span><span class="geo-core"></span>',
      iconSize: [22, 22],
      iconAnchor: [11, 11],
      popupAnchor: [0, -12],
    });
    const bounds = [];
    let plotted = 0;
    orgs.forEach((node) => {
      const latlng = markerLatLng(node);
      if (!latlng) return;
      plotted += 1;
      bounds.push(latlng);
      const a = node.attrs || {};
      const loc = [a.municipio, a.uf].filter(Boolean).join(" / ") || "UF aproximada";
      const exact = a.lat != null && a.lng != null;
      const marker = L.marker(latlng, { icon, keyboard: false }).addTo(map);
      marker.bindPopup(
        `<div class="geo-pop">` +
          `<p class="type-tag">empresa</p>` +
          `<strong>${escapeHtml(node.label)}</strong>` +
          `<p>${escapeHtml(a.situacao || "situação não informada")}</p>` +
          `<p class="muted">${escapeHtml(loc)}${exact ? "" : " · pin pela UF"}</p>` +
          (a.nota ? `<p class="muted">${escapeHtml(a.nota)}</p>` : "") +
          `<a class="btn primary" href="${root.dataset.entityBase}${node.id}">abrir ficha</a>` +
          `</div>`,
        { className: "geo-popup", maxWidth: 280 }
      );
    });
    let hud = el.querySelector(".geo-hud");
    if (!hud) {
      hud = document.createElement("div");
      hud.className = "geo-hud";
      el.appendChild(hud);
    }
    hud.innerHTML =
      `<p class="eyebrow">scan_geo</p>` +
      `<strong>${plotted}</strong>` +
      `<span>empresa(s) no grid · ${orgs.length - plotted} sem coordenada</span>`;
    if (bounds.length) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 11 });
    setTimeout(() => map.invalidateSize(), 80);
  }

  function setView(view) {
    document.querySelectorAll(".view-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.view === view);
    });
    const split = document.getElementById("split-list");
    const mapEl = document.getElementById("org-map");
    const stage = document.querySelector(".graph-stage");
    if (split) split.hidden = view !== "split";
    if (mapEl) mapEl.hidden = view !== "mapa";
    root.hidden = view === "mapa";
    if (stage) stage.classList.toggle("is-split", view === "split");
    if (view === "split") renderSplit();
    if (view === "mapa") renderMap();
    if (view !== "mapa") applyLayout(view);
  }

  async function load() {
    const res = await fetch(root.dataset.graphUrl, { credentials: "same-origin" });
    payload = await res.json();
    cy.elements().remove();
    cy.add(toElements(payload));
    laidOnce = false;
    const active = document.querySelector(".view-tab.is-active");
    setView((active && active.dataset.view) || "rede");
  }

  const TYPE_LABEL = {
    PERSON: "Pessoa",
    ORG: "Empresa",
    CASE: "Processo",
    PROFILE: "Perfil",
    ASSET: "Ativo",
    VEHICLE: "Veículo",
    PUBLICATION: "Publicação",
    NOTE: "Anotação",
  };
  const ATTR_LABEL = {
    razao_social: "razão social",
    situacao: "situação",
    municipio: "município",
    uf: "UF",
    cnae: "CNAE",
    capital_social: "capital",
    porte: "porte",
    endereco: "endereço",
    cep: "CEP",
    nota: "nota",
    motivo: "motivo",
    papel: "papel",
    nome: "nome",
    simples: "simples",
    mei: "MEI",
  };
  const balloon = document.getElementById("graph-balloon");
  const gbKind = document.getElementById("gb-kind");
  const gbTitle = document.getElementById("gb-title");
  const gbLead = document.getElementById("gb-lead");
  const gbFacts = document.getElementById("gb-facts");
  const gbActions = document.getElementById("gb-actions");
  let balloonLocked = false;
  let balloonTarget = null;
  let hideTimer = 0;

  function factRow(label, value) {
    const wrap = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    wrap.append(dt, dd);
    return wrap;
  }

  function nodeRecord(node) {
    return (payload.nodes || []).find((item) => item.id === node.id()) || {};
  }

  function fillBalloon(el, full) {
    if (!balloon || !gbKind || !gbTitle || !gbLead || !gbFacts || !gbActions) return;
    const isEdge = el.isEdge && el.isEdge();
    if (isEdge) {
      const from = el.source().data("name") || el.source().data("label") || "";
      const to = el.target().data("name") || el.target().data("label") || "";
      gbKind.textContent = "vínculo";
      gbTitle.textContent = el.data("label") || "Ligação";
      gbLead.textContent = from + " → " + to + (el.data("note") ? " · " + el.data("note") : "");
      gbFacts.replaceChildren();
      gbFacts.hidden = !full;
      if (full) {
        gbFacts.appendChild(factRow("tipo", String(el.data("label") || "—").split(" · ")[0]));
        if (el.data("grau")) gbFacts.appendChild(factRow("grau com o alvo", String(el.data("grau"))));
        if (el.data("note")) gbFacts.appendChild(factRow("nota", el.data("note")));
        gbFacts.appendChild(factRow("de", from));
        gbFacts.appendChild(factRow("para", to));
      }
      gbActions.hidden = !full;
      gbActions.replaceChildren();
      if (full && root.dataset.edgeBase) {
        const open = document.createElement("a");
        open.className = "btn primary";
        open.href = root.dataset.edgeBase + el.id();
        open.textContent = "Editar ligação";
        const close = document.createElement("button");
        close.type = "button";
        close.className = "btn";
        close.textContent = "Fechar";
        close.addEventListener("click", closeBalloon);
        gbActions.append(open, close);
      }
      return;
    }
    const rec = nodeRecord(el);
    const attrs = rec.attrs || el.data("attrs") || {};
    const type = el.data("type") || rec.type || "";
    const status = el.data("status") || rec.status || "confirmed";
    const neighbors = el.neighborhood("node").map((n) => n.data("name") || n.data("label")).filter(Boolean);
    gbKind.textContent = TYPE_LABEL[type] || type || "nó";
    gbTitle.textContent = el.data("name") || rec.label || "nó";
    gbLead.textContent = status === "unconfirmed"
      ? "Candidato — clique para a ficha e confirme ou desligue."
      : (full ? "Ficha rápida deste nó. Abrir a ficha completa para expandir ou desligar." : "Passe o cursor para ler · clique para mais detalhes");
    gbFacts.replaceChildren();
    gbFacts.hidden = !full;
    if (full) {
      if (rec.key || el.data("key")) gbFacts.appendChild(factRow("chave", rec.key || el.data("key")));
      gbFacts.appendChild(factRow("tipo", TYPE_LABEL[type] || type));
      gbFacts.appendChild(factRow("estado", status === "unconfirmed" ? "candidato" : "confirmado"));
      gbFacts.appendChild(factRow("grau com o alvo", el.data("seed") ? "0 · alvo" : String(rec.depth ?? el.data("depth") ?? 0)));
      if (rec.confidence != null) gbFacts.appendChild(factRow("confiança", Math.round(Number(rec.confidence) * 100) + "%"));
      Object.keys(ATTR_LABEL).forEach((key) => {
        if (attrs[key] == null || attrs[key] === "") return;
        gbFacts.appendChild(factRow(ATTR_LABEL[key], String(attrs[key])));
      });
      if (neighbors.length) gbFacts.appendChild(factRow("ligado a", neighbors.slice(0, 8).join(", ") + (neighbors.length > 8 ? "…" : "")));
    }
    gbActions.hidden = !full;
    gbActions.replaceChildren();
    if (full) {
      const open = document.createElement("a");
      open.className = "btn primary";
      open.href = root.dataset.entityBase + el.id();
      open.textContent = "Abrir ficha";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "btn";
      close.textContent = "Fechar";
      close.addEventListener("click", closeBalloon);
      gbActions.append(open, close);
    }
  }

  function placeBalloon(el) {
    if (!balloon || balloon.hidden) return;
    const stage = document.querySelector(".graph-stage");
    if (!stage) return;
    const box = el.renderedBoundingBox({ includeLabels: true });
    const width = balloon.offsetWidth || 228;
    const height = balloon.offsetHeight || 90;
    const maxX = stage.clientWidth - width - 12;
    const maxY = stage.clientHeight - height - 12;
    let left = box.x2 + 14;
    let top = box.y1;
    if (left > maxX) left = box.x1 - width - 14;
    balloon.style.left = Math.max(8, Math.min(maxX, left)) + "px";
    balloon.style.top = Math.max(8, Math.min(maxY, top)) + "px";
  }

  function showMini(el) {
    if (!balloon || balloonLocked) return;
    if (window.hideAppTip) window.hideAppTip();
    balloonTarget = el;
    fillBalloon(el, false);
    balloon.hidden = false;
    balloon.classList.remove("is-open");
    requestAnimationFrame(() => {
      balloon.classList.add("is-visible");
      placeBalloon(el);
    });
  }

  function openFull(el) {
    if (!balloon) return;
    if (window.hideAppTip) window.hideAppTip();
    balloonLocked = true;
    balloonTarget = el;
    cy.elements().unselect();
    if (el.select) el.select();
    fillBalloon(el, true);
    balloon.hidden = false;
    balloon.classList.add("is-open");
    requestAnimationFrame(() => {
      balloon.classList.add("is-visible");
      placeBalloon(el);
    });
  }

  function hideMini() {
    if (!balloon || balloonLocked) return;
    balloon.classList.remove("is-visible", "is-open");
    balloon.hidden = true;
    balloonTarget = null;
  }

  function closeBalloon() {
    balloonLocked = false;
    cy.elements().unselect();
    hideMini();
  }

  function scheduleHide() {
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      if (balloon && balloon.matches(":hover")) return;
      hideMini();
    }, 160);
  }

  cy.on("tap", "node", (evt) => {
    if (window.graphLinkPick && window.graphLinkPick(evt.target)) return;
    evt.preventDefault();
    openFull(evt.target);
  });
  cy.on("tap", "edge", (evt) => {
    if (window.graphLinkPick) return;
    evt.preventDefault();
    openFull(evt.target);
  });
  cy.on("tap", (evt) => {
    if (evt.target === cy) closeBalloon();
  });
  cy.on("mouseover", "node", (evt) => {
    window.clearTimeout(hideTimer);
    showMini(evt.target);
  });
  cy.on("mouseover", "edge", (evt) => {
    window.clearTimeout(hideTimer);
    showMini(evt.target);
  });
  cy.on("mouseout", "node, edge", scheduleHide);
  cy.on("pan zoom resize", () => {
    if (balloonTarget && !balloon.hidden) placeBalloon(balloonTarget);
  });
  if (balloon) {
    balloon.addEventListener("mouseenter", () => window.clearTimeout(hideTimer));
    balloon.addEventListener("mouseleave", () => {
      if (!balloonLocked) scheduleHide();
    });
    balloon.addEventListener("click", (event) => {
      if (event.target.closest("a, button")) return;
      if (balloonTarget && !balloonLocked) openFull(balloonTarget);
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && balloonLocked) closeBalloon();
  });

  const filter = document.getElementById("type-filter");
  const search = document.getElementById("graph-search");
  let filterTimer = 0;
  function applyFilters() {
    const type = filter ? filter.value : "";
    const q = search ? search.value.trim().toLowerCase() : "";
    cy.nodes().forEach((node) => {
      const typeOk = !type || node.data("type") === type;
      const text = String(node.data("name") || node.data("label") || "").toLowerCase();
      const key = String(node.data("key") || "").toLowerCase();
      const searchOk = !q || text.includes(q) || key.includes(q);
      node.style("display", typeOk && searchOk ? "element" : "none");
    });
    closeBalloon();
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => {
      const active = document.querySelector(".view-tab.is-active");
      applyLayout((active && active.dataset.view) || "rede");
    }, 160);
  }
  if (filter) filter.addEventListener("change", applyFilters);
  if (search) search.addEventListener("input", applyFilters);

  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });

  let lastShape = "";
  let lastPhase = "";
  async function poll() {
    try {
      const res = await fetch(root.dataset.statusUrl, { credentials: "same-origin" });
      const jobs = await res.json();
      const pill = document.getElementById("job-pill");
      const queue = (jobs.PENDING || 0) + (jobs.RUNNING || 0);
      if (pill) pill.textContent = queue ? "carregando " + queue : "concluído";
      if (jobs.label && window.setActionStatus) {
        window.setActionStatus(jobs.phase || (queue ? "loading" : "ok"), jobs.label);
      }
      const shape = `${jobs.entities || 0}:${jobs.edges || 0}`;
      if (lastShape && shape !== lastShape) load();
      lastShape = shape;
      lastPhase = jobs.phase || "";
    } catch (_) {
      /* ignore */
    }
  }

  const menu = document.getElementById("graph-menu");
  const composer = document.getElementById("graph-composer");
  const composerForm = document.getElementById("graph-composer-form");
  const gcKind = document.getElementById("gc-kind");
  const gcTitle = document.getElementById("gc-title");
  const gcLead = document.getElementById("gc-lead");
  const gcFields = document.getElementById("gc-fields");
  const stage = document.querySelector(".graph-stage");
  let linkFrom = null;
  let composerMode = "";

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.getAttribute("content")) || "";
  }

  function relTypes() {
    try {
      return JSON.parse(root.dataset.relTypes || "[]");
    } catch (_) {
      return ["RELACIONADO", "SETA", "ANOTACAO", "HIPOTESE"];
    }
  }

  function hideMenu() {
    if (menu) menu.hidden = true;
  }

  function placeMenu(x, y) {
    if (!menu) return;
    menu.hidden = false;
    const w = menu.offsetWidth || 228;
    const h = menu.offsetHeight || 160;
    menu.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x)) + "px";
    menu.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y)) + "px";
  }

  function menuButton(label, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      hideMenu();
      onClick();
    });
    return btn;
  }

  function closeComposer() {
    if (composer) composer.hidden = true;
    composerMode = "";
  }

  function field(label, name, type, value, extra) {
    const wrap = document.createElement("label");
    wrap.textContent = label;
    let input;
    if (type === "textarea") {
      input = document.createElement("textarea");
      input.rows = extra && extra.rows ? extra.rows : 4;
    } else if (type === "select") {
      input = document.createElement("select");
      (extra && extra.options ? extra.options : []).forEach((opt) => {
        const option = document.createElement("option");
        option.value = opt;
        option.textContent = opt;
        if (opt === value) option.selected = true;
        input.appendChild(option);
      });
    } else {
      input = document.createElement("input");
      input.type = type || "text";
      if (value) input.value = value;
    }
    input.name = name;
    if (type !== "select" && value) input.value = value;
    if (extra && extra.placeholder) input.placeholder = extra.placeholder;
    if (extra && extra.required) input.required = true;
    wrap.appendChild(input);
    return wrap;
  }

  function openComposer(mode, preset) {
    if (!composer || !gcFields || !gcKind || !gcTitle || !gcLead) return;
    composerMode = mode;
    gcFields.replaceChildren();
    if (mode === "note") {
      gcKind.textContent = "anotação";
      gcTitle.textContent = preset && preset.entityId ? "Anotação neste nó" : "Adicionar anotação";
      gcLead.textContent = "Fica no quadro do caso e, se quiser, vira um cartão na rede/árvore/split.";
      gcFields.appendChild(field("Título", "title", "text", "", { required: true, placeholder: "Hipótese, alerta, fonte…" }));
      gcFields.appendChild(field("Texto", "body", "textarea", "", { placeholder: "O que você quer lembrar" }));
    } else if (mode === "diagram") {
      gcKind.textContent = "diagrama";
      gcTitle.textContent = "Adicionar diagrama";
      gcLead.textContent = "Quadro no grafo, no estilo Miro/Mermaid: um bloco para desenhar a hipótese.";
      gcFields.appendChild(field("Título", "title", "text", "", { required: true, placeholder: "Fluxo, hipótese, mapa mental…" }));
      gcFields.appendChild(field("Conteúdo", "body", "textarea", "alvo --> empresa\nempresa --> socio", { rows: 6, placeholder: "alvo --> empresa\nempresa --> socio" }));
    } else {
      gcKind.textContent = "seta";
      gcTitle.textContent = "Adicionar ligação";
      gcLead.textContent = "Cria uma seta persistente entre dois nós do caso.";
      const names = (payload.nodes || []).map((n) => [n.id, n.label]);
      const from = document.createElement("label");
      from.textContent = "De";
      const fromSel = document.createElement("select");
      fromSel.name = "from_id";
      fromSel.required = true;
      const to = document.createElement("label");
      to.textContent = "Para";
      const toSel = document.createElement("select");
      toSel.name = "to_id";
      toSel.required = true;
      names.forEach(([id, label]) => {
        const a = document.createElement("option");
        a.value = id;
        a.textContent = label;
        if (preset && preset.fromId === id) a.selected = true;
        fromSel.appendChild(a);
        const b = document.createElement("option");
        b.value = id;
        b.textContent = label;
        if (preset && preset.toId === id) b.selected = true;
        toSel.appendChild(b);
      });
      from.appendChild(fromSel);
      to.appendChild(toSel);
      gcFields.append(from, to);
      gcFields.appendChild(field("Tipo", "rel_type", "select", preset && preset.rel ? preset.rel : "SETA", { options: relTypes() }));
      gcFields.appendChild(field("Nota da seta", "note", "text", "", { placeholder: "Por que estes nós se ligam" }));
    }
    composer.dataset.entityId = (preset && preset.entityId) || "";
    composer.hidden = false;
    const first = gcFields.querySelector("input, textarea, select");
    if (first) first.focus();
  }

  async function postBoard(url, fields) {
    const body = new URLSearchParams({ csrf_token: csrfToken(), ...fields });
    if (window.setActionStatus) window.setActionStatus("loading", "Gravando no quadro…");
    await fetch(url, { method: "POST", body, credentials: "same-origin", redirect: "follow" });
    if (window.setActionStatus) window.setActionStatus("ok", "Quadro atualizado.");
    await load();
  }

  function startLink(fromId) {
    linkFrom = fromId || null;
    if (stage) stage.classList.add("is-linking");
    if (window.setActionStatus) {
      window.setActionStatus("loading", fromId ? "Clique no nó de destino da seta." : "Clique na origem e depois no destino.");
    }
  }

  function stopLink() {
    linkFrom = null;
    if (stage) stage.classList.remove("is-linking");
  }

  window.graphLinkPick = function graphLinkPick(node) {
    if (!stage || !stage.classList.contains("is-linking")) return false;
    const id = node.id();
    if (!linkFrom) {
      linkFrom = id;
      if (window.setActionStatus) window.setActionStatus("loading", "Agora clique no destino da seta.");
      return true;
    }
    if (linkFrom === id) return true;
    const fromId = linkFrom;
    stopLink();
    openComposer("link", { fromId, toId: id, rel: "SETA" });
    return true;
  };

  if (composerForm) {
    composerForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(composerForm);
      if (composerMode === "link") {
        await postBoard(root.dataset.linkUrl, {
          from_id: String(data.get("from_id") || ""),
          to_id: String(data.get("to_id") || ""),
          rel_type: String(data.get("rel_type") || "SETA"),
          note: String(data.get("note") || ""),
        });
      } else {
        await postBoard(root.dataset.noteUrl, {
          title: String(data.get("title") || ""),
          body: String(data.get("body") || ""),
          entity_id: composer.dataset.entityId || "",
          on_graph: "1",
          kind: composerMode === "diagram" ? "diagram" : "note",
        });
      }
      closeComposer();
    });
  }
  const gcCancel = document.getElementById("gc-cancel");
  if (gcCancel) gcCancel.addEventListener("click", closeComposer);
  if (composer) {
    composer.addEventListener("click", (event) => {
      if (event.target === composer) closeComposer();
    });
  }

  function showMenu(evt, kind) {
    if (!menu) return;
    if (window.hideAppTip) window.hideAppTip();
    closeBalloon();
    menu.replaceChildren();
    const orig = evt.originalEvent || {};
    const head = document.createElement("div");
    head.className = "k";
    if (kind === "node") {
      const node = evt.target;
      head.textContent = "nó";
      menu.appendChild(head);
      menu.appendChild(menuButton("Abrir ficha", () => {
        window.location.href = root.dataset.entityBase + node.id();
      }));
      menu.appendChild(menuButton("Adicionar anotação", () => openComposer("note", { entityId: node.id() })));
      menu.appendChild(menuButton("Adicionar diagrama", () => openComposer("diagram", { entityId: node.id() })));
      menu.appendChild(menuButton("Ligar seta a outro nó", () => startLink(node.id())));
      const sep = document.createElement("div");
      sep.className = "sep";
      menu.appendChild(sep);
      menu.appendChild(menuButton("Expandir daqui", () => {
        postBoard(root.dataset.entityBase + node.id() + "/expandir", {});
      }));
      menu.appendChild(menuButton("Copiar nome", () => {
        const text = node.data("name") || node.data("label") || "";
        if (navigator.clipboard) navigator.clipboard.writeText(text);
      }));
      menu.appendChild(menuButton("Desligar nó", () => {
        if (confirm("Desligar este nó e as ligações?")) postBoard(root.dataset.entityBase + node.id() + "/desligar", {});
      }));
    } else if (kind === "edge") {
      const edge = evt.target;
      head.textContent = "seta";
      menu.appendChild(head);
      menu.appendChild(menuButton("Editar ligação", () => {
        window.location.href = root.dataset.edgeBase + edge.id();
      }));
      menu.appendChild(menuButton("Apagar seta", () => {
        if (confirm("Remover só esta ligação?")) postBoard(root.dataset.edgeBase + edge.id() + "/apagar", {});
      }));
    } else {
      head.textContent = "quadro";
      menu.appendChild(head);
      menu.appendChild(menuButton("Adicionar anotação", () => openComposer("note")));
      menu.appendChild(menuButton("Adicionar diagrama", () => openComposer("diagram")));
      menu.appendChild(menuButton("Adicionar ligação (seta)", () => startLink(null)));
    }
    placeMenu(orig.clientX || 16, orig.clientY || 16);
  }

  cy.on("cxttap", "node", (evt) => {
    evt.preventDefault();
    showMenu(evt, "node");
  });
  cy.on("cxttap", "edge", (evt) => {
    evt.preventDefault();
    showMenu(evt, "edge");
  });
  cy.on("cxttap", (evt) => {
    if (evt.target !== cy) return;
    evt.preventDefault();
    showMenu(evt, "bg");
  });
  root.addEventListener("contextmenu", (event) => event.preventDefault());
  document.addEventListener("click", hideMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    hideMenu();
    closeComposer();
    stopLink();
  });

  if (root.dataset.statusInit && window.setActionStatus) {
    window.setActionStatus(root.dataset.statusPhase || "loading", root.dataset.statusInit);
  }
  load();
  poll();
  setInterval(poll, 4000);
})();
