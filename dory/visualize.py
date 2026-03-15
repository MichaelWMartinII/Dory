"""
Dory graph visualization — generates a self-contained interactive HTML file
using a D3.js force-directed layout.
"""

from __future__ import annotations

import json
import os
import tempfile
import webbrowser
from pathlib import Path

from .graph import Graph
from .schema import ZONE_ACTIVE, ZONE_ARCHIVED, ZONE_EXPIRED

_NODE_COLORS = {
    "ENTITY":     "#4fc3f7",
    "CONCEPT":    "#b39ddb",
    "EVENT":      "#81c784",
    "PREFERENCE": "#ffb74d",
    "BELIEF":     "#ef9a9a",
    "SESSION":    "#90a4ae",
}

_ZONE_OPACITY = {
    ZONE_ACTIVE:   1.0,
    ZONE_ARCHIVED: 0.4,
    ZONE_EXPIRED:  0.15,
}


def _build_graph_data(graph: Graph, zones: list[str]) -> dict:
    node_ids: set[str] = set()
    nodes = []
    for n in graph.all_nodes(zone=None):
        if n.zone not in zones:
            continue
        node_ids.add(n.id)
        label = n.content if len(n.content) <= 60 else n.content[:57] + "…"
        nodes.append({
            "id":               n.id,
            "label":            label,
            "full":             n.content,
            "type":             n.type.value,
            "salience":         round(n.salience, 3),
            "is_core":          n.is_core,
            "zone":             n.zone,
            "tags":             n.tags,
            "activation_count": n.activation_count,
            "created_at":       n.created_at[:10],
            "color":            _NODE_COLORS.get(n.type.value, "#888"),
            "opacity":          _ZONE_OPACITY.get(n.zone, 1.0),
        })

    links = []
    for e in graph.all_edges():
        if e.source_id in node_ids and e.target_id in node_ids:
            links.append({
                "source": e.source_id,
                "target": e.target_id,
                "type":   e.type.value,
                "weight": round(e.weight, 3),
            })

    return {"nodes": nodes, "links": links}


def render_html(graph: Graph, zones: list[str] | None = None) -> str:
    if zones is None:
        zones = [ZONE_ACTIVE]
    data  = _build_graph_data(graph, zones)
    stats = graph.stats()
    html  = _HTML_TEMPLATE
    html  = html.replace("__GRAPH_DATA__",  json.dumps(data))
    html  = html.replace("__GRAPH_STATS__", json.dumps(stats))
    return html


