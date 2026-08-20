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

  function formatCardId(item) {
    const kind = String((item && item.kind) || "").toUpperCase();
    const raw = String((item && item.value) || "").trim();
    if (kind === "CPF") {
      const d = raw.replace(/\D/g, "").slice(0, 11);
      if (d.length === 11) return "CPF " + d.slice(0, 3) + "." + d.slice(3, 6) + "." + d.slice(6, 9) + "-" + d.slice(9);
      return "CPF " + raw;
    }
    if (kind === "PHONE") return "tel " + raw;
    if (kind === "EMAIL") return raw;
    if (kind === "USERNAME") return raw.startsWith("@") ? raw : "@" + raw;
    if (kind === "BIRTHDATE") return "nasc. " + raw;
    return (kind ? kind + " " : "") + raw;
  }

  function cardLabel(n) {
    const title = n.seed ? n.label + " · alvo" : n.label + " · g" + (n.depth || 0);
    const extras = (n.ids || []).filter((item) => item.kind !== "NAME").slice(0, 4).map(formatCardId);
    return [title].concat(extras).join("\n");
  }

  function toElements(data) {
    const nodes = (data.nodes || []).map((n) => ({
      data: {
        id: n.id,
        name: n.label,
        label: cardLabel(n),
        type: n.type,
        seed: n.seed,
        status: n.status || "confirmed",
        depth: n.depth || 0,
        confidence: n.confidence || 0,
        key: n.key || "",
        kind: (n.attrs || {}).kind || "",
        attrs: n.attrs || {},
        ids: n.ids || [],
        lines: 1 + Math.min(4, (n.ids || []).filter((item) => item.kind !== "NAME").length),
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
        strength: e.strength || "",
        period: e.period || "",
        year: e.year || 0,
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
    boxSelectionEnabled: false,
    selectionType: "additive",
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          color: "#d7e4dc",
          "font-size": 11,
          "font-family": "IBM Plex Mono, monospace",
          "text-wrap": "wrap",
          "text-max-width": 188,
          "text-valign": "center",
          "text-halign": "center",
          "min-zoomed-font-size": 8,
          shape: "round-rectangle",
          "background-color": "#121a16",
          "border-width": 1.4,
          "border-color": "#5e7a62",
          width: 200,
          height: 52,
          padding: "8px",
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
      { selector: "node[?seed]", style: { width: 210, height: 58, "border-color": "#6f9b82", "border-width": 2, "background-color": "#15241c" } },
      { selector: "node[lines > 1]", style: { height: 72 } },
      { selector: "node[lines > 2]", style: { height: 90 } },
      { selector: "node[lines > 3]", style: { height: 108 } },
      { selector: "node[lines > 4]", style: { height: 124 } },
      { selector: 'node[status = "unconfirmed"]', style: { "border-style": "dashed", "border-color": "#c4a35a", "opacity": 0.85 } },
      { selector: 'node[status = "probable"]', style: { "border-style": "dotted", "border-color": "#5eead4" } },
      { selector: 'node[status = "contested"]', style: { "border-color": "#ffe14a" } },
      { selector: 'node[status = "false"]', style: { "border-color": "#ff5c7a", "opacity": 0.45 } },
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
    const repulsion = Math.min(140000, 28000 + n * 380);
    const edgeLen = Math.min(340, 150 + Math.sqrt(n) * 22);
    return {
      name: "cose",
      animate: false,
      randomize: !laidOnce && n > 24,
      fit: true,
      padding: 72,
      nodeDimensionsIncludeLabels: true,
      nodeOverlap: 80,
      nodeRepulsion: () => repulsion,
      idealEdgeLength: () => edgeLen,
      edgeElasticity: () => 0.28,
      gravity: 0.08,
      numIter: n > 200 ? 400 : n > 80 ? 700 : 1100,
      componentSpacing: 200,
      nestingFactor: 1.2,
    };
  }

  function unoverlapNodes() {
    const nodes = cy.nodes(":visible").toArray();
    if (nodes.length < 2 || nodes.length > 140) return false;
    const pad = 22;
    let moved = false;
    const maxIter = nodes.length > 60 ? 6 : 14;
    for (let iter = 0; iter < maxIter; iter += 1) {
      let hit = false;
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = nodes[i];
          const b = nodes[j];
          const pa = a.position();
          const pb = b.position();
          const ox = (a.width() + b.width()) / 2 + pad - Math.abs(pb.x - pa.x);
          const oy = (a.height() + b.height()) / 2 + pad - Math.abs(pb.y - pa.y);
          if (ox <= 0 || oy <= 0) continue;
          if (ox < oy) {
            const step = ((pb.x === pa.x ? 1 : Math.sign(pb.x - pa.x)) * (ox / 2 + 1));
            a.position({ x: pa.x - step, y: pa.y });
            b.position({ x: pb.x + step, y: pb.y });
          } else {
            const step = ((pb.y === pa.y ? 1 : Math.sign(pb.y - pa.y)) * (oy / 2 + 1));
            a.position({ x: pa.x, y: pa.y - step });
            b.position({ x: pb.x, y: pb.y + step });
          }
          hit = true;
          moved = true;
        }
      }
      if (!hit) break;
    }
    return moved;
  }

  let laidOnce = false;
  let layoutLocked = false;
  let layoutDirty = false;
  let layoutTimer = 0;

  function savedNodeMap() {
    return ((payload.layout || {}).nodes) || {};
  }

  function hasLockedLayout() {
    return layoutLocked || Object.keys(savedNodeMap()).length > 0;
  }

  function capturePositions() {
    const nodes = {};
    cy.nodes().forEach((node) => {
      const pos = node.position();
      nodes[node.id()] = { x: pos.x, y: pos.y };
    });
    return nodes;
  }

  function applySavedPositions(nodes) {
    let applied = 0;
    Object.entries(nodes || {}).forEach(([id, pos]) => {
      const node = cy.getElementById(id);
      if (!node.nonempty() || !pos) return;
      const x = Number(pos.x);
      const y = Number(pos.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      node.position({ x, y });
      applied += 1;
    });
    return applied;
  }

  function idHash(id) {
    let hash = 0;
    const text = String(id || "");
    for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) | 0;
    return Math.abs(hash);
  }

  function placeNewNodes(knownIds) {
    const fresh = cy.nodes().filter((node) => !knownIds.has(node.id()));
    if (!fresh.length) return;
    const old = cy.nodes().filter((node) => knownIds.has(node.id()));
    const box = old.length ? old.boundingBox() : { x2: 0, y1: 0, h: 240 };
    let slot = 0;
    fresh.forEach((node) => {
      const neighbors = node.neighborhood("node").filter((other) => knownIds.has(other.id()));
      if (neighbors.length) {
        let x = 0;
        let y = 0;
        neighbors.forEach((other) => {
          const pos = other.position();
          x += pos.x;
          y += pos.y;
        });
        const angle = ((idHash(node.id()) % 360) * Math.PI) / 180;
        const radius = 190 + neighbors.length * 14;
        node.position({
          x: x / neighbors.length + Math.cos(angle) * radius,
          y: y / neighbors.length + Math.sin(angle) * radius,
        });
      } else {
        node.position({
          x: (box.x2 || 0) + 220,
          y: (box.y1 || 0) + (slot % 8) * 72 + Math.floor(slot / 8) * 24,
        });
        slot += 1;
      }
    });
  }

  function collectLayout() {
    const view = activeView();
    const pan = cy.pan();
    const prev = payload.layout || {};
    const nodes = view === "arvore" ? { ...savedNodeMap(), ...((prev.nodes) || {}) } : capturePositions();
    const snap = {
      view,
      zoom: cy.zoom(),
      pan: { x: pan.x, y: pan.y },
      nodes,
      locked: true,
    };
    if (map) {
      const center = map.getCenter();
      snap.map = { zoom: map.getZoom(), lat: center.lat, lng: center.lng };
    } else if (prev.map) {
      snap.map = prev.map;
    }
    return snap;
  }

  function scheduleSaveLayout() {
    layoutDirty = true;
    window.clearTimeout(layoutTimer);
    layoutTimer = window.setTimeout(saveLayoutNow, 700);
  }

  async function saveLayoutNow() {
    if (!layoutDirty || !root.dataset.layoutUrl) return;
    layoutDirty = false;
    const snap = collectLayout();
    payload.layout = snap;
    layoutLocked = true;
    try {
      await fetch(root.dataset.layoutUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken(), ...snap }),
      });
    } catch (_) {
      layoutDirty = true;
    }
  }

  function applyLayout(view) {
    const eles = visibleElements();
    if (!eles.nodes().length) return;
    if (view === "arvore") {
      const seeds = eles.nodes().filter((node) => node.data("seed"));
      eles.layout({
        name: "breadthfirst",
        directed: true,
        roots: seeds.length ? seeds : undefined,
        spacingFactor: 2.3,
        avoidOverlap: true,
        nodeDimensionsIncludeLabels: true,
        padding: 48,
        animate: false,
        fit: true,
      }).run();
      laidOnce = true;
      unoverlapNodes();
      return;
    }
    eles.layout(networkLayoutOpts()).run();
    laidOnce = true;
    unoverlapNodes();
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
    map.on("moveend zoomend", () => {
      if (typeof schedulePushView === "function") schedulePushView();
    });
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
      `<strong>${plotted}</strong>` +
      `<span>${orgs.length - plotted ? (orgs.length - plotted) + " sem pin" : "grid"}</span>`;
    const savedMap = (payload.layout || {}).map;
    if (savedMap && savedMap.lat != null && savedMap.lng != null) {
      map.setView([Number(savedMap.lat), Number(savedMap.lng)], Number(savedMap.zoom) || 4);
    } else if (bounds.length) {
      map.fitBounds(bounds, { padding: [36, 36], maxZoom: 11 });
    }
    setTimeout(() => map.invalidateSize(), 80);
  }

  function activeView() {
    const active = document.querySelector(".view-tab.is-active");
    return (active && active.dataset.view) || "rede";
  }

  function setView(view) {
    document.querySelectorAll(".view-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.view === view);
    });
    const split = document.getElementById("split-list");
    const mapEl = document.getElementById("org-map");
    const stage = document.querySelector(".graph-stage");
    const wrap = document.querySelector(".graph-canvas");
    if (split) split.hidden = view !== "split";
    if (mapEl) mapEl.hidden = view !== "mapa";
    if (wrap) wrap.hidden = view === "mapa";
    root.hidden = view === "mapa";
    if (stage) {
      stage.classList.toggle("is-split", view === "split");
      stage.classList.toggle("is-map", view === "mapa");
    }
    if (view === "split") renderSplit();
    if (view === "mapa") renderMap();
    if (view === "arvore") applyLayout("arvore");
    else if (view !== "mapa" && hasLockedLayout()) applySavedPositions(savedNodeMap());
    else if (view !== "mapa") applyLayout(view);
  }

  function patchElements(data) {
    const nextNodes = new Set((data.nodes || []).map((item) => item.id));
    const nextEdges = new Set((data.edges || []).map((item) => item.id));
    const gone = cy.elements().filter((el) => (el.isNode() ? !nextNodes.has(el.id()) : !nextEdges.has(el.id())));
    if (gone.length) gone.remove();
    const haveNodes = new Set(cy.nodes().map((node) => node.id()));
    const haveEdges = new Set(cy.edges().map((edge) => edge.id()));
    const fresh = {
      nodes: (data.nodes || []).filter((item) => !haveNodes.has(item.id)),
      edges: (data.edges || []).filter((item) => !haveEdges.has(item.id)),
    };
    if (fresh.nodes.length || fresh.edges.length) cy.add(toElements(fresh));
    (data.nodes || []).forEach((item) => {
      if (!haveNodes.has(item.id)) return;
      const el = cy.getElementById(item.id);
      if (!el.nonempty()) return;
      const label = cardLabel(item);
      if (el.data("label") !== label || el.data("status") !== (item.status || "confirmed")) {
        el.data({
          name: item.label,
          label,
          status: item.status || "confirmed",
          ids: item.ids || [],
          attrs: item.attrs || {},
          depth: item.depth || 0,
        });
      }
    });
    return { added: fresh.nodes.length + fresh.edges.length, removed: gone.length };
  }

  let lastLoadAt = 0;

  async function load() {
    const live = capturePositions();
    const camera = snapshotView();
    const hadNodes = cy.nodes().length > 0;
    const res = await fetch(root.dataset.graphUrl, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("grafo " + res.status);
    const next = await res.json();
    if (!next || typeof next !== "object") throw new Error("grafo inválido");
    if (hadNodes && next.rev && payload.rev && next.rev === payload.rev) {
      lastLoadAt = Date.now();
      return;
    }
    const known = new Set([...Object.keys(live), ...cy.nodes().map((node) => node.id())]);
    payload = next;
    rebuildNodeIndex();
    if (yearInput && (payload.years || []).length && !yearInput.dataset.ready) {
      yearInput.min = String(payload.years[0]);
      yearInput.max = String(payload.years[payload.years.length - 1]);
      yearInput.value = yearInput.max;
      if (yearOut) yearOut.textContent = yearInput.value;
      yearInput.dataset.ready = "1";
    }
    if (hadNodes) patchElements(payload);
    else {
      cy.elements().remove();
      cy.add(toElements(payload));
    }
    const serverNodes = savedNodeMap();
    const merged = { ...serverNodes, ...live };
    const applied = applySavedPositions(merged);
    placeNewNodes(new Set([...known, ...Object.keys(merged)]));
    layoutLocked = applied > 0 || Object.keys(serverNodes).length > 0;
    if (!layoutLocked && unoverlapNodes()) payload.layout = { ...(payload.layout || {}), nodes: capturePositions() };
    payload.layout = { ...(payload.layout || {}), nodes: { ...merged, ...capturePositions() } };
    const active = document.querySelector(".view-tab.is-active");
    const nextView = (!hadNodes && payload.layout.view) || (active && active.dataset.view) || "rede";
    if (hadNodes) {
      applyFilters();
      applySnapshot(camera);
      laidOnce = true;
      if (nextView === "split") renderSplit();
      if (nextView === "mapa") renderMap();
    } else {
      setView(nextView);
      if (layoutLocked && nextView !== "arvore") {
        const layout = payload.layout || {};
        if (layout.zoom) {
          applySnapshot({ kind: "cy", zoom: layout.zoom, x: (layout.pan || {}).x || 0, y: (layout.pan || {}).y || 0 });
        } else {
          cy.fit(undefined, 48);
        }
        laidOnce = true;
      } else if (!layoutLocked) {
        scheduleSaveLayout();
      }
      applyFilters();
    }
    lastLoadAt = Date.now();
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
    nascimento: "nascimento",
    nome_pai: "pai",
    nome_mae: "mãe",
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

  let nodeIndex = new Map();

  function rebuildNodeIndex() {
    nodeIndex = new Map((payload.nodes || []).map((item) => [item.id, item]));
  }

  function nodeRecord(node) {
    const id = typeof node === "string" ? node : node.id();
    if (nodeIndex.has(id)) return nodeIndex.get(id) || {};
    return (payload.nodes || []).find((item) => item.id === id) || {};
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
        if (el.data("strength")) gbFacts.appendChild(factRow("força", el.data("strength")));
        if (el.data("period")) gbFacts.appendChild(factRow("período", el.data("period")));
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
    const labels = { unconfirmed: "Candidato", probable: "Provável", contested: "Contestado", false: "Falso", confirmed: "" };
    gbLead.textContent = labels[status] || "";
    gbFacts.replaceChildren();
    gbFacts.hidden = !full;
    if (full) {
      if (rec.key || el.data("key")) gbFacts.appendChild(factRow("chave", rec.key || el.data("key")));
      gbFacts.appendChild(factRow("tipo", TYPE_LABEL[type] || type));
      gbFacts.appendChild(factRow("estado", labels[status] || status));
      gbFacts.appendChild(factRow("grau com o alvo", el.data("seed") ? "0 · alvo" : String(rec.depth ?? el.data("depth") ?? 0)));
      if (rec.confidence != null) gbFacts.appendChild(factRow("confiança", Math.round(Number(rec.confidence) * 100) + "%"));
      (rec.ids || el.data("ids") || []).forEach((item) => {
        gbFacts.appendChild(factRow(item.kind || "dado", formatCardId(item)));
      });
      Object.keys(ATTR_LABEL).forEach((key) => {
        if (attrs[key] == null || attrs[key] === "") return;
        gbFacts.appendChild(factRow(ATTR_LABEL[key], String(attrs[key])));
      });
      if (neighbors.length) gbFacts.appendChild(factRow("ligado a", neighbors.slice(0, 8).join(", ") + (neighbors.length > 8 ? "…" : "")));
    }
    gbActions.hidden = !full;
    gbActions.replaceChildren();
    if (full) {
      const probe = document.createElement("button");
      probe.type = "button";
      probe.className = "btn primary";
      probe.textContent = type === "ORG" ? "Procurar empresas e QSA" : "Procurar informações";
      probe.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        closeBalloon();
        probeNode(el.id(), el.data("name") || rec.label || "", type === "ORG" ? "CNPJ" : "NAME");
      });
      const open = document.createElement("a");
      open.className = "btn";
      open.href = root.dataset.entityBase + el.id();
      open.textContent = "Abrir ficha";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "btn";
      close.textContent = "Fechar";
      close.addEventListener("click", closeBalloon);
      gbActions.append(probe, open, close);
    }
  }

  function placeBalloon(el) {
    if (!balloon || balloon.hidden) return;
    const host = cy.container() || document.getElementById("cy");
    if (!host) return;
    const rect = host.getBoundingClientRect();
    const box = el.renderedBoundingBox({ includeLabels: true });
    const width = balloon.offsetWidth || 260;
    const height = balloon.offsetHeight || 90;
    const pad = 12;
    let left = rect.left + box.x2 + 14;
    let top = rect.top + box.y1;
    if (left + width > window.innerWidth - pad) left = rect.left + box.x1 - width - 14;
    if (top + height > window.innerHeight - pad) top = window.innerHeight - height - pad;
    balloon.style.left = Math.max(pad, Math.min(window.innerWidth - width - pad, left)) + "px";
    balloon.style.top = Math.max(pad, Math.min(window.innerHeight - height - pad, top)) + "px";
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
      requestAnimationFrame(() => placeBalloon(el));
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
  window.addEventListener("resize", () => {
    if (balloonTarget && balloon && !balloon.hidden) placeBalloon(balloonTarget);
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

  const layerBox = document.getElementById("ct-layers-panel");
  const search = document.getElementById("graph-search");
  const yearInput = document.getElementById("graph-year");
  const yearOut = document.getElementById("graph-year-out");
  let filterTimer = 0;
  function hiddenTypes() {
    const off = new Set();
    if (!layerBox) return off;
    layerBox.querySelectorAll("input[data-type]").forEach((input) => {
      if (!input.checked) off.add(input.dataset.type);
    });
    return off;
  }
  function filterType() {
    const on = document.querySelector("[data-filter-type].is-on");
    return (on && on.dataset.filterType) || "all";
  }
  function filterDegrees() {
    const degrees = new Set();
    document.querySelectorAll("[data-filter-degree]").forEach((input) => {
      if (input.checked) degrees.add(Number(input.dataset.filterDegree));
    });
    return degrees;
  }
  function applyFilters() {
    const blocked = hiddenTypes();
    const typeMode = filterType();
    const degrees = filterDegrees();
    const q = search ? search.value.trim().toLowerCase() : "";
    cy.nodes().forEach((node) => {
      const type = node.data("type");
      const depth = Number(node.data("depth") || 0);
      const seed = !!node.data("seed");
      const text = String(node.data("name") || node.data("label") || "").toLowerCase();
      const key = String(node.data("key") || "").toLowerCase();
      const searchOk = !q || text.includes(q) || key.includes(q);
      const layerOk = typeMode === "all" ? !blocked.has(type) : type === typeMode || seed;
      const degreeOk = seed ? degrees.has(0) : degrees.has(Math.min(depth, 4));
      node.style("display", searchOk && layerOk && degreeOk ? "element" : "none");
    });
    const yearLimit = yearInput ? Number(yearInput.value) : 9999;
    cy.edges().forEach((edge) => {
      const year = Number(edge.data("year") || 0);
      const endsOn = edge.source().style("display") !== "none" && edge.target().style("display") !== "none";
      edge.style("display", endsOn && (!year || year <= yearLimit) ? "element" : "none");
    });
    closeBalloon();
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => {
      if (activeView() === "arvore" || !hasLockedLayout()) applyLayout(activeView());
    }, 160);
  }
  const filterBox = document.getElementById("graph-filters");
  if (filterBox) {
    filterBox.querySelectorAll("[data-filter-type]").forEach((btn) => {
      btn.addEventListener("click", () => {
        filterBox.querySelectorAll("[data-filter-type]").forEach((other) => other.classList.toggle("is-on", other === btn));
        applyFilters();
      });
    });
    filterBox.addEventListener("change", applyFilters);
  }
  if (layerBox) layerBox.addEventListener("change", applyFilters);
  if (search) search.addEventListener("input", applyFilters);
  if (yearInput) {
    yearInput.addEventListener("input", () => {
      if (yearOut) yearOut.textContent = yearInput.value;
      applyFilters();
    });
  }

  const DOTS_KEY = "osint4all.canvasDots";
  const viewStack = [];
  let viewIdx = -1;
  let ignoreView = false;
  let viewTimer = 0;

  function snapshotView() {
    if (activeView() === "mapa" && map) {
      const center = map.getCenter();
      return { kind: "map", zoom: map.getZoom(), lat: center.lat, lng: center.lng };
    }
    const pan = cy.pan();
    return { kind: "cy", zoom: cy.zoom(), x: pan.x, y: pan.y };
  }

  function applySnapshot(snap) {
    ignoreView = true;
    if (snap.kind === "map" && map) {
      map.setView([snap.lat, snap.lng], snap.zoom);
    } else {
      cy.zoom(snap.zoom);
      cy.pan({ x: snap.x, y: snap.y });
    }
    window.setTimeout(() => {
      ignoreView = false;
    }, 80);
  }

  function syncUndoBtns() {
    const undo = document.getElementById("ct-undo");
    const redo = document.getElementById("ct-redo");
    if (undo) undo.disabled = viewIdx <= 0;
    if (redo) redo.disabled = viewIdx < 0 || viewIdx >= viewStack.length - 1;
  }

  function pushView() {
    if (ignoreView) return;
    const snap = snapshotView();
    const last = viewStack[viewIdx];
    if (
      last &&
      last.kind === snap.kind &&
      last.zoom === snap.zoom &&
      last.x === snap.x &&
      last.y === snap.y &&
      last.lat === snap.lat &&
      last.lng === snap.lng
    ) {
      return;
    }
    viewStack.splice(viewIdx + 1);
    viewStack.push(snap);
    if (viewStack.length > 40) viewStack.shift();
    viewIdx = viewStack.length - 1;
    syncUndoBtns();
  }

  function schedulePushView() {
    if (ignoreView) return;
    window.clearTimeout(viewTimer);
    viewTimer = window.setTimeout(pushView, 280);
  }

  function setDots(on) {
    const stageEl = document.querySelector(".graph-stage");
    const btn = document.getElementById("ct-dots");
    if (stageEl) stageEl.classList.toggle("is-dots", on);
    root.classList.toggle("is-dots", on);
    if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");
    try {
      localStorage.setItem(DOTS_KEY, on ? "1" : "0");
    } catch (_) {
      /* ignore */
    }
  }

  function zoomStep(dir) {
    if (activeView() === "mapa" && map) {
      map.setZoom(map.getZoom() + dir);
      return;
    }
    cy.zoom({
      level: cy.zoom() * (dir > 0 ? 1.2 : 1 / 1.2),
      renderedPosition: { x: root.clientWidth / 2, y: root.clientHeight / 2 },
    });
  }

  function fitCanvas() {
    if (activeView() === "mapa" && map) {
      map.invalidateSize();
      const pts = [];
      (payload.nodes || []).forEach((node) => {
        const latlng = markerLatLng(node);
        if (latlng) pts.push(latlng);
      });
      if (pts.length) map.fitBounds(pts, { padding: [36, 36], maxZoom: 11 });
      return;
    }
    const eles = visibleElements();
    cy.fit(eles.nodes().length ? eles : undefined, 48);
  }

  (function bindCanvasTools() {
    const stageEl = document.querySelector(".graph-stage");
    const dotsBtn = document.getElementById("ct-dots");
    const layerBtn = document.getElementById("ct-layers");
    let stored = "1";
    try {
      stored = localStorage.getItem(DOTS_KEY);
    } catch (_) {
      stored = "1";
    }
    setDots(stored !== "0");
    if (dotsBtn) {
      dotsBtn.addEventListener("click", () => setDots(!(stageEl && stageEl.classList.contains("is-dots"))));
    }
    const zoomIn = document.getElementById("ct-zoom-in");
    const zoomOut = document.getElementById("ct-zoom-out");
    const fitBtn = document.getElementById("ct-fit");
    const undoBtn = document.getElementById("ct-undo");
    const redoBtn = document.getElementById("ct-redo");
    if (zoomIn) zoomIn.addEventListener("click", () => zoomStep(1));
    if (zoomOut) zoomOut.addEventListener("click", () => zoomStep(-1));
    if (fitBtn) fitBtn.addEventListener("click", fitCanvas);
    if (undoBtn) {
      undoBtn.addEventListener("click", () => {
        if (viewIdx <= 0) return;
        viewIdx -= 1;
        applySnapshot(viewStack[viewIdx]);
        syncUndoBtns();
      });
    }
    if (redoBtn) {
      redoBtn.addEventListener("click", () => {
        if (viewIdx >= viewStack.length - 1) return;
        viewIdx += 1;
        applySnapshot(viewStack[viewIdx]);
        syncUndoBtns();
      });
    }
    if (layerBtn && layerBox) {
      layerBtn.addEventListener("click", () => {
        const open = layerBox.hidden;
        layerBox.hidden = !open;
        layerBtn.setAttribute("aria-expanded", open ? "true" : "false");
      });
      document.addEventListener("click", (event) => {
        if (layerBox.hidden) return;
        if (event.target.closest("#ct-layers, #ct-layers-panel")) return;
        layerBox.hidden = true;
        layerBtn.setAttribute("aria-expanded", "false");
      });
    }
    cy.on("pan zoom", () => {
      schedulePushView();
      scheduleSaveLayout();
    });
    cy.on("dragfree", "node", () => {
      layoutLocked = true;
      scheduleSaveLayout();
    });
    window.addEventListener("pagehide", () => {
      if (layoutDirty) saveLayoutNow();
    });
    document.addEventListener("keydown", (event) => {
      if (event.target && /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          if (redoBtn) redoBtn.click();
        } else if (undoBtn) undoBtn.click();
      }
      if (event.key === "+" || event.key === "=") zoomStep(1);
      if (event.key === "-" || event.key === "_") zoomStep(-1);
      if (event.key === "0") fitCanvas();
    });
    window.setTimeout(pushView, 400);
  })();

  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });

  let lastShape = "";
  let lastPhase = "";
  let mutating = false;
  let selectMode = false;
  let pollTimer = 0;

  function schedulePoll(ms) {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(() => {
      poll().catch(() => schedulePoll(5000));
    }, ms);
  }

  function applyPulse(jobs) {
    const pill = document.getElementById("job-pill");
    const queue = (jobs.PENDING || 0) + (jobs.RUNNING || 0);
    if (pill) pill.textContent = queue ? "rodando " + queue : "concluído";
    if (!mutating && jobs.label && window.setActionStatus) {
      window.setActionStatus(jobs.phase || (queue ? "loading" : "ok"), jobs.label);
    }
    const shape = `${jobs.entities || 0}:${jobs.edges || 0}`;
    const changed = lastShape && shape !== lastShape;
    lastShape = shape;
    lastPhase = jobs.phase || "";
    return { queue, changed };
  }

  async function readJson(res) {
    const ctype = (res.headers.get("content-type") || "").toLowerCase();
    if (!ctype.includes("json")) {
      throw new Error("resposta sem JSON");
    }
    return res.json();
  }

  async function poll() {
    if (mutating) {
      schedulePoll(1500);
      return;
    }
    try {
      const res = await fetch(root.dataset.statusUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) {
        schedulePoll(4000);
        return;
      }
      let jobs = await readJson(res);
      let info = applyPulse(jobs);
      if (info.queue && root.dataset.tickUrl) {
        const tick = await fetch(root.dataset.tickUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          body: new URLSearchParams({ csrf_token: csrfToken() }),
        });
        if (tick.ok) {
          jobs = await readJson(tick);
          info = applyPulse(jobs);
        }
      }
      if (info.changed && !selectMode && Date.now() - lastLoadAt > 900) {
        try {
          await load();
        } catch (_) {
          /* próximo ciclo tenta de novo */
        }
      }
      schedulePoll(info.queue ? 2200 : 5000);
    } catch (_) {
      schedulePoll(5000);
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
  const selectBar = document.getElementById("graph-select-bar");
  const selectCount = document.getElementById("graph-select-count");
  const selectBtn = document.getElementById("ct-select");
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
      gcLead.textContent = "";
      gcFields.appendChild(field("Título", "title", "text", "", { required: true, placeholder: "Hipótese, alerta, fonte…" }));
      gcFields.appendChild(field("Texto", "body", "textarea", "", { placeholder: "O que você quer lembrar" }));
    } else if (mode === "cnpj") {
      gcKind.textContent = "empresa";
      gcTitle.textContent = "Adicionar empresa pelo CNPJ";
      gcLead.textContent = "Liga ao alvo e busca o QSA / sócios.";
      gcFields.appendChild(field("CNPJ", "cnpj", "text", "", { required: true, placeholder: "00.000.000/0001-00" }));
    } else if (mode === "diagram") {
      gcKind.textContent = "diagrama";
      gcTitle.textContent = "Adicionar diagrama";
      gcLead.textContent = "";
      gcFields.appendChild(field("Título", "title", "text", "", { required: true, placeholder: "Fluxo, hipótese, mapa mental…" }));
      gcFields.appendChild(field("Conteúdo", "body", "textarea", "alvo --> empresa\nempresa --> socio", { rows: 6, placeholder: "alvo --> empresa\nempresa --> socio" }));
    } else {
      gcKind.textContent = "seta";
      gcTitle.textContent = "Adicionar ligação";
      gcLead.textContent = "";
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

  function removeNodesLocal(ids) {
    const gone = new Set((ids || []).filter(Boolean));
    if (!gone.size) return;
    gone.forEach((id) => {
      const el = cy.getElementById(id);
      if (el && el.length) el.remove();
    });
    payload.nodes = (payload.nodes || []).filter((node) => !gone.has(node.id));
    payload.edges = (payload.edges || []).filter((edge) => !gone.has(edge.source) && !gone.has(edge.target));
    rebuildNodeIndex();
  }

  function removeEdgesLocal(ids) {
    const gone = new Set((ids || []).filter(Boolean));
    if (!gone.size) return;
    gone.forEach((id) => {
      const el = cy.getElementById(id);
      if (el && el.length) el.remove();
    });
    payload.edges = (payload.edges || []).filter((edge) => !gone.has(edge.id));
  }

  async function postBoard(url, fields, status) {
    const body = new URLSearchParams();
    body.set("csrf_token", csrfToken());
    Object.entries(fields || {}).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => body.append(key, String(item)));
      else if (value != null) body.set(key, String(value));
    });
    const loading = (status && status.loading) || "Gravando no quadro…";
    const done = (status && status.done) || "Quadro atualizado.";
    const removeIds = (status && status.removeIds) || [];
    const removeEdgeIds = (status && status.removeEdgeIds) || [];
    const skipReload = !!(status && status.skipReload);
    mutating = true;
    if (removeIds.length) removeNodesLocal(removeIds);
    if (removeEdgeIds.length) removeEdgesLocal(removeEdgeIds);
    if (window.setActionStatus) window.setActionStatus("loading", loading);
    try {
      const res = await fetch(url, {
        method: "POST",
        body,
        credentials: "same-origin",
        redirect: "follow",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) throw new Error("http " + res.status);
      const ctype = (res.headers.get("content-type") || "").toLowerCase();
      if (ctype.includes("json")) {
        const data = await res.json();
        if (data && data.ok === false) throw new Error(data.error || "falhou");
        if (data) applyPulse(data);
      }
      if (window.setActionStatus) window.setActionStatus("ok", done);
      if (!skipReload) {
        try {
          await load();
        } catch (_) {
          if (window.setActionStatus) window.setActionStatus("error", "Ação feita. Recarregue se o grafo não mudou.");
        }
      }
    } catch (_) {
      if (removeIds.length) {
        try { await load(); } catch (err) { /* próximo poll tenta */ }
      }
      if (window.setActionStatus) window.setActionStatus("error", "Não concluiu nesta passagem. O grafo tenta de novo sozinho.");
    } finally {
      mutating = false;
      if (window.unlockActionForms) window.unlockActionForms();
      schedulePoll(800);
    }
  }

  function probeNode(id, label, kind) {
    const name = label || "nó";
    const fields = kind ? { kind: kind } : {};
    return postBoard(
      root.dataset.entityBase + id + "/procurar",
      fields,
      { loading: "Procurando informações de " + name + "…", done: "Informações adicionadas ao caso." }
    );
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
      if (composerMode === "cnpj") {
        await postBoard(root.dataset.companyUrl, {
          cnpj: String(data.get("cnpj") || ""),
          from_id: composer.dataset.entityId || seedNodeId(),
        }, { loading: "Ligando empresa…", done: "Empresa na fila — QSA entra sozinho." });
      } else if (composerMode === "link") {
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

  function seedNodeId() {
    const seed = cy.nodes().filter((n) => n.data("seed")).first();
    return seed && seed.length ? seed.id() : "";
  }

  function kindLabel(kind) {
    return ({
      EMAIL: "E-mail",
      USERNAME: "Rede social",
      PHONE: "Telefone",
      CPF: "CPF",
      NAME: "Nome",
      CNPJ: "CNPJ",
      COMPANIES: "Empresas",
      QSA: "QSA / sócios",
    })[kind] || kind;
  }

  function canProbe(kind) {
    return !!({
      NAME: 1, EMAIL: 1, USERNAME: 1, PHONE: 1, CPF: 1, CNPJ: 1, COMPANIES: 1, QSA: 1,
    })[kind];
  }

  function menuCheck(kind, extra, checked) {
    const label = document.createElement("label");
    label.className = "chk";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.name = "probe_kind";
    box.value = kind;
    box.checked = !!checked;
    const text = extra ? kindLabel(kind) + " · " + extra : kindLabel(kind);
    label.append(box, document.createTextNode(" " + text));
    return label;
  }

  function probeKinds(id, kinds, label) {
    const clean = (kinds || []).filter(Boolean);
    if (!clean.length) {
      if (window.setActionStatus) window.setActionStatus("error", "Escolha ao menos um dado para buscar.");
      return;
    }
    return postBoard(
      root.dataset.entityBase + id + "/procurar",
      { kinds: clean },
      { loading: "Buscando " + (label || clean.map(kindLabel).join(", ")) + "…", done: "Busca na fila — o grafo atualiza sozinho." }
    );
  }

  function validateNode(id) {
    return postBoard(root.dataset.entityBase + id + "/confirmar", {}, {
      loading: "Validando…",
      done: "Nó validado.",
    });
  }

  const lassoHost = document.querySelector(".graph-canvas") || stage || root;
  const lasso = document.createElement("div");
  lasso.className = "graph-lasso";
  lasso.hidden = true;
  if (lassoHost) lassoHost.appendChild(lasso);
  let lassoStart = null;

  function hideLasso() {
    lasso.hidden = true;
    lassoStart = null;
  }

  function lassoRect(event) {
    const box = root.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  function placeLasso(a, b) {
    const left = Math.min(a.x, b.x);
    const top = Math.min(a.y, b.y);
    lasso.hidden = false;
    lasso.style.left = left + "px";
    lasso.style.top = top + "px";
    lasso.style.width = Math.abs(b.x - a.x) + "px";
    lasso.style.height = Math.abs(b.y - a.y) + "px";
  }

  function selectInBox(a, b) {
    const left = Math.min(a.x, b.x);
    const right = Math.max(a.x, b.x);
    const top = Math.min(a.y, b.y);
    const bottom = Math.max(a.y, b.y);
    if (right - left < 6 && bottom - top < 6) return;
    cy.nodes(":visible").forEach((node) => {
      if (node.data("seed")) return;
      const bb = node.renderedBoundingBox({ includeLabels: false });
      if (bb.x1 < right && bb.x2 > left && bb.y1 < bottom && bb.y2 > top) node.select();
    });
    refreshSelectBar();
  }

  function selectedRemovable() {
    return cy.nodes(":selected").filter((node) => !node.data("seed"));
  }

  function refreshSelectBar() {
    if (!selectCount) return;
    const n = selectedRemovable().length;
    const seeds = cy.nodes(":selected").filter((node) => node.data("seed")).length;
    if (!n && !seeds) {
      selectCount.textContent = "Arraste no quadro para marcar nós.";
      return;
    }
    selectCount.textContent = n
      ? n + " nó(s) para excluir" + (seeds ? " · alvo permanece" : "")
      : "O alvo não pode ser excluído.";
  }

  function setSelectMode(on) {
    selectMode = !!on;
    hideMenu();
    stopLink();
    if (stage) stage.classList.toggle("is-selecting", selectMode);
    if (selectBtn) selectBtn.setAttribute("aria-pressed", selectMode ? "true" : "false");
    if (selectBar) selectBar.hidden = !selectMode;
    cy.boxSelectionEnabled(false);
    cy.userPanningEnabled(!selectMode);
    cy.autoungrabify(selectMode);
    cy.autounselectify(!selectMode);
    if (!selectMode) {
      cy.nodes().unselect();
      hideLasso();
    } else {
      cy.nodes().unselect();
      if (window.setActionStatus) window.setActionStatus("loading", "Arraste no quadro para marcar. O alvo não sai.");
    }
    refreshSelectBar();
  }

  function deleteSelectedArea() {
    const ids = selectedRemovable().map((node) => node.id());
    if (!ids.length) {
      if (window.setActionStatus) window.setActionStatus("error", "Nenhum nó além do alvo nesta área.");
      return;
    }
    if (!confirm("Excluir " + ids.length + " nó(s) desta área? O alvo permanece.")) return;
    postBoard(root.dataset.batchUrl, { entity_ids: ids }, {
      loading: "Removendo a área…",
      done: ids.length + " nó(s) excluídos.",
      skipReload: true,
      removeIds: ids,
    });
    setSelectMode(false);
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
      const type = node.data("type") || "";
      const label = node.data("name") || node.data("label") || "";
      const status = node.data("status") || "";
      const ids = node.data("ids") || [];
      head.textContent = node.data("seed") ? "alvo" : "nó";
      menu.appendChild(head);
      if (type === "ORG") {
        menu.appendChild(menuButton("Buscar sócios (QSA)", () => probeKinds(node.id(), ["QSA"], "sócios")));
        menu.appendChild(menuButton("Buscar empresas relacionadas", () => probeKinds(node.id(), ["COMPANIES"], "empresas")));
      } else {
        const picks = document.createElement("div");
        picks.className = "picks";
        const hint = document.createElement("div");
        hint.className = "k";
        hint.textContent = "o que buscar";
        picks.appendChild(hint);
        picks.appendChild(menuCheck("NAME", label, false));
        ids.forEach((item) => {
          if (!item || !item.kind || item.kind === "NAME" || !canProbe(item.kind)) return;
          picks.appendChild(menuCheck(item.kind, formatCardId(item), false));
        });
        menu.appendChild(picks);
        menu.appendChild(menuButton("Buscar dados selecionados", () => {
          const chosen = [...menu.querySelectorAll("input[name=probe_kind]:checked")].map((box) => box.value);
          probeKinds(node.id(), chosen, chosen.map(kindLabel).join(", "));
        }));
        menu.appendChild(menuButton("Buscar empresas deste alvo", () => probeKinds(node.id(), ["COMPANIES"], "empresas")));
        menu.appendChild(menuButton("Adicionar empresa (CNPJ)", () => openComposer("cnpj", { entityId: node.id() })));
      }
      menu.appendChild(menuButton("Abrir ficha", () => {
        window.location.href = root.dataset.entityBase + node.id();
      }));
      menu.appendChild(menuButton("Adicionar anotação", () => openComposer("note", { entityId: node.id() })));
      menu.appendChild(menuButton("Adicionar diagrama", () => openComposer("diagram", { entityId: node.id() })));
      menu.appendChild(menuButton("Ligar seta a outro nó", () => startLink(node.id())));
      const sep = document.createElement("div");
      sep.className = "sep";
      menu.appendChild(sep);
      if (status !== "confirmed") {
        menu.appendChild(menuButton("Validar este nó", () => validateNode(node.id())));
      }
      menu.appendChild(menuButton("Expandir daqui", () => {
        postBoard(root.dataset.entityBase + node.id() + "/expandir", {}, {
          loading: "Rodando expansão…",
          done: "Expansão na fila — o grafo atualiza sozinho.",
        });
      }));
      menu.appendChild(menuButton("Copiar nome", () => {
        const text = node.data("name") || node.data("label") || "";
        if (navigator.clipboard) navigator.clipboard.writeText(text);
      }));
      if (!node.data("seed")) {
        menu.appendChild(menuButton(status === "confirmed" ? "Excluir nó" : "Excluir (não validado)", () => {
          if (confirm("Excluir este nó e o que só existe por causa dele?")) {
            postBoard(root.dataset.entityBase + node.id() + "/desligar", {}, {
              loading: "Removendo…",
              done: "Nó excluído.",
              skipReload: true,
              removeIds: [node.id()],
            });
          }
        }));
      }
    } else if (kind === "edge") {
      const edge = evt.target;
      head.textContent = "seta";
      menu.appendChild(head);
      menu.appendChild(menuButton("Editar ligação", () => {
        window.location.href = root.dataset.edgeBase + edge.id();
      }));
      menu.appendChild(menuButton("Apagar seta", () => {
        if (confirm("Remover só esta ligação?")) {
          postBoard(root.dataset.edgeBase + edge.id() + "/apagar", {}, {
            loading: "Removendo…",
            done: "Ligação removida.",
            skipReload: true,
            removeEdgeIds: [edge.id()],
          });
        }
      }));
    } else {
      head.textContent = "quadro";
      menu.appendChild(head);
      menu.appendChild(menuButton("Adicionar empresa (CNPJ)", () => openComposer("cnpj", { entityId: seedNodeId() })));
      menu.appendChild(menuButton("Selecionar área e excluir", () => setSelectMode(true)));
      menu.appendChild(menuButton("Adicionar anotação", () => openComposer("note")));
      menu.appendChild(menuButton("Adicionar diagrama", () => openComposer("diagram")));
      menu.appendChild(menuButton("Adicionar ligação (seta)", () => startLink(null)));
    }
    placeMenu(orig.clientX || 16, orig.clientY || 16);
  }

  cy.on("cxttap", "node", (evt) => {
    evt.preventDefault();
    if (selectMode) return;
    showMenu(evt, "node");
  });
  cy.on("cxttap", "edge", (evt) => {
    evt.preventDefault();
    if (selectMode) return;
    showMenu(evt, "edge");
  });
  cy.on("cxttap", (evt) => {
    if (evt.target !== cy) return;
    evt.preventDefault();
    if (selectMode) {
      setSelectMode(false);
      return;
    }
    showMenu(evt, "bg");
  });
  function blockBrowserMenu(event) {
    if (!event.target || !event.target.closest) return;
    if (event.target.closest(".graph-main, .graph-panel, .graph-stage, .graph-canvas, #cy, #graph-menu, #graph-composer, .graph-balloon, .graph-select-bar, .canvas-tools")) {
      event.preventDefault();
      event.stopPropagation();
    }
  }
  document.addEventListener("contextmenu", blockBrowserMenu, true);
  if (menu) {
    menu.addEventListener("click", (event) => event.stopPropagation());
    menu.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
  }
  if (selectBtn) selectBtn.addEventListener("click", () => setSelectMode(!selectMode));
  const selectDelete = document.getElementById("graph-select-delete");
  const selectCancel = document.getElementById("graph-select-cancel");
  if (selectDelete) selectDelete.addEventListener("click", deleteSelectedArea);
  if (selectCancel) selectCancel.addEventListener("click", () => setSelectMode(false));
  if (selectBar) selectBar.addEventListener("click", (event) => event.stopPropagation());
  root.addEventListener("mousedown", (event) => {
    if (!selectMode || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    lassoStart = lassoRect(event);
    placeLasso(lassoStart, lassoStart);
  }, true);
  window.addEventListener("mousemove", (event) => {
    if (!selectMode || !lassoStart) return;
    placeLasso(lassoStart, lassoRect(event));
  });
  window.addEventListener("mouseup", (event) => {
    if (!selectMode || !lassoStart) return;
    selectInBox(lassoStart, lassoRect(event));
    hideLasso();
  });
  cy.on("select unselect", "node", () => {
    if (selectMode) refreshSelectBar();
  });
  document.addEventListener("click", hideMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    hideMenu();
    closeComposer();
    stopLink();
    if (selectMode) setSelectMode(false);
  });

  document.querySelectorAll('form[action*="/explodir"], form[action*="/processar"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const exploding = (form.getAttribute("action") || "").includes("/explodir");
      postBoard(form.action, {}, {
        loading: exploding ? "Rodando QSA…" : "Rodando fila…",
        done: exploding ? "QSA na fila — o grafo atualiza sozinho." : "Lote na fila — o grafo atualiza sozinho.",
      });
    });
  });
  document.querySelectorAll('form[action*="/buscar-ferramentas"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const tools = [...form.querySelectorAll('input[name="tools"]:checked')].map((input) => input.value);
      postBoard(form.action, { tools }, {
        loading: "Buscando com as ferramentas do grafo…",
        done: "Infos acrescentadas — o grafo não substituiu o que já existia.",
      });
    });
  });

  if (root.dataset.statusInit && window.setActionStatus) {
    window.setActionStatus(root.dataset.statusPhase || "loading", root.dataset.statusInit);
  }
  load().catch(() => {
    if (window.setActionStatus) window.setActionStatus("error", "Não deu para desenhar o grafo. Recarregue a página.");
  });
  poll();
})();
