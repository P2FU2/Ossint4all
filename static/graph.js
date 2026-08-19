(function () {
  const root = document.getElementById("cy");
  if (!root || typeof cytoscape === "undefined") return;

  const colors = {
    PERSON: "#5b8def",
    ORG: "#e8b84a",
    CASE: "#c45c5c",
    PROFILE: "#7c6bff",
    ASSET: "#3db88a",
    PUBLICATION: "#9aa3b2",
  };

  function toElements(payload) {
    const nodes = (payload.nodes || []).map((n) => ({
      data: { id: n.id, label: n.label, type: n.type, seed: n.seed },
    }));
    const edges = (payload.edges || []).map((e) => ({
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

  async function load() {
    const res = await fetch(root.dataset.graphUrl, { credentials: "same-origin" });
    const payload = await res.json();
    cy.elements().remove();
    cy.add(toElements(payload));
    cy.layout({ name: "cose", animate: false, nodeRepulsion: 12000 }).run();
  }

  cy.on("tap", "node", (evt) => {
    const id = evt.target.id();
    window.location.href = root.dataset.entityBase + id;
  });

  const filter = document.getElementById("type-filter");
  if (filter) {
    filter.addEventListener("change", () => {
      const value = filter.value;
      cy.nodes().forEach((node) => {
        const show = !value || node.data("type") === value;
        node.style("display", show ? "element" : "none");
      });
    });
  }

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
