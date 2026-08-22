(function () {
  const root = document.getElementById("cy");
  if (!root) return;
  if (typeof cytoscape === "undefined") {
    root.classList.add("is-dead");
    root.textContent = "O motor do grafo não carregou (Cytoscape). Recarregue a página ou libere o CDN unpkg.com.";
    return;
  }

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

  function previewKindOf(n) {
    const attrs = (n && n.attrs) || {};
    return String(attrs.preview_kind || attrs.tipo || "");
  }

  function officialSourceUrl(n) {
    const attrs = (n && n.attrs) || {};
    for (const key of ["page_url", "fonte", "maps_url"]) {
      const val = String(attrs[key] || "");
      if (/^https?:\/\//i.test(val)) return val;
    }
    const key = String((n && n.key) || "");
    return key.indexOf("url:") === 0 ? key.slice(4) : "";
  }

  function urlLooksPdf(url) {
    return /\.pdf(\b|$)/i.test(url || "") || /\/pdf\//i.test(url || "");
  }

  function pdfPlaceholder(url, label) {
    const raw = String(url || label || "documento.pdf");
    let name = raw.split("/").pop() || "documento.pdf";
    try { name = decodeURIComponent(name.split("?")[0]); } catch (err) {}
    name = name.replace(/[<>&"']/g, "").slice(0, 26) || "documento.pdf";
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="148">' +
      '<rect width="128" height="148" fill="#120e08"/>' +
      '<rect x="16" y="14" width="96" height="120" rx="3" fill="#1c140c" stroke="#d4b45a" stroke-width="1.5"/>' +
      '<text x="64" y="72" text-anchor="middle" fill="#d4b45a" font-size="20" font-family="IBM Plex Mono,monospace">PDF</text>' +
      '<text x="64" y="118" text-anchor="middle" fill="#d7e4dc" font-size="8" font-family="IBM Plex Mono,monospace">' +
      name +
      "</text></svg>";
    return "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
  }

  function nodeThumb(n) {
    const attrs = n.attrs || {};
    const thumb = attrs.thumb || attrs.profile_photo || "";
    if (thumb) return thumb;
    const url = officialSourceUrl(n);
    if (previewKindOf(n) === "pdf" || urlLooksPdf(url) || urlLooksPdf(n.key || "")) {
      return pdfPlaceholder(url || n.key || n.label, n.label);
    }
    return "";
  }

  function isPhotoCard(n) {
    const attrs = n.attrs || {};
    if (attrs.tipo === "imagem" || attrs.tipo === "pdf" || attrs.preview_kind === "pdf") return true;
    if (attrs.thumb || attrs.profile_photo) {
      return n.type === "PERSON" || n.type === "PUBLICATION" || n.type === "PROFILE";
    }
    return false;
  }

  function cardLabel(n) {
    const attrs = n.attrs || {};
    if (isPhotoCard(n)) {
      const title = String(attrs.og_title || n.label || "Imagem").replace(/^https?:\/\/\S+/i, "Imagem").slice(0, 42);
      return title + (n.seed ? " · alvo" : "");
    }
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
        thumb: nodeThumb(n),
        tipo: (n.attrs || {}).tipo || (n.attrs || {}).preview_kind || "",
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
    selectionType: "single",
    autounselectify: true,
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
      {
        selector: 'node[tipo = "imagem"][?thumb]',
        style: {
          "background-image": "data(thumb)",
          "background-fit": "cover",
          "background-clip": "node",
          width: 128,
          height: 148,
          "text-valign": "bottom",
          "text-margin-y": 4,
          "font-size": 9,
          "text-max-width": 118,
          "background-color": "#0c1410",
        },
      },
      { selector: 'node[type = "PERSON"]', style: { "border-color": colors.PERSON } },
      {
        selector: 'node[type = "PERSON"][?thumb]',
        style: {
          "background-image": "data(thumb)",
          "background-fit": "cover",
          "background-clip": "node",
          width: 132,
          height: 156,
          "text-valign": "bottom",
          "text-margin-y": 4,
          "font-size": 9,
          "text-max-width": 120,
          "background-color": "#0c1410",
        },
      },
      {
        selector: 'node[type = "PERSON"][?thumb][?seed]',
        style: { width: 148, height: 172, "border-width": 2, "border-color": "#6f9b82" },
      },
      { selector: 'node[type = "NOTE"]', style: { "border-color": colors.NOTE, "background-color": "#1c1a10" } },
      { selector: 'node[kind = "diagram"]', style: { width: 210, height: 64, "border-color": "#d4b45a", "background-color": "#1c1810", "text-wrap": "wrap", "text-max-width": 190 } },
      {
        selector: 'node[kind = "category"]',
        style: {
          width: 200,
          height: 30,
          shape: "round-rectangle",
          "background-color": "#14180c",
          "border-color": "#d4b45a",
          "border-width": 1,
          "font-size": 10,
          "font-weight": 600,
          color: "#d4b45a",
          "text-valign": "center",
          "text-max-width": 188,
          padding: "4px",
        },
      },
      { selector: "node[?seed]", style: { width: 210, height: 58, "border-color": "#6f9b82", "border-width": 2, "background-color": "#15241c" } },
      { selector: "node[lines > 1]", style: { height: 72 } },
      { selector: "node[lines > 2]", style: { height: 90 } },
      { selector: "node[lines > 3]", style: { height: 108 } },
      { selector: "node[lines > 4]", style: { height: 124 } },
      { selector: 'node[status = "unconfirmed"]', style: { "border-style": "dashed", "border-color": "#c4a35a", "opacity": 0.85 } },
      { selector: 'node[status = "probable"]', style: { "border-style": "dotted", "border-color": "#5eead4" } },
      { selector: 'node[status = "contested"]', style: { "border-color": "#ffe14a" } },
      { selector: 'node[status = "false"]', style: { "border-color": "#ff5c7a", "opacity": 0.45 } },
      {
        selector: 'node[?thumb][type = "PUBLICATION"], node[?thumb][type = "PROFILE"]',
        style: {
          "background-image": "data(thumb)",
          "background-fit": "cover",
          "background-clip": "node",
          width: 132,
          height: 156,
          "text-valign": "bottom",
          "text-margin-y": 4,
          "font-size": 9,
          "text-max-width": 120,
          "background-color": "#0c1410",
        },
      },
      {
        selector: 'node[tipo = "pdf"]',
        style: {
          "background-image": "data(thumb)",
          "background-fit": "cover",
          "background-clip": "node",
          width: 128,
          height: 148,
          "text-valign": "bottom",
          "text-margin-y": 4,
          "font-size": 9,
          "text-max-width": 118,
          "background-color": "#1a1208",
          "border-color": "#d4b45a",
        },
      },
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
    const nodes = cy.nodes(":visible").filter((node) => !isCategoryLabel(node)).toArray();
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
      if (node.data("kind") === "category") return;
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
    const nodes = capturePositions();
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

  const CATEGORY_ORDER = [
    { id: "person", label: "Pessoa" },
    { id: "org", label: "Empresa" },
    { id: "social", label: "Rede social" },
    { id: "news", label: "Matéria" },
    { id: "doc", label: "Documento" },
    { id: "image", label: "Imagem" },
    { id: "case", label: "Processo" },
    { id: "asset", label: "Ativo" },
    { id: "vehicle", label: "Veículo" },
    { id: "note", label: "Anotação" },
    { id: "other", label: "Outro" },
  ];

  function isCategoryLabel(node) {
    return node.data("kind") === "category";
  }

  function nodeCategory(node) {
    const type = node.data("type") || "";
    const attrs = node.data("attrs") || {};
    const tipo = String(attrs.tipo || attrs.preview_kind || "").toLowerCase();
    if (type === "PERSON") return "person";
    if (type === "ORG") return "org";
    if (type === "PROFILE" || tipo === "social") return "social";
    if (tipo === "pdf" || tipo === "diario") return "doc";
    if (tipo === "imagem" || tipo === "image") return "image";
    if (type === "PUBLICATION" || tipo === "noticia" || tipo === "article" || tipo === "mencao") return "news";
    if (type === "CASE") return "case";
    if (type === "ASSET") return "asset";
    if (type === "VEHICLE") return "vehicle";
    if (type === "NOTE") return "note";
    return "other";
  }

  function removeCategoryLabels() {
    const labels = cy.nodes().filter(isCategoryLabel);
    if (labels.length) labels.remove();
  }

  function applyCategoryLayout() {
    removeCategoryLabels();
    const nodes = cy
      .nodes()
      .filter((node) => !isCategoryLabel(node) && node.style("display") !== "none")
      .toArray();
    if (!nodes.length) return;
    const groups = new Map(CATEGORY_ORDER.map((cat) => [cat.id, []]));
    nodes.forEach((node) => {
      const id = nodeCategory(node);
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(node);
    });
    const colW = 236;
    const catGap = 88;
    const rowGap = 22;
    const wrapAfter = 14;
    let cursorX = 0;
    CATEGORY_ORDER.forEach((cat) => {
      const list = groups.get(cat.id) || [];
      if (!list.length) return;
      list.sort((a, b) => {
        if (!!a.data("seed") !== !!b.data("seed")) return a.data("seed") ? -1 : 1;
        return String(a.data("name") || a.data("label") || "").localeCompare(
          String(b.data("name") || b.data("label") || ""),
          "pt"
        );
      });
      const cols = Math.max(1, Math.ceil(list.length / wrapAfter));
      const heights = Array.from({ length: cols }, () => 58);
      cy.add({
        group: "nodes",
        selectable: false,
        grabbable: false,
        data: {
          id: "cat:" + cat.id,
          name: cat.label,
          label: cat.label,
          type: "NOTE",
          kind: "category",
          cat: cat.id,
          attrs: {},
          ids: [],
          thumb: "",
          tipo: "",
          seed: false,
          status: "confirmed",
          depth: 0,
          key: "",
        },
        position: { x: cursorX + ((cols - 1) * colW) / 2, y: 0 },
      });
      list.forEach((node, index) => {
        const col = Math.floor(index / wrapAfter);
        const h = node.outerHeight();
        const x = cursorX + col * colW;
        const y = heights[col] + h / 2;
        node.position({ x, y });
        heights[col] += h + rowGap;
      });
      cursorX += cols * colW + catGap;
    });
    const box = visibleElements();
    if (box.nodes().length) cy.fit(box, 56);
    laidOnce = true;
    layoutLocked = true;
    scheduleSaveLayout();
  }

  function placeCategoryLabelsFromPositions() {
    removeCategoryLabels();
    const groups = new Map(CATEGORY_ORDER.map((cat) => [cat.id, []]));
    cy.nodes().forEach((node) => {
      if (isCategoryLabel(node) || node.style("display") === "none") return;
      const id = nodeCategory(node);
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(node);
    });
    CATEGORY_ORDER.forEach((cat) => {
      const list = groups.get(cat.id) || [];
      if (!list.length) return;
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      list.forEach((node) => {
        const pos = node.position();
        minX = Math.min(minX, pos.x);
        maxX = Math.max(maxX, pos.x);
        minY = Math.min(minY, pos.y - node.outerHeight() / 2);
      });
      cy.add({
        group: "nodes",
        selectable: false,
        grabbable: false,
        data: {
          id: "cat:" + cat.id,
          name: cat.label,
          label: cat.label,
          type: "NOTE",
          kind: "category",
          cat: cat.id,
          attrs: {},
          ids: [],
          thumb: "",
          tipo: "",
          seed: false,
          status: "confirmed",
          depth: 0,
          key: "",
        },
        position: { x: (minX + maxX) / 2, y: minY - 36 },
      });
    });
  }

  function applyLayout(view) {
    if (view !== "ordenar") removeCategoryLabels();
    const eles = visibleElements();
    if (!eles.nodes().length) return;
    if (view === "ordenar") {
      applyCategoryLayout();
      return;
    }
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

  let placeMap = null;

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

  function geoStreetLayer() {
    return L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: "OSM · CARTO",
      subdomains: "abcd",
      maxZoom: 18,
    });
  }

  function geoSatLayer() {
    return L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      attribution: "Esri · Maxar · Earthstar",
      maxZoom: 19,
    });
  }

  function geoMarkIcon() {
    return L.divIcon({
      className: "geo-mark",
      html: '<span class="geo-pulse"></span><span class="geo-core"></span>',
      iconSize: [22, 22],
      iconAnchor: [11, 11],
      popupAnchor: [0, -12],
    });
  }

  function attachGeoBasemap(host, leaflet, start) {
    const street = geoStreetLayer();
    const sat = geoSatLayer();
    let mode = start === "street" ? "street" : "sat";
    function apply(next) {
      mode = next === "street" ? "street" : "sat";
      if (mode === "street") {
        if (leaflet.hasLayer(sat)) leaflet.removeLayer(sat);
        if (!leaflet.hasLayer(street)) street.addTo(leaflet);
        if (leaflet.getZoom() > 18) leaflet.setZoom(18);
      } else {
        if (leaflet.hasLayer(street)) leaflet.removeLayer(street);
        if (!leaflet.hasLayer(sat)) sat.addTo(leaflet);
      }
      host.classList.toggle("is-street", mode === "street");
      host.querySelectorAll(".geo-basemap [data-base]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.base === mode);
      });
    }
    let bar = host.querySelector(".geo-basemap");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "geo-basemap track-group";
      bar.innerHTML =
        '<button type="button" class="track-item" data-base="sat">Satélite</button>' +
        '<button type="button" class="track-item" data-base="street">Mapa</button>';
      host.appendChild(bar);
    }
    bar.querySelectorAll("[data-base]").forEach((btn) => {
      btn.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        apply(btn.dataset.base);
      };
    });
    apply(mode);
    return apply;
  }

  function destroyPlaceMap() {
    if (!placeMap) return;
    placeMap.remove();
    placeMap = null;
  }

  function mountPlaceMap(host, lat, lng) {
    destroyPlaceMap();
    if (!host || typeof L === "undefined") return;
    host.classList.add("geo-stage", "is-ready");
    placeMap = L.map(host, {
      zoomControl: false,
      attributionControl: true,
      fadeAnimation: false,
    }).setView([lat, lng], 19);
    L.control.zoom({ position: "bottomright" }).addTo(placeMap);
    attachGeoBasemap(host, placeMap, "sat");
    L.marker([lat, lng], { icon: geoMarkIcon(), keyboard: false }).addTo(placeMap);
    window.setTimeout(() => {
      if (!placeMap) return;
      placeMap.invalidateSize();
      placeMap.setView([lat, lng], 19);
    }, 80);
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

  function mapPlaces() {
    return (payload.nodes || []).filter((n) => {
      if (String((n.key || "")).indexOf("geo:") === 0) return false;
      const a = n.attrs || {};
      if (a.lat != null && a.lng != null) return n.type === "ORG" || n.type === "ASSET" || n.type === "VEHICLE";
      return n.type === "ORG";
    });
  }

  function renderMap() {
    const el = document.getElementById("org-map");
    if (!el || typeof L === "undefined") return;
    const places = mapPlaces();
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
    el.classList.add("geo-stage");
    attachGeoBasemap(el, map, "street");
    L.control.zoom({ position: "bottomright" }).addTo(map);
    const icon = geoMarkIcon();
    const bounds = [];
    let plotted = 0;
    places.forEach((node) => {
      const latlng = markerLatLng(node);
      if (!latlng) return;
      plotted += 1;
      bounds.push(latlng);
      const a = node.attrs || {};
      const loc = [a.endereco, a.municipio, a.uf].filter(Boolean).join(" · ") || "UF aproximada";
      const exact = a.lat != null && a.lng != null;
      const kind = node.type === "ORG" ? "empresa" : node.type === "ASSET" ? "imóvel" : "local";
      const maps = exact
        ? "https://www.google.com/maps/@" + Number(a.lat).toFixed(6) + "," + Number(a.lng).toFixed(6) + ",18z/data=!3m1!1e3"
        : "";
      const marker = L.marker(latlng, { icon, keyboard: false }).addTo(map);
      marker.bindPopup(
        `<div class="geo-pop">` +
          `<p class="type-tag">${kind}</p>` +
          `<strong>${escapeHtml(node.label)}</strong>` +
          `<p>${escapeHtml(a.situacao || a.tipo_imovel || "localização")}</p>` +
          `<p class="muted">${escapeHtml(loc)}${exact ? "" : " · pin pela UF"}</p>` +
          (a.nota ? `<p class="muted">${escapeHtml(a.nota)}</p>` : "") +
          (maps ? `<a class="btn primary" href="${maps}" target="_blank" rel="noopener noreferrer">Google Maps satélite</a>` : "") +
          `<a class="btn" href="${root.dataset.entityBase}${node.id}">abrir ficha</a>` +
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
      `<span>${places.length - plotted ? (places.length - plotted) + " sem pin" : "satélite"}</span>`;
    const savedMap = (payload.layout || {}).map;
    if (savedMap && savedMap.lat != null && savedMap.lng != null) {
      map.setView([Number(savedMap.lat), Number(savedMap.lng)], Number(savedMap.zoom) || 4);
    } else if (bounds.length) {
      const close = places.some((n) => n.attrs && n.attrs.lat != null && n.attrs.lng != null);
      map.fitBounds(bounds, { padding: [36, 36], maxZoom: close ? 17 : 11 });
    }
    const refreshMapSize = () => {
      if (!map) return;
      map.invalidateSize({ animate: false });
    };
    requestAnimationFrame(() => {
      refreshMapSize();
      window.setTimeout(refreshMapSize, 60);
      window.setTimeout(refreshMapSize, 240);
    });
  }

  function activeView() {
    const active = document.querySelector(".view-tab.is-active");
    return (active && active.dataset.view) || "rede";
  }

  function setView(view, opts) {
    const restore = !!(opts && opts.restore);
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
    if (view === "mapa" && typeof setSelectMode === "function") setSelectMode(false);
    if (view === "split") renderSplit();
    if (view === "mapa") renderMap();
    const sortBtn = document.getElementById("ct-sort");
    if (sortBtn) sortBtn.setAttribute("aria-pressed", view === "ordenar" ? "true" : "false");
    if (view === "mapa") {
      removeCategoryLabels();
      return;
    }
    if (restore && hasLockedLayout()) {
      applySavedPositions(savedNodeMap());
      if (view === "ordenar") placeCategoryLabelsFromPositions();
      else removeCategoryLabels();
      laidOnce = true;
      return;
    }
    if (view === "arvore" || view === "ordenar") {
      applyLayout(view);
      layoutLocked = true;
      scheduleSaveLayout();
      return;
    }
    removeCategoryLabels();
    if (hasLockedLayout()) applySavedPositions(savedNodeMap());
    else applyLayout(view);
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
    if ((payload.years || []).length) {
      const first = String(payload.years[0]);
      const last = String(payload.years[payload.years.length - 1]);
      const targets = [yearInput, yearMin, yearMax].filter(Boolean);
      const ready = yearMin || yearInput;
      if (ready && !ready.dataset.ready) {
        targets.forEach((input) => {
          input.min = first;
          input.max = last;
        });
        if (yearMin) yearMin.value = first;
        if (yearMax) yearMax.value = last;
        if (yearInput) yearInput.value = last;
        if (ready) ready.dataset.ready = "1";
        paintYearRange();
      }
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
      if (nextView === "ordenar") placeCategoryLabelsFromPositions();
    } else {
      setView(nextView, { restore: true });
      const layout = payload.layout || {};
      if (layout.zoom) {
        applySnapshot({ kind: "cy", zoom: layout.zoom, x: (layout.pan || {}).x || 0, y: (layout.pan || {}).y || 0 });
      } else {
        cy.fit(undefined, 48);
      }
      laidOnce = true;
      if (!layoutLocked) scheduleSaveLayout();
      applyFilters();
    }
    lastLoadAt = Date.now();
    hydrateMedia();
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
    banco: "banco",
    agencia: "agência",
    conta: "conta",
    tipo_conta: "tipo",
    pix: "PIX",
    fonte: "fonte",
    page_url: "página",
    snippet: "trecho",
    via: "via",
    tipo: "tipo",
    quando: "quando",
    valor: "valor",
    ano: "ano",
    patrimonio_estimado: "patrimônio",
    patrimonio_ano: "ano da estimativa",
    patrimonio_fonte: "fonte do patrimônio",
    tipo_imovel: "tipo do imóvel",
    matricula: "matrícula (informada)",
    network: "rede",
    preview_kind: "prévia",
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

  function officialUrl(rec, el) {
    const bag = (rec && rec.attrs) || (el && el.data && el.data("attrs")) || {};
    for (const key of ["maps_url", "page_url", "fonte"]) {
      const val = String(bag[key] || "");
      if (/^https?:\/\//i.test(val)) return val;
    }
    const key = (rec && rec.key) || (el && el.data && el.data("key")) || "";
    if (String(key).indexOf("url:") === 0) return String(key).slice(4);
    return "";
  }

  function fonteUrl(id) {
    return id && root.dataset.entityBase ? root.dataset.entityBase + id + "/fonte" : "";
  }

  function applyPreviewMap(previews) {
    Object.entries(previews || {}).forEach(([id, bag]) => {
      if (!bag || !bag.thumb) return;
      const rec = nodeIndex.get(id);
      if (rec) rec.attrs = { ...(rec.attrs || {}), ...bag };
      const el = cy.getElementById(id);
      if (!el.nonempty()) return;
      const attrs = { ...(el.data("attrs") || {}), ...bag };
      el.data({ thumb: bag.thumb, attrs, tipo: attrs.tipo || el.data("tipo") || "" });
    });
  }

  function setupPdfJs() {
    const lib = window.pdfjsLib;
    if (!lib) return null;
    if (!lib.GlobalWorkerOptions.workerSrc) {
      lib.GlobalWorkerOptions.workerSrc = "https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
    }
    return lib;
  }

  async function renderPdfThumb(entityId) {
    const lib = setupPdfJs();
    if (!lib) throw new Error("pdfjs");
    const pdf = await lib.getDocument({ url: fonteUrl(entityId), withCredentials: true }).promise;
    const page = await pdf.getPage(1);
    const viewport = page.getViewport({ scale: 0.55 });
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.floor(viewport.width));
    canvas.height = Math.max(1, Math.floor(viewport.height));
    await page.render({ canvasContext: canvas.getContext("2d"), viewport, intent: "display" }).promise;
    return canvas.toDataURL("image/jpeg", 0.74);
  }

  let hydrating = false;
  async function hydrateMedia() {
    if (hydrating) return;
    hydrating = true;
    try {
      if (root.dataset.previewUrl) {
        const res = await fetch(root.dataset.previewUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ csrf_token: csrfToken() }),
        });
        if (res.ok) {
          const body = await res.json();
          applyPreviewMap(body.previews);
        }
      }
      const pdfs = cy.nodes().filter((node) => {
        if (isCategoryLabel(node)) return false;
        const attrs = node.data("attrs") || {};
        const url = officialUrl({ attrs, key: node.data("key") }, node);
        const kind = attrs.preview_kind || attrs.tipo || "";
        const thumb = String(node.data("thumb") || "");
        return (kind === "pdf" || urlLooksPdf(url)) && (!thumb || thumb.indexOf("data:image/svg") === 0);
      });
      if (setupPdfJs()) {
        const list = pdfs.toArray().slice(0, 14);
        for (let i = 0; i < list.length; i += 1) {
          try {
            const node = list[i];
            const dataUrl = await renderPdfThumb(node.id());
            node.data("thumb", dataUrl);
            const attrs = { ...(node.data("attrs") || {}), thumb: dataUrl };
            node.data("attrs", attrs);
            const rec = nodeIndex.get(node.id());
            if (rec) rec.attrs = attrs;
          } catch (_) {}
        }
      }
    } finally {
      hydrating = false;
    }
  }

  function buildSourcePreview(attrs, sourceUrl, type, fallbackThumb, entityId) {
    const wrap = document.createElement("div");
    wrap.className = "graph-balloon-preview";
    const kind = String(attrs.preview_kind || attrs.tipo || (urlLooksPdf(sourceUrl) ? "pdf" : "") || "");
    const thumb = String(attrs.thumb || fallbackThumb || "");
    const embed = String(attrs.embed_url || "");
    const title = String(attrs.og_title || "").trim();
    const desc = String(attrs.description || attrs.snippet || "").trim();
    const isStory = kind === "article" || kind === "noticia" || kind === "mencao" || kind === "diario" || type === "PUBLICATION";
    const isSocial = kind === "social" || type === "PROFILE";
    const isPdf = kind === "pdf" || urlLooksPdf(sourceUrl);
    const isImage = kind === "image" || kind === "imagem";

    if (isSocial) {
      const kicker = document.createElement("p");
      kicker.className = "graph-balloon-kicker";
      kicker.textContent = "Prévia do perfil" + (attrs.network ? " · " + attrs.network : "");
      wrap.appendChild(kicker);
    } else if (isPdf) {
      const kicker = document.createElement("p");
      kicker.className = "graph-balloon-kicker";
      kicker.textContent = "Prévia do documento";
      wrap.appendChild(kicker);
    } else if (isStory) {
      const kicker = document.createElement("p");
      kicker.className = "graph-balloon-kicker";
      kicker.textContent = "Matéria";
      wrap.appendChild(kicker);
    } else if (isImage) {
      const kicker = document.createElement("p");
      kicker.className = "graph-balloon-kicker";
      kicker.textContent = "Imagem da fonte";
      wrap.appendChild(kicker);
    }

    if (isPdf && (entityId || sourceUrl)) {
      const frame = document.createElement("iframe");
      frame.className = "graph-balloon-embed graph-balloon-pdf";
      frame.src = fonteUrl(entityId) || sourceUrl;
      frame.title = "Prévia do PDF";
      wrap.appendChild(frame);
    } else if (embed) {
      const frame = document.createElement("iframe");
      frame.className = "graph-balloon-embed";
      frame.src = embed;
      frame.title = "Prévia";
      frame.allow = "accelerometer; autoplay; encrypted-media; picture-in-picture";
      wrap.appendChild(frame);
    } else if (thumb && (/^https?:\/\//i.test(thumb) || thumb.indexOf("data:image") === 0)) {
      const pic = document.createElement("img");
      pic.className = "graph-balloon-thumb";
      pic.src = thumb;
      pic.alt = title || "";
      pic.referrerPolicy = "no-referrer";
      wrap.appendChild(pic);
    }

    if (isStory || isSocial) {
      if (title) {
        const heading = document.createElement("p");
        heading.className = "graph-balloon-story-title";
        heading.textContent = title;
        wrap.appendChild(heading);
      }
      if (desc) {
        const body = document.createElement("p");
        body.className = "graph-balloon-desc";
        body.textContent = desc;
        wrap.appendChild(body);
      }
    }
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
    if (!full) destroyPlaceMap();
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
    if (isCategoryLabel(el)) {
      const cat = el.data("cat");
      const count = cy.nodes().filter((node) => !isCategoryLabel(node) && nodeCategory(node) === cat && node.style("display") !== "none").length;
      gbKind.textContent = "categoria";
      gbTitle.textContent = el.data("label") || "Grupo";
      gbLead.textContent = count + (count === 1 ? " item nesta faixa" : " itens nesta faixa");
      gbFacts.replaceChildren();
      gbFacts.hidden = true;
      gbActions.hidden = !full;
      gbActions.replaceChildren();
      if (full) {
        const close = document.createElement("button");
        close.type = "button";
        close.className = "btn";
        close.textContent = "Fechar";
        close.addEventListener("click", closeBalloon);
        gbActions.appendChild(close);
      }
      return;
    }
    const rec = nodeRecord(el);
    const attrs = rec.attrs || el.data("attrs") || {};
    const type = el.data("type") || rec.type || "";
    const status = el.data("status") || rec.status || "confirmed";
    const neighbors = el.neighborhood("node").map((n) => n.data("name") || n.data("label")).filter(Boolean);
    const sourceUrl = officialUrl(rec, el);
    const kind = String(attrs.preview_kind || attrs.tipo || (urlLooksPdf(sourceUrl) ? "pdf" : "") || "");
    const storyTitle = String(attrs.og_title || "").trim();
    gbKind.textContent = TYPE_LABEL[type] || type || "nó";
    gbTitle.textContent = storyTitle || el.data("name") || rec.label || "nó";
    const labels = { unconfirmed: "Candidato", probable: "Provável", contested: "Contestado", false: "Falso", confirmed: "" };
    gbLead.textContent = labels[status] || (kind === "social" && attrs.network ? "Perfil · " + attrs.network : "");
    gbFacts.replaceChildren();
    gbFacts.hidden = !full;
    if (full) {
      destroyPlaceMap();
      const lat = Number(attrs.lat);
      const lng = Number(attrs.lng);
      const hasGeo = Number.isFinite(lat) && Number.isFinite(lng);
      if (!hasGeo) {
        const preview = buildSourcePreview(attrs, sourceUrl, type, el.data("thumb") || "", el.id());
        if (preview.childNodes.length) gbFacts.appendChild(preview);
      }
      if (hasGeo) {
        const box = document.createElement("div");
        box.className = "graph-balloon-map geo-stage";
        box.addEventListener("click", (event) => event.stopPropagation());
        box.addEventListener("mousedown", (event) => event.stopPropagation());
        box.addEventListener("wheel", (event) => event.stopPropagation());
        gbFacts.appendChild(box);
        requestAnimationFrame(() => {
          mountPlaceMap(box, lat, lng);
          placeBalloon(el);
        });
      }
      const key = rec.key || el.data("key") || "";
      if (key && key.indexOf("url:") !== 0) gbFacts.appendChild(factRow("chave", key));
      if (sourceUrl) gbFacts.appendChild(factRow("fonte oficial", sourceUrl));
      gbFacts.appendChild(factRow("tipo", TYPE_LABEL[type] || type));
      gbFacts.appendChild(factRow("estado", labels[status] || status));
      gbFacts.appendChild(factRow("grau com o alvo", el.data("seed") ? "0 · alvo" : String(rec.depth ?? el.data("depth") ?? 0)));
      (rec.ids || el.data("ids") || []).forEach((item) => {
        gbFacts.appendChild(factRow(item.kind || "dado", formatCardId(item)));
      });
      Object.keys(ATTR_LABEL).forEach((keyName) => {
        if (["fonte", "page_url", "thumb", "tipo", "snippet", "og_title", "description", "preview_kind", "embed_url"].indexOf(keyName) >= 0) return;
        if (attrs[keyName] == null || attrs[keyName] === "") return;
        gbFacts.appendChild(factRow(ATTR_LABEL[keyName], String(attrs[keyName])));
      });
      if (neighbors.length) gbFacts.appendChild(factRow("ligado a", neighbors.slice(0, 8).join(", ") + (neighbors.length > 8 ? "…" : "")));
    }
    gbActions.hidden = !full;
    gbActions.replaceChildren();
    if (full) {
      if (sourceUrl) {
        const src = document.createElement("a");
        src.className = "btn primary";
        src.href = sourceUrl;
        src.target = "_blank";
        src.rel = "noopener noreferrer";
        src.textContent = /google\.com\/maps/i.test(sourceUrl) ? "Abrir no Google Maps" : "Abrir fonte oficial";
        src.addEventListener("click", (event) => event.stopPropagation());
        gbActions.appendChild(src);
      }
      const probe = document.createElement("button");
      probe.type = "button";
      probe.className = sourceUrl ? "btn" : "btn primary";
      const isDoc = type === "PUBLICATION" || type === "PROFILE";
      probe.textContent = type === "ORG" ? "Procurar empresas e QSA" : isDoc ? "Procurar no alvo" : "Procurar informações";
      probe.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        closeBalloon();
        if (type === "ORG") {
          probeKinds(el.id(), ["CNPJ", "QSA", "PROCESSOS"], "empresa e processos");
        } else if (isDoc) {
          probeKinds(seedNodeId() || el.id(), ["INFO"], "dossiê");
        } else {
          probeKinds(el.id(), ["INFO"], "dossiê");
        }
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
    destroyPlaceMap();
    balloon.classList.remove("is-visible", "is-open");
    balloon.hidden = true;
    balloonTarget = null;
  }

  function closeBalloon() {
    balloonLocked = false;
    hideMini();
  }

  function clearSelection() {
    cy.elements().unselect();
    refreshMultiChrome();
  }

  function scheduleHide() {
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      if (balloon && balloon.matches(":hover")) return;
      hideMini();
    }, 160);
  }

  function bindAssetHost(id) {
    document.querySelectorAll("input.js-asset-from").forEach((el) => {
      el.value = id || "";
    });
  }

  cy.on("tap", "node", (evt) => {
    if (window.graphLinkPick && window.graphLinkPick(evt.target)) return;
    evt.preventDefault();
    const orig = evt.originalEvent || {};
    if (selectMode) return;
    if (orig.ctrlKey || orig.metaKey) {
      const node = evt.target;
      if (node.selected()) node.unselect();
      else node.select();
      closeBalloon();
      refreshMultiChrome();
      if (window.setActionStatus) {
        const n = cy.nodes(":selected").length;
        window.setActionStatus("ok", n ? n + " quadro(s) marcados. Botão direito para ações." : "Seleção limpa.");
      }
      return;
    }
    cy.nodes().unselect();
    evt.target.select();
    refreshMultiChrome();
    bindAssetHost(evt.target.id());
    openFull(evt.target);
  });
  cy.on("tap", "edge", (evt) => {
    if (window.graphLinkPick) return;
    evt.preventDefault();
    if (selectMode) return;
    const orig = evt.originalEvent || {};
    if (!(orig.ctrlKey || orig.metaKey)) cy.nodes().unselect();
    refreshMultiChrome();
    openFull(evt.target);
  });
  cy.on("tap", (evt) => {
    if (evt.target !== cy) return;
    const orig = evt.originalEvent || {};
    if (!(orig.ctrlKey || orig.metaKey) && !selectMode) clearSelection();
    closeBalloon();
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
  const yearMin = document.getElementById("graph-year-min");
  const yearMax = document.getElementById("graph-year-max");
  const yearFrom = document.getElementById("graph-year-from");
  const yearTo = document.getElementById("graph-year-to");
  const yearSpan = document.getElementById("graph-year-span");
  const yearTrack = document.getElementById("graph-year-track");
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
      if (isCategoryLabel(node)) {
        node.style("display", activeView() === "ordenar" ? "element" : "none");
        return;
      }
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
    if (activeView() === "ordenar") {
      cy.nodes().filter(isCategoryLabel).forEach((label) => {
        const cat = label.data("cat");
        const any = cy.nodes().filter(
          (node) => !isCategoryLabel(node) && nodeCategory(node) === cat && node.style("display") !== "none"
        ).length;
        label.style("display", any ? "element" : "none");
      });
    }
    const yearLo = yearMin ? Number(yearMin.value) : (yearInput ? Number(yearInput.min || 0) : 0);
    const yearHi = yearMax ? Number(yearMax.value) : (yearInput ? Number(yearInput.value) : 9999);
    cy.edges().forEach((edge) => {
      const year = Number(edge.data("year") || 0);
      const endsOn = edge.source().style("display") !== "none" && edge.target().style("display") !== "none";
      const yearOk = !year || (year >= yearLo && year <= yearHi);
      edge.style("display", endsOn && yearOk ? "element" : "none");
    });
    closeBalloon();
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => {
      const view = activeView();
      if (view === "mapa") return;
      if (!hasLockedLayout()) applyLayout(view);
      else if (view === "ordenar") placeCategoryLabelsFromPositions();
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
  function paintYearRange() {
    if (!yearMin || !yearMax) return;
    let lo = Number(yearMin.value);
    let hi = Number(yearMax.value);
    if (lo > hi) {
      const swap = lo;
      lo = hi;
      hi = swap;
      yearMin.value = String(lo);
      yearMax.value = String(hi);
    }
    const min = Number(yearMin.min);
    const max = Number(yearMin.max);
    const span = Math.max(1, max - min);
    if (yearFrom) yearFrom.textContent = String(lo);
    if (yearTo) yearTo.textContent = String(hi);
    if (yearSpan) yearSpan.textContent = lo === hi ? String(lo) : lo + " — " + hi;
    if (yearTrack) {
      yearTrack.style.setProperty("--year-from", ((lo - min) / span * 100) + "%");
      yearTrack.style.setProperty("--year-span", ((hi - lo) / span * 100) + "%");
    }
  }
  function bindYearInput(input) {
    if (!input) return;
    input.addEventListener("input", () => {
      paintYearRange();
      if (yearOut) yearOut.textContent = yearMax ? yearMax.value : input.value;
      applyFilters();
    });
  }
  bindYearInput(yearInput);
  bindYearInput(yearMin);
  bindYearInput(yearMax);
  paintYearRange();

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
    const sortBtn = document.getElementById("ct-sort");
    if (sortBtn) {
      sortBtn.addEventListener("click", () => {
        if (activeView() === "ordenar") applyCategoryLayout();
        else setView("ordenar");
      });
    }
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
    const fail = jobs.FAILED || 0;
    if (pill) {
      pill.textContent = jobs.pill || (queue || fail ? `fila ${queue}` + (fail ? ` · ${fail} falha` : "") : "concluído");
    }
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
      if (root.dataset.queueUrl) {
        fetch(root.dataset.queueUrl, { credentials: "same-origin" })
          .then((res) => (res.ok ? res.text() : ""))
          .then((html) => {
            const board = document.getElementById("queue-board");
            if (board && html) {
              const keepOpen = board.open || info.queue || jobs.FAILED;
              board.innerHTML = html;
              board.open = keepOpen;
            }
          })
          .catch(() => {});
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
        const pair = Array.isArray(opt);
        option.value = pair ? opt[0] : opt;
        option.textContent = pair ? opt[1] : opt;
        if ((pair ? opt[0] : opt) === value) option.selected = true;
        input.appendChild(option);
      });
    } else {
      input = document.createElement("input");
      input.type = type || "text";
      if (value) input.value = value;
    }
    input.name = name;
    if (type !== "select" && type !== "file" && value) input.value = value;
    if (extra && extra.placeholder) input.placeholder = extra.placeholder;
    if (extra && extra.required) input.required = true;
    if (extra && extra.accept) input.accept = extra.accept;
    if (extra && extra.multiple) input.multiple = true;
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
    } else if (mode === "bank") {
      gcKind.textContent = "conta";
      gcTitle.textContent = "Adicionar conta bancária";
      gcLead.textContent = "Dado manual de fonte lícita. O painel não consulta banco.";
      gcFields.appendChild(field("Banco", "bank", "text", "", { placeholder: "Itaú, 341…" }));
      gcFields.appendChild(field("Agência", "agency", "text", "", { placeholder: "0001" }));
      gcFields.appendChild(field("Conta", "account", "text", "", { placeholder: "12345-6" }));
      gcFields.appendChild(field("Tipo", "account_type", "select", "", { options: [["", "—"], ["corrente", "Corrente"], ["poupança", "Poupança"], ["pagamento", "Pagamento"], ["investimento", "Investimento"], ["outro", "Outro"]] }));
      gcFields.appendChild(field("PIX público", "pix", "text", "", { placeholder: "chave já publicada" }));
      gcFields.appendChild(field("Fonte", "source", "text", "", { placeholder: "notícia, processo, declaração…" }));
      gcFields.appendChild(field("Nota", "note", "text", "", { placeholder: "opcional" }));
    } else if (mode === "wealth") {
      gcKind.textContent = "patrimônio";
      gcTitle.textContent = "Adicionar patrimônio estimado";
      gcLead.textContent = "Estimativa sua, com fonte. Não é declaração da Receita.";
      gcFields.appendChild(field("Valor", "amount", "text", "", { required: true, placeholder: "R$ 2.400.000" }));
      gcFields.appendChild(field("Ano", "year", "text", "", { placeholder: "2024" }));
      gcFields.appendChild(field("Fonte", "source", "text", "", { placeholder: "notícia, leilão, declaração…" }));
      gcFields.appendChild(field("Nota", "note", "text", "", { placeholder: "opcional" }));
    } else if (mode === "property") {
      gcKind.textContent = "imóvel";
      gcTitle.textContent = "Adicionar imóvel";
      gcLead.textContent = "Endereço e fotos de fonte lícita. O painel não consulta cartório.";
      gcFields.appendChild(field("Endereço", "address", "text", "", { placeholder: "Rua, número, bairro" }));
      gcFields.appendChild(field("Cidade", "city", "text", "", { placeholder: "Município" }));
      gcFields.appendChild(field("UF", "uf", "text", "", { placeholder: "SP" }));
      gcFields.appendChild(field("Tipo", "property_type", "select", "", { options: [["", "—"], ["casa", "Casa"], ["apartamento", "Apartamento"], ["terreno", "Terreno"], ["sala", "Sala"], ["galpão", "Galpão"], ["sítio", "Sítio"], ["outro", "Outro"]] }));
      gcFields.appendChild(field("Valor", "amount", "text", "", { placeholder: "se souber" }));
      gcFields.appendChild(field("Fonte", "source", "text", "", { placeholder: "leilão, notícia, processo…" }));
      gcFields.appendChild(field("Fotos", "fotos", "file", "", { accept: "image/jpeg,image/png,.jpg,.jpeg,.png", multiple: true }));
      gcFields.appendChild(field("URL da foto", "photo_url", "text", "", { placeholder: "https://… miniatura pública" }));
      gcFields.appendChild(field("Nota", "note", "text", "", { placeholder: "opcional" }));
    } else if (mode === "photo") {
      gcKind.textContent = "foto";
      gcTitle.textContent = "Adicionar foto ao grafo";
      gcLead.textContent = "Arquivo ou URL pública. O mesmo recorte de foto do mapa. Sem face de leak.";
      gcFields.appendChild(field("Título", "title", "text", "", { placeholder: "legenda" }));
      gcFields.appendChild(field("Fotos", "fotos", "file", "", { accept: "image/jpeg,image/png,.jpg,.jpeg,.png", multiple: true }));
      gcFields.appendChild(field("URL da foto", "photo_url", "text", "", { placeholder: "https://…" }));
      gcFields.appendChild(field("Fonte", "source", "text", "", { placeholder: "Câmara, TSE, manual…" }));
      const profile = document.createElement("label");
      profile.className = "check";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.name = "as_profile";
      box.value = "1";
      profile.append(box, document.createTextNode(" Usar como foto de perfil"));
      gcFields.appendChild(profile);
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

  async function postMultipart(url, form, status) {
    const body = form instanceof FormData ? form : new FormData();
    if (!body.has("csrf_token")) body.set("csrf_token", csrfToken());
    const loading = (status && status.loading) || "Gravando no quadro…";
    const done = (status && status.done) || "Quadro atualizado.";
    mutating = true;
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
      try {
        await load();
      } catch (_) {
        if (window.setActionStatus) window.setActionStatus("error", "Ação feita. Recarregue se o grafo não mudou.");
      }
    } catch (_) {
      if (window.setActionStatus) window.setActionStatus("error", "Não concluiu nesta passagem. Confira endereço ou as fotos.");
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
      } else if (composerMode === "bank" || composerMode === "wealth") {
        await postBoard(root.dataset.assetUrl, {
          kind: composerMode,
          from_id: composer.dataset.entityId || seedNodeId(),
          bank: String(data.get("bank") || ""),
          agency: String(data.get("agency") || ""),
          account: String(data.get("account") || ""),
          account_type: String(data.get("account_type") || ""),
          pix: String(data.get("pix") || ""),
          amount: String(data.get("amount") || ""),
          year: String(data.get("year") || ""),
          source: String(data.get("source") || ""),
          note: String(data.get("note") || ""),
        }, {
          loading: "Gravando no dossiê…",
          done: composerMode === "bank" ? "Conta ligada ao nó." : "Patrimônio estimado gravado.",
        });
      } else if (composerMode === "photo") {
        const body = new FormData(composerForm);
        body.set("csrf_token", csrfToken());
        body.set("from_id", composer.dataset.entityId || seedNodeId());
        await postMultipart(root.dataset.photoUrl, body, {
          loading: "Colocando a foto no grafo…",
          done: "Foto no grafo.",
        });
      } else if (composerMode === "property") {
        const body = new FormData(composerForm);
        body.set("csrf_token", csrfToken());
        body.set("from_id", composer.dataset.entityId || seedNodeId());
        await postMultipart(root.dataset.propertyUrl, body, {
          loading: "Ligando imóvel…",
          done: "Imóvel ligado ao nó.",
        });
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
      PROCESSOS: "Processos",
      CNJ: "Processo",
      INFO: "Dossiê",
      POLITICOS: "Político / PEP",
    })[kind] || kind;
  }

  function canProbe(kind) {
    return !!({
      NAME: 1, EMAIL: 1, USERNAME: 1, PHONE: 1, CPF: 1, CNPJ: 1, COMPANIES: 1, QSA: 1, PROCESSOS: 1, CNJ: 1, INFO: 1, POLITICOS: 1,
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

  function selectedNodes() {
    return cy.nodes(":selected");
  }

  function refreshMultiChrome() {
    if (selectMode) {
      refreshSelectBar();
      return;
    }
    const picked = selectedNodes();
    const n = selectedRemovable().length;
    if (selectBar) selectBar.hidden = picked.length < 2;
    if (selectCount && picked.length >= 2) {
      selectCount.textContent = n
        ? n + " quadro(s) marcados" + (picked.length - n ? " · alvo incluso" : "") + ". Botão direito para ações."
        : "O alvo está marcado. Marque outros com Ctrl+clique.";
    }
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
    deleteSelectedNodes();
  }

  function deleteSelectedNodes() {
    const ids = selectedRemovable().map((node) => node.id());
    if (!ids.length) {
      if (window.setActionStatus) window.setActionStatus("error", "Nenhum nó além do alvo na seleção.");
      return;
    }
    if (!confirm("Excluir " + ids.length + " quadro(s) selecionados? O alvo permanece.")) return;
    postBoard(root.dataset.batchUrl, { entity_ids: ids }, {
      loading: "Removendo selecionados…",
      done: ids.length + " quadro(s) excluídos.",
      skipReload: true,
      removeIds: ids,
    });
    setSelectMode(false);
    clearSelection();
  }

  function validateSelectedNodes() {
    const nodes = selectedNodes().filter((node) => node.data("status") !== "confirmed");
    if (!nodes.length) {
      if (window.setActionStatus) window.setActionStatus("ok", "Nada para validar nesta seleção.");
      return;
    }
    nodes.forEach((node) => validateNode(node.id()));
  }

  function copySelectedNames() {
    const text = selectedNodes().map((node) => node.data("name") || node.data("label") || "").filter(Boolean).join("\n");
    if (text && navigator.clipboard) navigator.clipboard.writeText(text);
    if (window.setActionStatus) window.setActionStatus("ok", "Nomes copiados.");
  }

  function probeSelected(kinds, label) {
    const nodes = selectedRemovable();
    if (!nodes.length) {
      if (window.setActionStatus) window.setActionStatus("error", "Marque nós além do alvo.");
      return;
    }
    nodes.forEach((node) => probeKinds(node.id(), kinds, label));
  }

  function expandSelectedNodes() {
    const nodes = selectedRemovable();
    if (!nodes.length) {
      if (window.setActionStatus) window.setActionStatus("error", "Marque nós além do alvo.");
      return;
    }
    nodes.forEach((node) => {
      postBoard(root.dataset.entityBase + node.id() + "/expandir", {}, {
        loading: "Rodando expansão…",
        done: "Expansão na fila — o grafo atualiza sozinho.",
      });
    });
  }

  function showMultiMenu(evt) {
    const picked = selectedNodes();
    const removable = selectedRemovable();
    const head = document.createElement("div");
    head.className = "k";
    head.textContent = picked.length + " quadros";
    menu.appendChild(head);
    menu.appendChild(menuButton("Excluir selecionados", deleteSelectedNodes));
    menu.appendChild(menuButton("Validar selecionados", validateSelectedNodes));
    menu.appendChild(menuButton("Expandir selecionados", expandSelectedNodes));
    menu.appendChild(menuButton("Buscar processos nos marcados", () => probeSelected(["PROCESSOS"], "processos")));
    menu.appendChild(menuButton("Buscar empresas nos marcados", () => probeSelected(["COMPANIES"], "empresas")));
    menu.appendChild(menuButton("Buscar sócios (QSA) nos marcados", () => probeSelected(["QSA"], "sócios")));
    menu.appendChild(menuButton("Copiar nomes", copySelectedNames));
    menu.appendChild(menuButton("Limpar seleção", clearSelection));
    if (!removable.length) {
      if (window.setActionStatus) window.setActionStatus("ok", "O alvo está na seleção — ele não será excluído.");
    }
    placeMenu((evt.originalEvent || {}).clientX || 16, (evt.originalEvent || {}).clientY || 16);
  }

  function showMenu(evt, kind) {
    if (!menu) return;
    if (window.hideAppTip) window.hideAppTip();
    closeBalloon();
    menu.replaceChildren();
    const orig = evt.originalEvent || {};
    const head = document.createElement("div");
    head.className = "k";
    if (kind === "multi") {
      showMultiMenu(evt);
      return;
    }
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
        menu.appendChild(menuButton("Buscar processos", () => probeKinds(node.id(), ["PROCESSOS"], "processos")));
        menu.appendChild(menuButton("Adicionar conta bancária", () => openComposer("bank", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar patrimônio estimado", () => openComposer("wealth", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar imóvel", () => openComposer("property", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar foto ao grafo", () => openComposer("photo", { entityId: node.id() })));
      } else if (type === "CASE") {
        menu.appendChild(menuButton("Buscar comunicações deste processo", () => probeKinds(node.id(), ["PROCESSOS", "CNJ"], "processos")));
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
        menu.appendChild(menuButton("Buscar processos", () => probeKinds(node.id(), ["PROCESSOS"], "processos")));
        menu.appendChild(menuButton("Adicionar empresa (CNPJ)", () => openComposer("cnpj", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar conta bancária", () => openComposer("bank", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar patrimônio estimado", () => openComposer("wealth", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar imóvel", () => openComposer("property", { entityId: node.id() })));
        menu.appendChild(menuButton("Adicionar foto ao grafo", () => openComposer("photo", { entityId: node.id() })));
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
      menu.appendChild(menuButton("Adicionar conta bancária", () => openComposer("bank", { entityId: seedNodeId() })));
      menu.appendChild(menuButton("Adicionar patrimônio estimado", () => openComposer("wealth", { entityId: seedNodeId() })));
      menu.appendChild(menuButton("Adicionar imóvel", () => openComposer("property", { entityId: seedNodeId() })));
      menu.appendChild(menuButton("Adicionar foto ao grafo", () => openComposer("photo", { entityId: seedNodeId() })));
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
    const node = evt.target;
    if (!node.selected()) {
      cy.nodes().unselect();
      node.select();
      refreshMultiChrome();
    }
    showMenu(evt, selectedNodes().length > 1 ? "multi" : "node");
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
    showMenu(evt, selectedNodes().length > 1 ? "multi" : "bg");
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
  if (selectCancel) selectCancel.addEventListener("click", () => {
    if (selectMode) setSelectMode(false);
    else clearSelection();
  });
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
    refreshMultiChrome();
  });
  document.addEventListener("click", hideMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    hideMenu();
    closeComposer();
    stopLink();
    if (selectMode) setSelectMode(false);
    else if (selectedNodes().length) clearSelection();
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
  document.querySelectorAll('form[action*="/pesquisar-tudo"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      postBoard(form.action, {}, {
        loading: "Pesquisando o dossiê inteiro…",
        done: "Busca total na fila — o grafo atualiza sozinho.",
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
