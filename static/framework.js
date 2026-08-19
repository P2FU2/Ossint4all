(function () {
  const rootEl = document.getElementById("framework-tree");
  if (!rootEl || typeof d3 === "undefined") return;

  const drawer = document.getElementById("tool-drawer");
  const seedInput = document.getElementById("seed-input");
  const kindInput = document.getElementById("kind-input");
  const searchInput = document.getElementById("tool-search");

  const KIND_BRANCHES = {
    USERNAME: ["Username", "Social Networks", "Instant Messaging"],
    EMAIL: ["Email Address"],
    PHONE: ["Telephone Numbers"],
    NAME: ["People Search Engines", "Social Networks", "Username"],
    CPF: ["Brasil · oficiais", "People Search Engines"],
    CNPJ: ["Brasil · oficiais", "Business Records"],
    CNJ: ["Brasil · oficiais"],
    URL: ["Domain Name", "IP Address"],
  };

  function applySeed(url, seed, editUrl) {
    if (!url || !seed) return url;
    const token = encodeURIComponent(seed.trim());
    const raw = seed.trim();
    const placeholders = ["{seed}", "{q}", "{query}", "{username}", "{email}", "{domain}"];
    for (const p of placeholders) {
      if (url.includes(p)) return url.split(p).join(p === "{seed}" ? raw : token);
    }
    if (editUrl) return url + (url.includes("?") ? "&" : "?") + "q=" + token;
    return url;
  }

  function showTool(d) {
    if (!drawer) return;
    drawer.hidden = false;
    document.getElementById("tool-title").textContent = d.data.name;
    const flags = (d.data.flags || []).join(" · ");
    document.getElementById("tool-meta").textContent = (d.data.input || "") + (flags ? " · " + flags : "");
    document.getElementById("tool-desc").textContent = d.data.description || d.data.bestFor || "";
    const io = document.getElementById("tool-io");
    io.innerHTML = "";
    [
      ["Entrada", d.data.input],
      ["Saída", d.data.output],
      ["OPSEC", d.data.opsecNote || d.data.opsec],
    ].forEach(([k, v]) => {
      if (!v) return;
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      dd.textContent = v;
      io.appendChild(dt);
      io.appendChild(dd);
    });
    const seed = seedInput ? seedInput.value : "";
    const href = applySeed(d.data.url || "#", seed, Boolean(d.data.editUrl));
    const open = document.getElementById("tool-open");
    open.href = href;
    open.textContent = d.data.internal ? "Usar no OSINT4ALL" : "Abrir ferramenta";
    if (d.data.internal) open.removeAttribute("target");
    else open.target = "_blank";
    document.getElementById("tool-source").textContent =
      d.data.source === "osint4all" ? "OSINT4ALL" : "OSINT Framework";
  }

  fetch(rootEl.dataset.treeUrl, { credentials: "same-origin" })
    .then((r) => r.json())
    .then(draw);

  function draw(data) {
    const width = Math.max(rootEl.clientWidth || 960, 960);
    const dx = 18;
    const dy = 220;
    const tree = d3.tree().nodeSize([dx, dy]);
    const diagonal = d3
      .linkHorizontal()
      .x((d) => d.y)
      .y((d) => d.x);

    const root = d3.hierarchy(data);
    root.x0 = 0;
    root.y0 = 0;
    root.descendants().forEach((d, i) => {
      d.id = i;
      d._children = d.children;
      if (d.depth > 1) d.children = null;
    });

    const kind = (kindInput && kindInput.value) || rootEl.dataset.kind || "";
    const focus = KIND_BRANCHES[kind] || [];
    if (focus.length) {
      root.children = root._children;
      (root.children || []).forEach((child) => {
        if (focus.includes(child.data.name)) child.children = child._children;
      });
    }

    const svg = d3
      .select(rootEl)
      .append("svg")
      .attr("viewBox", [-40, -20, width, 720])
      .attr("width", "100%")
      .attr("height", 720)
      .style("font", "12px IBM Plex Sans, sans-serif");

    const gLink = svg.append("g").attr("fill", "none").attr("stroke", "rgba(232,228,217,0.22)").attr("stroke-width", 1.1);
    const gNode = svg.append("g").attr("cursor", "pointer").attr("pointer-events", "all");

    function update(source) {
      const nodes = root.descendants().reverse();
      const links = root.links();
      tree(root);
      let left = root;
      let right = root;
      root.eachBefore((node) => {
        if (node.x < left.x) left = node;
        if (node.x > right.x) right = node;
      });
      const height = right.x - left.x + 80;
      svg.attr("viewBox", [-40, left.x - 40, width, height]);

      const node = gNode.selectAll("g").data(nodes, (d) => d.id);
      const nodeEnter = node
        .enter()
        .append("g")
        .attr("transform", () => `translate(${source.y0},${source.x0})`)
        .on("click", (_, d) => {
          if (d.data.type === "url") {
            showTool(d);
            return;
          }
          d.children = d.children ? null : d._children;
          update(d);
        });

      nodeEnter
        .append("circle")
        .attr("r", 5)
        .attr("fill", (d) => color(d))
        .attr("stroke", "#0c0e12")
        .attr("stroke-width", 1.4);

      nodeEnter
        .append("text")
        .attr("dy", "0.31em")
        .attr("x", (d) => (d.data.type === "url" ? 10 : -10))
        .attr("text-anchor", (d) => (d.data.type === "url" ? "start" : "end"))
        .text((d) => d.data.name)
        .attr("fill", "#e8e4d9")
        .clone(true)
        .lower()
        .attr("stroke", "#0c0e12")
        .attr("stroke-width", 3);

      node
        .merge(nodeEnter)
        .transition()
        .duration(250)
        .attr("transform", (d) => `translate(${d.y},${d.x})`);

      node.exit().remove();

      const link = gLink.selectAll("path").data(links, (d) => d.target.id);
      link
        .enter()
        .append("path")
        .attr("d", () => {
          const o = { x: source.x0, y: source.y0 };
          return diagonal({ source: o, target: o });
        })
        .merge(link)
        .transition()
        .duration(250)
        .attr("d", diagonal);
      link.exit().remove();

      root.eachBefore((d) => {
        d.x0 = d.x;
        d.y0 = d.y;
      });
    }

    function color(d) {
      if (d.data.source === "osint4all" || (d.data.name || "").includes("Brasil")) return "#e8b84a";
      if (d.data.type === "url") return "#5b8def";
      return d.children || d._children ? "#9aa3b2" : "#5b8def";
    }

    update(root);

    if (searchInput) {
      searchInput.addEventListener("input", () => {
        const q = searchInput.value.trim().toLowerCase();
        svg.selectAll("text").attr("fill", (d) => {
          if (!q) return "#e8e4d9";
          return (d.data.name || "").toLowerCase().includes(q) ? "#e8b84a" : "#5a6170";
        });
      });
    }
  }
})();
