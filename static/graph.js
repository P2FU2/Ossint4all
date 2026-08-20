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
      data: { id: n.id, label: n.label, type: n.type, seed: n.seed, attrs: n.attrs || {} },
    }));
    const edges = (data.edges || []).map((e) => ({
      data: { id: e.id, source: e.source, target: e.target, label: e.type },
    }));
    return nodes.concat(edges);
  }

  const cy = cytoscape({
    container: root,
    elements: [],
    layout: { name: "cose", animate: false, nodeRepulsion: 12000 },
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          color: "#d7e4dc",
          "font-size": 10,
          "font-family": "IBM Plex Mono, monospace",
          "text-wrap": "ellipsis",
          "text-max-width": 120,
          "text-valign": "center",
          "text-halign": "center",
          shape: "round-rectangle",
          "background-color": "#121a16",
          "border-width": 1.4,
          "border-color": "#5e7a62",
          width: 132,
          height: 36,
        },
      },
      { selector: 'node[type = "ORG"]', style: { "border-color": colors.ORG } },
      { selector: 'node[type = "CASE"]', style: { "border-color": colors.CASE } },
      { selector: 'node[type = "PROFILE"]', style: { "border-color": colors.PROFILE } },
      { selector: 'node[type = "ASSET"]', style: { "border-color": colors.ASSET } },
      { selector: 'node[type = "VEHICLE"]', style: { "border-color": colors.VEHICLE } },
      { selector: 'node[type = "PUBLICATION"]', style: { "border-color": colors.PUBLICATION } },
      { selector: 'node[type = "PERSON"]', style: { "border-color": colors.PERSON } },
      { selector: "node[?seed]", style: { width: 148, height: 40, "border-color": "#6f9b82", "border-width": 2, "background-color": "#15241c" } },
      {
        selector: "edge",
        style: {
          width: 1.1,
          "line-color": "#3d5348",
          "target-arrow-color": "#3d5348",
          "target-arrow-shape": "triangle",
          "curve-style": "taxi",
          "taxi-direction": "downward",
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

  function applyLayout(view) {
    if (view === "arvore") {
      cy.layout({ name: "breadthfirst", directed: true, spacingFactor: 1.15, animate: false }).run();
      return;
    }
    cy.layout({ name: "cose", animate: false, nodeRepulsion: 12000 }).run();
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
          return `<tr data-id="${n.id}"><td>${n.label}</td><td>${a.situacao || "—"}</td><td>${loc || "—"}</td></tr>`;
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

  function renderMap() {
    const el = document.getElementById("org-map");
    if (!el || typeof L === "undefined") return;
    const orgs = (payload.nodes || []).filter((n) => n.type === "ORG");
    if (map) {
      map.remove();
      map = null;
    }
    map = L.map(el).setView([-14.2, -51.9], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);
    const bounds = [];
    orgs.forEach((node) => {
      const latlng = markerLatLng(node);
      if (!latlng) return;
      bounds.push(latlng);
      const a = node.attrs || {};
      const marker = L.marker(latlng).addTo(map);
      marker.bindPopup(
        `<strong>${node.label}</strong><br>${a.situacao || ""}<br>${[a.municipio, a.uf].filter(Boolean).join(" / ")}`
      );
      marker.on("click", () => {
        window.location.href = root.dataset.entityBase + node.id;
      });
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 11 });
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
    const active = document.querySelector(".view-tab.is-active");
    setView((active && active.dataset.view) || "rede");
  }

  cy.on("tap", "node", (evt) => {
    window.location.href = root.dataset.entityBase + evt.target.id();
  });

  cy.on("mouseover", "node", (evt) => {
    const node = evt.target;
    const orig = evt.originalEvent || {};
    if (window.showAppTip) {
      window.showAppTip(`${node.data("type")} · ${node.data("label")} — clique para a ficha`, orig.clientX || 0, orig.clientY || 0);
    }
  });
  cy.on("mousemove", (evt) => {
    const orig = evt.originalEvent || {};
    if (!window.showAppTip || !orig.clientX) return;
    const tip = document.getElementById("tooltip");
    if (tip && !tip.hidden) window.showAppTip(tip.textContent, orig.clientX, orig.clientY);
  });
  cy.on("mouseout", "node", () => {
    if (window.hideAppTip) window.hideAppTip();
  });
  cy.on("mouseover", "edge", (evt) => {
    const orig = evt.originalEvent || {};
    if (window.showAppTip) window.showAppTip(evt.target.data("label") || "vínculo", orig.clientX || 0, orig.clientY || 0);
  });
  cy.on("mouseout", "edge", () => {
    if (window.hideAppTip) window.hideAppTip();
  });

  const filter = document.getElementById("type-filter");
  const search = document.getElementById("graph-search");
  function applyFilters() {
    const type = filter ? filter.value : "";
    const q = search ? search.value.trim().toLowerCase() : "";
    cy.nodes().forEach((node) => {
      const typeOk = !type || node.data("type") === type;
      const text = String(node.data("label") || "").toLowerCase();
      const searchOk = !q || text.includes(q);
      node.style("display", typeOk && searchOk ? "element" : "none");
    });
  }
  if (filter) filter.addEventListener("change", applyFilters);
  if (search) search.addEventListener("input", applyFilters);

  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });

  async function poll() {
    try {
      const res = await fetch(root.dataset.statusUrl, { credentials: "same-origin" });
      const jobs = await res.json();
      const pill = document.getElementById("job-pill");
      if (pill) pill.textContent = "fila " + ((jobs.PENDING || 0) + (jobs.RUNNING || 0));
    } catch (_) {
      /* ignore */
    }
  }

  load();
  setInterval(poll, 4000);
})();