def open_visualization(
    graph: Graph,
    output_path: Path | None = None,
    zones: list[str] | None = None,
    open_browser: bool = True,
) -> Path:
    """Generate the HTML visualization and optionally open it in a browser."""
    html = render_html(graph, zones)
    if output_path is None:
        fd, tmp = tempfile.mkstemp(suffix=".html", prefix="dory_graph_")
        os.close(fd)
        output_path = Path(tmp)
    output_path.write_text(html, encoding="utf-8")
    if open_browser:
        webbrowser.open(output_path.as_uri())
    return output_path


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dory Memory Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: #0d1117;
    color: #c9d1d9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace;
    display: flex;
    height: 100vh;
    overflow: hidden;
  }

  #sidebar {
    width: 280px;
    min-width: 280px;
    background: #161b22;
    border-right: 1px solid #30363d;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  #sidebar-header {
    padding: 16px;
    border-bottom: 1px solid #30363d;
  }

  #sidebar-header h1 {
    font-size: 18px;
    font-weight: 600;
    color: #f0f6fc;
    letter-spacing: 0.5px;
  }

  #sidebar-header p {
    font-size: 12px;
    color: #8b949e;
    margin-top: 4px;
  }

  #stats {
    padding: 12px 16px;
    border-bottom: 1px solid #30363d;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .stat { text-align: center; }
  .stat-val { font-size: 20px; font-weight: 700; color: #58a6ff; }
  .stat-lbl { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }

  #legend {
    padding: 12px 16px;
    border-bottom: 1px solid #30363d;
  }

  #legend h3 { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 5px;
    font-size: 12px;
    cursor: pointer;
    padding: 2px 4px;
    border-radius: 4px;
    transition: background 0.15s;
  }
  .legend-item:hover { background: #21262d; }
  .legend-item.dimmed { opacity: 0.4; }

  .legend-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  #zone-controls {
    padding: 12px 16px;
    border-bottom: 1px solid #30363d;
  }
  #zone-controls h3 { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
  .zone-btn {
    background: #21262d;
    border: 1px solid #30363d;
    color: #8b949e;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
    margin-right: 4px;
    transition: all 0.15s;
  }
  .zone-btn.active { background: #0d419d; border-color: #58a6ff; color: #58a6ff; }

  #detail-panel {
    flex: 1;
    padding: 16px;
    overflow-y: auto;
  }

  #detail-panel h3 {
    font-size: 11px;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
  }

  #detail-content {
    font-size: 12px;
    line-height: 1.6;
    color: #8b949e;
  }

  .detail-node-content {
    color: #c9d1d9;
    font-size: 13px;
    margin-bottom: 12px;
    line-height: 1.5;
  }

  .detail-row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 4px;
  }

  .detail-key { color: #8b949e; }
  .detail-val { color: #58a6ff; font-family: monospace; }

  .core-badge {
    display: inline-block;
    background: #2d2000;
    border: 1px solid #bb8009;
    color: #d29922;
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 10px;
    margin-bottom: 8px;
  }

  .connected-node {
    background: #21262d;
    border-radius: 4px;
    padding: 5px 8px;
    margin-bottom: 4px;
    font-size: 11px;
    cursor: pointer;
  }
  .connected-node:hover { background: #30363d; }
  .connected-node .edge-type { color: #58a6ff; font-size: 10px; }
  .connected-node .node-label { color: #c9d1d9; }

  #graph-area {
    flex: 1;
    position: relative;
    overflow: hidden;
  }

  svg {
    width: 100%;
    height: 100%;
  }

  .link {
    stroke: #4a7fa5;
    stroke-opacity: 0.5;
  }

  .node circle {
    cursor: pointer;
    transition: filter 0.15s;
  }

  .node circle:hover { filter: brightness(1.3); }
  .node.selected circle { filter: brightness(1.4); }

  .node-label {
    font-size: 10px;
    fill: #8b949e;
    pointer-events: none;
    text-anchor: middle;
  }

  .core-ring {
    fill: none;
    stroke: #d29922;
    stroke-width: 2px;
    pointer-events: none;
  }

  .edge-label {
    font-size: 9px;
    fill: #484f58;
    pointer-events: none;
    text-anchor: middle;
  }

  #tooltip {
    position: absolute;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    max-width: 240px;
    z-index: 100;
  }

  #tooltip .tt-type { color: #58a6ff; font-size: 10px; text-transform: uppercase; }
  #tooltip .tt-content { color: #f0f6fc; margin-top: 2px; line-height: 1.4; }

  #search-bar {
    position: absolute;
    top: 12px;
    right: 12px;
    z-index: 10;
  }

  #search-input {
    background: #161b22;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 12px;
    width: 200px;
    outline: none;
  }
  #search-input:focus { border-color: #58a6ff; }
  #search-input::placeholder { color: #484f58; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <h1>Dory Memory</h1>
    <p>Knowledge graph visualization</p>
  </div>

  <div id="stats">
    <div class="stat"><div class="stat-val" id="s-nodes">0</div><div class="stat-lbl">Nodes</div></div>
    <div class="stat"><div class="stat-val" id="s-edges">0</div><div class="stat-lbl">Edges</div></div>
    <div class="stat"><div class="stat-val" id="s-core">0</div><div class="stat-lbl">Core</div></div>
    <div class="stat"><div class="stat-val" id="s-archived">0</div><div class="stat-lbl">Archived</div></div>
  </div>

  <div id="legend">
    <h3>Node Types</h3>
    <div class="legend-item" data-type="ENTITY">    <div class="legend-dot" style="background:#4fc3f7"></div> Entity</div>
    <div class="legend-item" data-type="CONCEPT">   <div class="legend-dot" style="background:#b39ddb"></div> Concept</div>
    <div class="legend-item" data-type="EVENT">     <div class="legend-dot" style="background:#81c784"></div> Event</div>
    <div class="legend-item" data-type="PREFERENCE"><div class="legend-dot" style="background:#ffb74d"></div> Preference</div>
    <div class="legend-item" data-type="BELIEF">    <div class="legend-dot" style="background:#ef9a9a"></div> Belief</div>
    <div class="legend-item" data-type="SESSION">   <div class="legend-dot" style="background:#90a4ae"></div> Session</div>
  </div>

  <div id="zone-controls">
    <h3>Zones</h3>
    <button class="zone-btn active" data-zone="active">Active</button>
    <button class="zone-btn" data-zone="archived">Archived</button>
    <button class="zone-btn" data-zone="expired">Expired</button>
  </div>

  <div id="detail-panel">
    <h3>Node Detail</h3>
    <div id="detail-content">
      <span style="color:#484f58">Click a node to inspect it.</span>
    </div>
  </div>
</div>

<div id="graph-area">
  <div id="search-bar">
    <input id="search-input" type="text" placeholder="Search nodes…">
  </div>
  <div id="tooltip">
    <div class="tt-type" id="tt-type"></div>
    <div class="tt-content" id="tt-content"></div>
  </div>
  <svg id="graph-svg"></svg>
</div>

<script>
const RAW_DATA  = __GRAPH_DATA__;
const RAW_STATS = __GRAPH_STATS__;

// Populate stats
document.getElementById("s-nodes").textContent    = RAW_STATS.nodes    ?? 0;
document.getElementById("s-edges").textContent    = RAW_STATS.edges    ?? 0;
document.getElementById("s-core").textContent     = RAW_STATS.core_nodes ?? 0;
document.getElementById("s-archived").textContent = RAW_STATS.archived ?? 0;

// ---- State ----
let activeZones   = new Set(["active"]);
let hiddenTypes   = new Set();
let selectedNode  = null;

// ---- SVG setup ----
const svg    = d3.select("#graph-svg");
const width  = () => document.getElementById("graph-area").clientWidth;
const height = () => document.getElementById("graph-area").clientHeight;

const container = svg.append("g");

svg.call(
  d3.zoom()
    .scaleExtent([0.1, 4])
    .on("zoom", (event) => container.attr("transform", event.transform))
);

// Arrow marker
svg.append("defs").append("marker")
  .attr("id", "arrowhead")
  .attr("viewBox", "0 -4 8 8")
  .attr("refX", 18).attr("refY", 0)
  .attr("markerWidth", 6).attr("markerHeight", 6)
  .attr("orient", "auto")
  .append("path")
    .attr("d", "M0,-4L8,0L0,4")
    .attr("fill", "#30363d");

// ---- Simulation ----
let simulation = null;
let linkSel, nodeSel, labelSel, coreRingSel, edgeLabelSel;

function nodeRadius(d) {
  const base = 8 + d.salience * 16;
  return Math.max(8, Math.min(24, base));
}

function visibleData() {
  const nodes = RAW_DATA.nodes.filter(n =>
    activeZones.has(n.zone) && !hiddenTypes.has(n.type)
  );
  const nodeIds = new Set(nodes.map(n => n.id));
  const links = RAW_DATA.links.filter(l =>
    nodeIds.has(l.source.id ?? l.source) &&
    nodeIds.has(l.target.id ?? l.target)
  );
  return { nodes, links };
}

function buildGraph() {
  container.selectAll("*").remove();

  const { nodes, links } = visibleData();

  // Deep-copy so D3 can mutate positions
  const nodesCopy = nodes.map(d => ({ ...d }));
  const nodeMap   = new Map(nodesCopy.map(d => [d.id, d]));
  const linksCopy = links.map(l => ({
    ...l,
    source: nodeMap.get(l.source.id ?? l.source) ?? l.source,
    target: nodeMap.get(l.target.id ?? l.target) ?? l.target,
  }));

  if (simulation) simulation.stop();
  simulation = d3.forceSimulation(nodesCopy)
    .force("link",    d3.forceLink(linksCopy).id(d => d.id).distance(d => 55 + (1 - d.weight) * 40).strength(0.8))
    .force("charge",  d3.forceManyBody().strength(d => -150 - d.salience * 180))
    .force("x",       d3.forceX(width() / 2).strength(0.06))
    .force("y",       d3.forceY(height() / 2).strength(0.06))
    .force("collide", d3.forceCollide(d => nodeRadius(d) + 5))
    .alphaDecay(0.012)
    .velocityDecay(0.35);

  // Links
  linkSel = container.append("g").selectAll("line")
    .data(linksCopy).join("line")
    .attr("class", "link")
    .attr("stroke-width", d => Math.max(1, d.weight * 3))
    .attr("marker-end", "url(#arrowhead)");

  // Edge labels (hidden by default, shown on hover)
  edgeLabelSel = container.append("g").selectAll("text")
    .data(linksCopy).join("text")
    .attr("class", "edge-label")
    .text(d => d.type)
    .style("display", "none");

  // Nodes
  const nodeGroup = container.append("g").selectAll("g")
    .data(nodesCopy).join("g")
    .attr("class", "node")
    .call(
      d3.drag()
        .on("start", (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end",   (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  nodeGroup.append("circle")
    .attr("r",      d => nodeRadius(d))
    .attr("fill",   d => d.color)
    .attr("fill-opacity", d => d.opacity)
    .attr("stroke", d => d.zone === "archived" ? "#484f58" : "none")
    .attr("stroke-dasharray", d => d.zone === "archived" ? "4,2" : null)
    .attr("stroke-width", 1.5);

  // Core ring
  coreRingSel = nodeGroup.filter(d => d.is_core)
    .append("circle")
    .attr("class", "core-ring")
    .attr("r", d => nodeRadius(d) + 4);

  // Labels (always shown for core, hidden otherwise)
  labelSel = nodeGroup.append("text")
    .attr("class", "node-label")
    .attr("dy", d => nodeRadius(d) + 12)
    .text(d => d.label.length > 28 ? d.label.slice(0, 26) + "…" : d.label)
    .style("display", null);

  // Tooltip on hover
  const tooltip = document.getElementById("tooltip");
  nodeGroup
    .on("mouseover", (event, d) => {
      document.getElementById("tt-type").textContent    = d.type + (d.is_core ? " ★ CORE" : "");
      document.getElementById("tt-content").textContent = d.label;
      tooltip.style.opacity = "1";
    })
    .on("mousemove", (event) => {
      tooltip.style.left = (event.offsetX + 12) + "px";
      tooltip.style.top  = (event.offsetY - 8)  + "px";
    })
    .on("mouseout",  () => { tooltip.style.opacity = "0"; })
    .on("click", (event, d) => {
      event.stopPropagation();
      selectNode(d, nodeGroup, linksCopy, nodeMap);
    });

  // Show edge labels on link hover
  linkSel
    .on("mouseover", function(event, d) {
      d3.select(this).attr("stroke", "#58a6ff").attr("stroke-opacity", 1).attr("stroke-width", d => Math.max(2, d.weight * 4));
      const idx = linksCopy.indexOf(d);
      edgeLabelSel.filter((_, i) => i === idx).style("display", null);
    })
    .on("mouseout",  function(event, d) {
      d3.select(this).attr("stroke", "#4a7fa5").attr("stroke-opacity", 0.5).attr("stroke-width", d => Math.max(1, d.weight * 3));
      edgeLabelSel.style("display", "none");
    });

  svg.on("click", () => clearSelection(nodeGroup));

  simulation.on("tick", () => {
    linkSel
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);

    edgeLabelSel
      .attr("x", d => (d.source.x + d.target.x) / 2)
      .attr("y", d => (d.source.y + d.target.y) / 2);

    nodeGroup.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  simulation.on("end", () => fitToView(nodesCopy));
}

function fitToView(nodes) {
  if (!nodes || !nodes.length) return;
  const pad = 80;
  const xs = nodes.map(d => d.x).filter(v => v != null);
  const ys = nodes.map(d => d.y).filter(v => v != null);
  if (!xs.length) return;
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const w = width(), h = height();
  const scale = Math.min(0.95, Math.min(w / (x1 - x0 + pad * 2), h / (y1 - y0 + pad * 2)));
  const tx = w / 2 - scale * (x0 + x1) / 2;
  const ty = h / 2 - scale * (y0 + y1) / 2;
  svg.transition().duration(700).call(
    d3.zoom().transform,
    d3.zoomIdentity.translate(tx, ty).scale(scale)
  );
}

function selectNode(d, nodeGroup, linksCopy, nodeMap) {
  selectedNode = d.id;
  nodeGroup.classed("selected", n => n.id === d.id);

  // Highlight connected nodes
  const connectedIds = new Set([d.id]);
  const connectedLinks = linksCopy.filter(l => {
    const s = l.source.id ?? l.source;
    const t = l.target.id ?? l.target;
    if (s === d.id || t === d.id) { connectedIds.add(s); connectedIds.add(t); return true; }
    return false;
  });

  nodeGroup.selectAll("circle").attr("fill-opacity", n =>
    connectedIds.has(n.id) ? n.opacity : n.opacity * 0.25
  );
  linkSel.attr("stroke-opacity", l => {
    const s = l.source.id ?? l.source;
    const t = l.target.id ?? l.target;
    return (s === d.id || t === d.id) ? 0.9 : 0.1;
  });

  // Detail panel
  const panel  = document.getElementById("detail-content");
  const coreBadge = d.is_core ? '<div class="core-badge">★ CORE MEMORY</div>' : "";
  const tagStr = d.tags.length ? d.tags.join(", ") : "—";

  const connections = connectedLinks.map(l => {
    const otherId = (l.source.id ?? l.source) === d.id ? (l.target.id ?? l.target) : (l.source.id ?? l.source);
    const other   = nodeMap.get(otherId);
    const dir     = (l.source.id ?? l.source) === d.id ? "→" : "←";
    if (!other) return "";
    return `<div class="connected-node" onclick="highlightById('${other.id}')">
      <span class="edge-type">${dir} ${l.type}</span><br>
      <span class="node-label">${other.label}</span>
    </div>`;
  }).join("");

  panel.innerHTML = `
    ${coreBadge}
    <div class="detail-node-content">${d.full}</div>
    <div class="detail-row"><span class="detail-key">Type</span>       <span class="detail-val">${d.type}</span></div>
    <div class="detail-row"><span class="detail-key">Zone</span>       <span class="detail-val">${d.zone}</span></div>
    <div class="detail-row"><span class="detail-key">Salience</span>   <span class="detail-val">${d.salience}</span></div>
    <div class="detail-row"><span class="detail-key">Activations</span><span class="detail-val">${d.activation_count}</span></div>
    <div class="detail-row"><span class="detail-key">Created</span>    <span class="detail-val">${d.created_at}</span></div>
    <div class="detail-row"><span class="detail-key">Tags</span>       <span class="detail-val">${tagStr}</span></div>
    ${connections ? `<div style="margin-top:12px;font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Connections (${connectedLinks.length})</div>${connections}` : ""}
  `;
}

function clearSelection(nodeGroup) {
  selectedNode = null;
  nodeGroup.classed("selected", false);
  nodeGroup.selectAll("circle").attr("fill-opacity", d => d.opacity);
  if (linkSel) linkSel.attr("stroke-opacity", 0.6);
  document.getElementById("detail-content").innerHTML = '<span style="color:#484f58">Click a node to inspect it.</span>';
}

// ---- Zone toggle ----
document.querySelectorAll(".zone-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const zone = btn.dataset.zone;
    if (activeZones.has(zone)) { activeZones.delete(zone); btn.classList.remove("active"); }
    else                       { activeZones.add(zone);    btn.classList.add("active"); }
    buildGraph();
  });
});

// ---- Type legend toggle ----
document.querySelectorAll(".legend-item").forEach(item => {
  item.addEventListener("click", () => {
    const type = item.dataset.type;
    if (hiddenTypes.has(type)) { hiddenTypes.delete(type); item.classList.remove("dimmed"); }
    else                       { hiddenTypes.add(type);    item.classList.add("dimmed"); }
    buildGraph();
  });
});

// ---- Search ----
document.getElementById("search-input").addEventListener("input", function() {
  const q = this.value.toLowerCase().trim();
  if (!q) {
    container.selectAll(".node circle").attr("fill-opacity", d => d.opacity);
    container.selectAll(".node-label").style("display", d => d.is_core ? null : "none");
    return;
  }
  container.selectAll(".node").each(function(d) {
    const match = d.full.toLowerCase().includes(q) || d.tags.some(t => t.toLowerCase().includes(q));
    d3.select(this).select("circle").attr("fill-opacity", match ? d.opacity : d.opacity * 0.08);
    d3.select(this).select(".node-label").style("opacity", match ? 1 : 0.1);
  });
});

// ---- Init ----
buildGraph();
window.addEventListener("resize", buildGraph);

// Allow clicking connected nodes from detail panel
window.highlightById = function(id) {
  const nodeGroup = container.selectAll(".node");
  const nodesCopy = nodeGroup.data();
  const nodeMap   = new Map(nodesCopy.map(d => [d.id, d]));
  const d         = nodeMap.get(id);
  if (!d) return;
  const linksCopy = linkSel ? linkSel.data() : [];
  selectNode(d, nodeGroup, linksCopy, nodeMap);
};
</script>
</body>
</html>
"""
