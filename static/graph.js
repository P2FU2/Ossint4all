(function () {
  const root = document.getElementById("cy");
  if (!root || typeof cytoscape === "undefined") return;

  const colors = {
    PERSON: "#5b8def",
    ORG: "#e8b84a",
    CASE: "#c45c5c",
    PROFILE: "#7c6bff",
    ASSET: "#3db88a",
    VEHICLE: "#3db88a",
    PUBLICATION: "#9aa3b2",
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
          color: "#e8e4d9",
          "font-size": 10,
          "text-wrap": "ellipsis",
          "text-max-width": 110,
          "background-color": "#5b8def",
          "border-width": 2,
          "border-color": "#0c0e12",
          width: 28,
          height: 28,
        },
      },
      { selector: 'node[type = "ORG"]', style: { "background-color": colors.ORG } },
      { selector: 'node[type = "CASE"]', style: { "background-color": colors.CASE } },
      { selector: 'node[type = "PROFILE"]', style: { "background-color": colors.PROFILE } },
      { selector: 'node[type = "ASSET"]', style: { "background-color": colors.ASSET } },
      { selector: 'node[type = "VEHICLE"]', style: { "background-color": colors.VEHICLE } },
      { selector: 'node[type = "PUBLICATION"]', style: { "background-color": colors.PUBLICATION } },
      { selector: "node[?seed]", style: { width: 36, height: 36, "border-color": "#e8b84a", "border-width": 3 } },
      {
        selector: "edge",
        style: {
          width: 1.2,
          "line-color": "rgba(232,228,217,0.28)",
          "target-arrow-color": "rgba(232,228,217,0.28)",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          label: "data(label)",
          "font-size": 8,
          color: "#9aa3b2",
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
