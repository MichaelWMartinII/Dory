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
    "ENTITY":          "#4fc3f7",
    "CONCEPT":         "#b39ddb",
    "EVENT":           "#81c784",
    "PREFERENCE":      "#ffb74d",
    "BELIEF":          "#ef9a9a",
    "SESSION":         "#90a4ae",
    "SESSION_SUMMARY": "#4dd0e1",
    "PROCEDURE":       "#ce93d8",
}

_EDGE_COLORS = {
    "TEMPORALLY_AFTER":  "#d29922",
    "TEMPORALLY_BEFORE": "#d29922",
    "SUPERSEDES":        "#f85149",
    "SUPPORTS_FACT":     "#4dd0e1",
    "MENTIONS":          "#4dd0e1",
    "PREFERS":           "#ffb74d",
    "WORKS_ON":          "#58a6ff",
    "USES":              "#58a6ff",
    "CO_OCCURS":         "#4a7fa5",
}

_ZONE_OPACITY = {
    ZONE_ACTIVE:   1.0,
    ZONE_ARCHIVED: 0.35,
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
            "superseded_at":    n.superseded_at,
        })

    links = []
    for e in graph.all_edges():
        if e.source_id in node_ids and e.target_id in node_ids:
            links.append({
                "source": e.source_id,
                "target": e.target_id,
                "type":   e.type.value,
                "weight": round(e.weight, 3),
                "color":  _EDGE_COLORS.get(e.type.value, "#4a7fa5"),
            })

    return {"nodes": nodes, "links": links}


def render_html(
    graph: Graph,
    zones: list[str] | None = None,
    demo_queries: list | None = None,
) -> str:
    if zones is None:
        zones = [ZONE_ACTIVE]
    data  = _build_graph_data(graph, zones)
    stats = graph.stats()
    html  = _HTML_TEMPLATE
    html  = html.replace("__GRAPH_DATA__",    json.dumps(data))
    html  = html.replace("__GRAPH_STATS__",   json.dumps(stats))
    html  = html.replace("__DEMO_QUERIES__",  json.dumps(demo_queries or []))
    return html


def open_visualization(
    graph: Graph,
    output_path: Path | None = None,
    zones: list[str] | None = None,
    open_browser: bool = True,
    demo_queries: list | None = None,
) -> Path:
    """Generate the HTML visualization and optionally open it in a browser."""
    html = render_html(graph, zones, demo_queries)
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
    width: 300px;
    min-width: 300px;
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

  /* ----- Query panel ----- */
  #query-panel {
    padding: 12px 16px;
    border-bottom: 1px solid #30363d;
  }

  #query-panel h3 {
    font-size: 11px;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }

  #query-input {
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
    width: 100%;
    outline: none;
    margin-bottom: 6px;
  }
  #query-input:focus { border-color: #58a6ff; }
  #query-input::placeholder { color: #484f58; }

  #query-examples {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 8px;
  }

  .query-chip {
    background: #21262d;
    border: 1px solid #30363d;
    color: #8b949e;
    padding: 3px 8px;
    border-radius: 10px;
    font-size: 10px;
    cursor: pointer;
    transition: all 0.15s;
    line-height: 1.4;
  }
  .query-chip:hover { border-color: #58a6ff; color: #58a6ff; background: #0d1f3c; }
  .query-chip.active { border-color: #58a6ff; color: #58a6ff; background: #0d1f3c; }

  #route-badge {
    display: none;
    margin-bottom: 6px;
  }

  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }
  .badge-graph    { background: #0d1f3c; color: #58a6ff; border: 1px solid #58a6ff; }
  .badge-episodic { background: #0f2b0f; color: #56d364; border: 1px solid #56d364; }
  .badge-hybrid   { background: #2d1a00; color: #f0883e; border: 1px solid #f0883e; }

  #activation-list {
    display: none;
  }

  .activated-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
    background: #21262d;
    border-radius: 4px;
    padding: 5px 8px;
    margin-bottom: 3px;
    font-size: 11px;
    cursor: pointer;
  }
  .activated-item:hover { background: #30363d; }
  .activated-item-header { display: flex; justify-content: space-between; align-items: center; }
  .activated-item-type { color: #58a6ff; font-size: 10px; }
  .activated-item-label { color: #c9d1d9; line-height: 1.3; }
  .activation-bar-wrap { background: #0d1117; border-radius: 2px; height: 3px; margin-top: 2px; }
  .activation-bar { height: 3px; background: #58a6ff; border-radius: 2px; transition: width 0.3s; }

  #clear-query {
    display: none;
    background: none;
    border: none;
    color: #8b949e;
    font-size: 11px;
    cursor: pointer;
    padding: 2px 0;
    text-decoration: underline;
  }
  #clear-query:hover { color: #c9d1d9; }

  /* ----- Legend ----- */
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

  /* ----- Edge legend ----- */
  #edge-legend {
    padding: 10px 16px;
    border-bottom: 1px solid #30363d;
  }
  #edge-legend h3 { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
  .edge-legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
    font-size: 11px;
    color: #8b949e;
  }
  .edge-swatch {
    width: 24px;
    height: 2px;
    border-radius: 1px;
    flex-shrink: 0;
  }
  .edge-swatch.dashed {
    background: repeating-linear-gradient(90deg, #f85149 0px, #f85149 5px, transparent 5px, transparent 9px);
    height: 2px;
  }

  /* ----- Zone controls ----- */
  #zone-controls {
    padding: 10px 16px;
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

  /* ----- Detail panel ----- */
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

  .archived-badge {
    display: inline-block;
    background: #2d1010;
    border: 1px solid #f85149;
    color: #f85149;
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 10px;
    margin-bottom: 8px;
    margin-left: 4px;
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
  .connected-node .edge-type { font-size: 10px; }
  .connected-node .node-label { color: #c9d1d9; }

  /* ----- Graph area ----- */
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
    stroke-opacity: 0.55;
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

  <!-- Query mode -->
  <div id="query-panel">
    <h3>Query Memory</h3>
    <input id="query-input" type="text" placeholder="Ask a question…">
    <div id="query-examples"></div>
    <div id="route-badge"></div>
    <button id="clear-query" onclick="clearQuery()">✕ clear query</button>
    <div id="activation-list"></div>
  </div>

  <div id="legend">
    <h3>Node Types</h3>
    <div class="legend-item" data-type="ENTITY">          <div class="legend-dot" style="background:#4fc3f7"></div> Entity</div>
    <div class="legend-item" data-type="CONCEPT">         <div class="legend-dot" style="background:#b39ddb"></div> Concept</div>
    <div class="legend-item" data-type="EVENT">           <div class="legend-dot" style="background:#81c784"></div> Event</div>
    <div class="legend-item" data-type="PREFERENCE">      <div class="legend-dot" style="background:#ffb74d"></div> Preference</div>
    <div class="legend-item" data-type="BELIEF">          <div class="legend-dot" style="background:#ef9a9a"></div> Belief</div>
    <div class="legend-item" data-type="SESSION">         <div class="legend-dot" style="background:#90a4ae"></div> Session</div>
    <div class="legend-item" data-type="SESSION_SUMMARY"> <div class="legend-dot" style="background:#4dd0e1"></div> Session Summary</div>
    <div class="legend-item" data-type="PROCEDURE">       <div class="legend-dot" style="background:#ce93d8"></div> Procedure</div>
  </div>

  <div id="edge-legend">
    <h3>Edge Types</h3>
    <div class="edge-legend-item"><div class="edge-swatch" style="background:#58a6ff"></div> WORKS_ON / USES</div>
    <div class="edge-legend-item"><div class="edge-swatch" style="background:#ffb74d"></div> PREFERS</div>
    <div class="edge-legend-item"><div class="edge-swatch" style="background:#4dd0e1"></div> SUPPORTS_FACT / MENTIONS</div>
    <div class="edge-legend-item"><div class="edge-swatch" style="background:#d29922"></div> TEMPORALLY_AFTER</div>
    <div class="edge-legend-item"><div class="edge-swatch" style="background:#4a7fa5"></div> CO_OCCURS</div>
    <div class="edge-legend-item"><div class="edge-swatch dashed"></div> SUPERSEDES (archived)</div>
  </div>

  <div id="zone-controls">
    <h3>Zones</h3>
    <button class="zone-btn active" data-zone="active">Active</button>
    <button class="zone-btn active" data-zone="archived">Archived</button>
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
const RAW_DATA    = __GRAPH_DATA__;
const RAW_STATS   = __GRAPH_STATS__;
const DEMO_QUERIES = __DEMO_QUERIES__;

// Populate stats
document.getElementById("s-nodes").textContent    = RAW_STATS.nodes      ?? 0;
document.getElementById("s-edges").textContent    = RAW_STATS.edges      ?? 0;
document.getElementById("s-core").textContent     = RAW_STATS.core_nodes ?? 0;
document.getElementById("s-archived").textContent = RAW_STATS.archived   ?? 0;

// ---- State ----
let activeZones   = new Set(["active", "archived"]);
let hiddenTypes   = new Set();
let selectedNode  = null;
let activeQuery   = null;

// ---- Build query chips ----
const examplesEl = document.getElementById("query-examples");
DEMO_QUERIES.forEach((q, i) => {
  const chip = document.createElement("button");
  chip.className = "query-chip";
  chip.textContent = q.text;
  chip.onclick = () => runQuery(i);
  examplesEl.appendChild(chip);
});

document.getElementById("query-input").addEventListener("keydown", e => {
  if (e.key === "Enter") {
    const text = e.target.value.trim();
    if (!text) return;
    const idx = DEMO_QUERIES.findIndex(q =>
      q.text.toLowerCase().includes(text.toLowerCase()) ||
      text.toLowerCase().includes(q.text.toLowerCase().split(" ")[0])
    );
    if (idx >= 0) runQuery(idx);
  }
});

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

  // Links — colored by type, dashed for SUPERSEDES
  linkSel = container.append("g").selectAll("line")
    .data(linksCopy).join("line")
    .attr("class", "link")
    .attr("stroke",           d => d.color || "#4a7fa5")
    .attr("stroke-width",     d => d.type === "SUPERSEDES" ? 2 : Math.max(1, d.weight * 2.5))
    .attr("stroke-dasharray", d => d.type === "SUPERSEDES" ? "6,3" : null)
    .attr("marker-end", "url(#arrowhead)");

  // Edge labels (shown on hover)
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
    .attr("stroke", d => d.zone === "archived" ? "#f85149" : "none")
    .attr("stroke-dasharray", d => d.zone === "archived" ? "4,2" : null)
    .attr("stroke-width", 1.5);

  // Core ring
  coreRingSel = nodeGroup.filter(d => d.is_core)
    .append("circle")
    .attr("class", "core-ring")
    .attr("r", d => nodeRadius(d) + 4);

  // Labels
  labelSel = nodeGroup.append("text")
    .attr("class", "node-label")
    .attr("dy", d => nodeRadius(d) + 12)
    .text(d => d.label.length > 28 ? d.label.slice(0, 26) + "…" : d.label)
    .style("display", null);

  // Tooltip
  const tooltip = document.getElementById("tooltip");
  nodeGroup
    .on("mouseover", (event, d) => {
      const archivedTag = d.zone === "archived" ? " ⚠ ARCHIVED" : "";
      document.getElementById("tt-type").textContent    = d.type + (d.is_core ? " ★ CORE" : "") + archivedTag;
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

  // Edge label on hover
  linkSel
    .on("mouseover", function(event, d) {
      d3.select(this).attr("stroke-opacity", 1).attr("stroke-width", d => Math.max(2, d.weight * 4));
      const idx = linksCopy.indexOf(d);
      edgeLabelSel.filter((_, i) => i === idx).style("display", null);
    })
    .on("mouseout",  function(event, d) {
      d3.select(this).attr("stroke-opacity", 0.55).attr("stroke-width", d => d.type === "SUPERSEDES" ? 2 : Math.max(1, d.weight * 2.5));
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

  // Re-apply active query highlight if any
  if (activeQuery !== null) applyQueryHighlight(activeQuery);
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

// ---- Query mode ----
function runQuery(idx) {
  activeQuery = idx;
  const q = DEMO_QUERIES[idx];

  // Update chip styles
  document.querySelectorAll(".query-chip").forEach((c, i) => {
    c.classList.toggle("active", i === idx);
  });
  document.getElementById("query-input").value = q.text;

  // Routing badge
  const badgeEl = document.getElementById("route-badge");
  badgeEl.style.display = "block";
  badgeEl.innerHTML = `Route: <span class="badge badge-${q.route}">${q.route}</span>`;

  // Activation list
  const listEl = document.getElementById("activation-list");
  listEl.style.display = "block";
  const sorted = Object.entries(q.activated).sort((a, b) => b[1] - a[1]).slice(0, 7);
  listEl.innerHTML = "<div style='font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;'>Why these surfaced</div>" +
    sorted.map(([nid, level]) => {
      const node = RAW_DATA.nodes.find(n => n.id === nid);
      if (!node) return "";
      const pct = Math.round(level * 100);
      return `<div class="activated-item" onclick="window.highlightById('${nid}')">
        <div class="activated-item-header">
          <span class="activated-item-type">${node.type}</span>
          <span style="color:#58a6ff;font-size:10px">${pct}%</span>
        </div>
        <span class="activated-item-label">${node.label}</span>
        <div class="activation-bar-wrap"><div class="activation-bar" style="width:${pct}%"></div></div>
      </div>`;
    }).join("");

  document.getElementById("clear-query").style.display = "block";

  applyQueryHighlight(idx);
}

function applyQueryHighlight(idx) {
  const q = DEMO_QUERIES[idx];
  const activated = q.activated;

  container.selectAll(".node").each(function(d) {
    const level = activated[d.id] || 0;
    const circle = d3.select(this).select("circle");
    if (level > 0) {
      circle.attr("fill-opacity", Math.max(0.6, level));
      if (level > 0.5) {
        circle.style("filter", `drop-shadow(0 0 ${Math.round(4 + level * 8)}px ${d.color})`);
      } else {
        circle.style("filter", null);
      }
    } else {
      circle.attr("fill-opacity", d.opacity * 0.12).style("filter", null);
    }
  });

  if (linkSel) {
    linkSel.attr("stroke-opacity", l => {
      const s = l.source.id ?? l.source;
      const t = l.target.id ?? l.target;
      return (activated[s] > 0 && activated[t] > 0) ? 0.85 : 0.06;
    });
  }
}

function clearQuery() {
  activeQuery = null;
  document.querySelectorAll(".query-chip").forEach(c => c.classList.remove("active"));
  document.getElementById("query-input").value = "";
  document.getElementById("route-badge").style.display = "none";
  document.getElementById("activation-list").style.display = "none";
  document.getElementById("clear-query").style.display = "none";

  container.selectAll(".node circle")
    .attr("fill-opacity", d => d.opacity)
    .style("filter", null);
  if (linkSel) linkSel.attr("stroke-opacity", 0.55);
}

// ---- Node selection ----
function selectNode(d, nodeGroup, linksCopy, nodeMap) {
  selectedNode = d.id;
  nodeGroup.classed("selected", n => n.id === d.id);

  const connectedIds = new Set([d.id]);
  const connectedLinks = linksCopy.filter(l => {
    const s = l.source.id ?? l.source;
    const t = l.target.id ?? l.target;
    if (s === d.id || t === d.id) { connectedIds.add(s); connectedIds.add(t); return true; }
    return false;
  });

  nodeGroup.selectAll("circle").attr("fill-opacity", n =>
    connectedIds.has(n.id) ? n.opacity : n.opacity * 0.2
  );
  if (linkSel) linkSel.attr("stroke-opacity", l => {
    const s = l.source.id ?? l.source;
    const t = l.target.id ?? l.target;
    return (s === d.id || t === d.id) ? 0.9 : 0.08;
  });

  const panel  = document.getElementById("detail-content");
  const coreBadge     = d.is_core    ? '<span class="core-badge">★ CORE MEMORY</span>' : "";
  const archivedBadge = d.zone === "archived" ? '<span class="archived-badge">⚠ ARCHIVED</span>' : "";
  const tagStr = d.tags.length ? d.tags.join(", ") : "—";

  const connections = connectedLinks.map(l => {
    const otherId = (l.source.id ?? l.source) === d.id ? (l.target.id ?? l.target) : (l.source.id ?? l.source);
    const other   = nodeMap.get(otherId);
    const dir     = (l.source.id ?? l.source) === d.id ? "→" : "←";
    if (!other) return "";
    const edgeColor = l.color || "#58a6ff";
    return `<div class="connected-node" onclick="highlightById('${other.id}')">
      <span class="edge-type" style="color:${edgeColor}">${dir} ${l.type}</span><br>
      <span class="node-label">${other.label}</span>
    </div>`;
  }).join("");

  panel.innerHTML = `
    <div style="margin-bottom:8px">${coreBadge}${archivedBadge}</div>
    <div class="detail-node-content">${d.full}</div>
    <div class="detail-row"><span class="detail-key">Type</span>        <span class="detail-val">${d.type}</span></div>
    <div class="detail-row"><span class="detail-key">Zone</span>        <span class="detail-val">${d.zone}</span></div>
    <div class="detail-row"><span class="detail-key">Salience</span>    <span class="detail-val">${d.salience}</span></div>
    <div class="detail-row"><span class="detail-key">Activations</span> <span class="detail-val">${d.activation_count}</span></div>
    <div class="detail-row"><span class="detail-key">Created</span>     <span class="detail-val">${d.created_at}</span></div>
    <div class="detail-row"><span class="detail-key">Tags</span>        <span class="detail-val">${tagStr}</span></div>
    ${d.superseded_at ? `<div class="detail-row"><span class="detail-key">Superseded</span><span class="detail-val" style="color:#f85149">${d.superseded_at.slice(0,10)}</span></div>` : ""}
    ${connections ? `<div style="margin-top:12px;font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Connections (${connectedLinks.length})</div>${connections}` : ""}
  `;
}

function clearSelection(nodeGroup) {
  selectedNode = null;
  nodeGroup.classed("selected", false);
  if (activeQuery !== null) {
    applyQueryHighlight(activeQuery);
  } else {
    nodeGroup.selectAll("circle").attr("fill-opacity", d => d.opacity);
    if (linkSel) linkSel.attr("stroke-opacity", 0.55);
  }
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
