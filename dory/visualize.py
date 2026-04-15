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
    "ENTITY":          "#58a6ff",
    "CONCEPT":         "#c084fc",
    "EVENT":           "#4ade80",
    "PREFERENCE":      "#fb923c",
    "BELIEF":          "#f87171",
    "SESSION":         "#64748b",
    "SESSION_SUMMARY": "#22d3ee",
    "PROCEDURE":       "#e879f9",
    "WORKING":         "#facc15",
}

# Base opacity for edges by type — drives visual hierarchy
_EDGE_BASE_OPACITY = {
    "SUPERSEDES":        0.75,
    "REFINES":           0.65,
    "TEMPORALLY_AFTER":  0.55,
    "TEMPORALLY_BEFORE": 0.55,
    "SUPPORTS_FACT":     0.40,
    "MENTIONS":          0.35,
    "PREFERS":           0.35,
    "WORKS_ON":          0.25,
    "USES":              0.25,
    "CO_OCCURS":         0.08,
}

_EDGE_COLORS = {
    "TEMPORALLY_AFTER":  "#d29922",
    "TEMPORALLY_BEFORE": "#d29922",
    "SUPERSEDES":        "#f85149",
    "REFINES":           "#a78bfa",
    "SUPPORTS_FACT":     "#22d3ee",
    "MENTIONS":          "#22d3ee",
    "PREFERS":           "#fb923c",
    "WORKS_ON":          "#58a6ff",
    "USES":              "#58a6ff",
    "CO_OCCURS":         "#334155",
}

_ZONE_OPACITY = {
    ZONE_ACTIVE:   1.0,
    ZONE_ARCHIVED: 0.28,
    ZONE_EXPIRED:  0.10,
}


def _build_graph_data(graph: Graph, zones: list[str]) -> dict:
    from collections import defaultdict
    node_ids: set[str] = set()
    degree: dict[str, int] = defaultdict(int)

    # First pass: collect node ids and compute degree
    all_edges = graph.all_edges()
    candidate_nodes = {n.id for n in graph.all_nodes(zone=None) if n.zone in zones}
    for e in all_edges:
        if e.source_id in candidate_nodes and e.target_id in candidate_nodes:
            degree[e.source_id] += 1
            degree[e.target_id] += 1

    nodes = []
    for n in graph.all_nodes(zone=None):
        if n.zone not in zones:
            continue
        node_ids.add(n.id)
        label = n.content if len(n.content) <= 50 else n.content[:47] + "…"
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
            "degree":           degree[n.id],
            "created_at":       n.created_at[:10],
            "color":            _NODE_COLORS.get(n.type.value, "#888"),
            "opacity":          _ZONE_OPACITY.get(n.zone, 1.0),
            "superseded_at":    n.superseded_at,
        })

    links = []
    for e in all_edges:
        if e.source_id in node_ids and e.target_id in node_ids:
            links.append({
                "source":       e.source_id,
                "target":       e.target_id,
                "type":         e.type.value,
                "weight":       round(e.weight, 3),
                "color":        _EDGE_COLORS.get(e.type.value, "#334155"),
                "base_opacity": _EDGE_BASE_OPACITY.get(e.type.value, 0.10),
            })

    return {"nodes": nodes, "links": links}


def render_html(
    graph: Graph,
    zones: list[str] | None = None,
    demo_queries: list | None = None,
    allow_remote_js: bool = False,
) -> str:
    if zones is None:
        zones = [ZONE_ACTIVE]
    data  = _build_graph_data(graph, zones)
    stats = graph.stats()
    html  = _HTML_TEMPLATE
    html  = html.replace(
        "__GRAPH_DATA__",
        json.dumps(data).replace("</", "<\\/"),
    )
    html  = html.replace(
        "__GRAPH_STATS__",
        json.dumps(stats).replace("</", "<\\/"),
    )
    html  = html.replace(
        "__DEMO_QUERIES__",
        json.dumps(demo_queries or []).replace("</", "<\\/"),
    )
    html  = html.replace(
        "__D3_SCRIPT_TAG__",
        '<script src="https://d3js.org/d3.v7.min.js"></script>' if allow_remote_js else "",
    )
    return html


def open_visualization(
    graph: Graph,
    output_path: Path | None = None,
    zones: list[str] | None = None,
    open_browser: bool = True,
    demo_queries: list | None = None,
    allow_remote_js: bool = False,
) -> Path:
    """Generate the HTML visualization and optionally open it in a browser."""
    html = render_html(graph, zones, demo_queries, allow_remote_js=allow_remote_js)
    if output_path is None:
        fd, tmp = tempfile.mkstemp(suffix=".html", prefix="dory_graph_")
        os.close(fd)
        output_path = Path(tmp)
    output_path.write_text(html, encoding="utf-8")
    if open_browser:
        webbrowser.open(output_path.as_uri())
    return output_path


# ---------------------------------------------------------------------------
# HTML template — v2
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dory Memory Graph</title>
__D3_SCRIPT_TAG__
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

/* ── Sidebar ── */
#sidebar {
  width: 280px;
  min-width: 280px;
  background: #0d1117;
  border-right: 1px solid #21262d;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

#sidebar-header {
  padding: 14px 16px 10px;
  border-bottom: 1px solid #21262d;
}
#sidebar-header h1 { font-size: 16px; font-weight: 700; color: #f0f6fc; letter-spacing: 0.3px; }
#sidebar-header p  { font-size: 11px; color: #484f58; margin-top: 2px; }

#stats {
  padding: 10px 16px;
  border-bottom: 1px solid #21262d;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.stat { text-align: center; }
.stat-val { font-size: 18px; font-weight: 700; color: #58a6ff; }
.stat-lbl { font-size: 9px; color: #484f58; text-transform: uppercase; letter-spacing: 0.5px; }

/* ── Query panel ── */
#query-panel {
  padding: 10px 16px;
  border-bottom: 1px solid #21262d;
  flex-shrink: 0;
}
#query-panel-title {
  font-size: 10px; color: #484f58; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 8px; font-weight: 600;
}
#query-input {
  background: #161b22;
  border: 1px solid #21262d;
  color: #c9d1d9;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  width: 100%;
  outline: none;
  margin-bottom: 6px;
}
#query-input:focus { border-color: #58a6ff; }
#query-input::placeholder { color: #30363d; }

#query-examples { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.query-chip {
  background: #161b22;
  border: 1px solid #21262d;
  color: #8b949e;
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
}
.query-chip:hover { border-color: #58a6ff; color: #c9d1d9; }
.query-chip.active { border-color: #58a6ff; color: #58a6ff; background: #0d1f3c; }

#route-badge { display: none; margin-bottom: 6px; }
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;
}
.badge-graph    { background: #0d1f3c; color: #58a6ff; border: 1px solid #1d4ed8; }
.badge-episodic { background: #0f2b0f; color: #4ade80; border: 1px solid #166534; }
.badge-hybrid   { background: #2d1a00; color: #fb923c; border: 1px solid #92400e; }

#reasoning-section { display: none; }
#reasoning-title {
  font-size: 10px; color: #484f58; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 6px; margin-top: 8px;
}
.activated-item {
  display: flex; flex-direction: column; gap: 2px;
  background: #161b22; border-radius: 4px;
  padding: 5px 8px; margin-bottom: 3px;
  font-size: 11px; cursor: pointer; border: 1px solid transparent;
  transition: border-color 0.15s;
}
.activated-item:hover { border-color: #30363d; }
.activated-item-header { display: flex; justify-content: space-between; align-items: center; }
.activated-item-type { font-size: 10px; }
.activated-item-label { color: #c9d1d9; line-height: 1.3; }
.activation-bar-wrap { background: #0d1117; border-radius: 2px; height: 2px; margin-top: 3px; }
.activation-bar { height: 2px; border-radius: 2px; transition: width 0.4s ease; }

#clear-query {
  display: none; background: none; border: none;
  color: #484f58; font-size: 10px; cursor: pointer; padding: 2px 0;
}
#clear-query:hover { color: #8b949e; }

/* ── Legend ── */
#legend {
  padding: 10px 16px;
  border-bottom: 1px solid #21262d;
  flex-shrink: 0;
}
#legend h3 { font-size: 10px; color: #484f58; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.legend-item {
  display: flex; align-items: center; gap: 7px; margin-bottom: 4px;
  font-size: 11px; cursor: pointer; padding: 2px 4px; border-radius: 4px;
  color: #8b949e; transition: all 0.15s;
}
.legend-item:hover { color: #c9d1d9; }
.legend-item.dimmed { opacity: 0.3; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

/* ── Edge legend ── */
#edge-legend {
  padding: 8px 16px;
  border-bottom: 1px solid #21262d;
  flex-shrink: 0;
}
#edge-legend h3 { font-size: 10px; color: #484f58; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.edge-legend-item { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; font-size: 10px; color: #484f58; }
.edge-swatch { width: 20px; height: 2px; border-radius: 1px; flex-shrink: 0; }
.edge-swatch.dashed {
  background: repeating-linear-gradient(90deg, #f85149 0px, #f85149 4px, transparent 4px, transparent 8px);
}

/* ── Zone controls ── */
#zone-controls {
  padding: 8px 16px;
  border-bottom: 1px solid #21262d;
  flex-shrink: 0;
}
#zone-controls h3 { font-size: 10px; color: #484f58; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.zone-btn {
  background: #161b22; border: 1px solid #21262d; color: #484f58;
  padding: 3px 8px; border-radius: 4px; font-size: 10px;
  cursor: pointer; margin-right: 4px; transition: all 0.15s;
}
.zone-btn.active { background: #0d1f3c; border-color: #1d4ed8; color: #58a6ff; }

/* ── Inspector (right panel) ── */
#inspector {
  width: 0; min-width: 0; overflow: hidden;
  background: #0d1117; border-left: 1px solid #21262d;
  transition: width 0.25s ease; flex-shrink: 0;
}
#inspector.open { width: 320px; min-width: 320px; }
#inspector-inner {
  width: 320px; height: 100vh; overflow-y: auto;
  padding: 16px; display: flex; flex-direction: column; gap: 12px;
}
#inspector-header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;
}
#inspector-badges { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; flex: 1; }
#inspector-type-badge {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.8px; padding: 3px 10px; border-radius: 10px; border: 1px solid;
}
.core-badge {
  display: inline-block; background: #1c1400; border: 1px solid #bb8009;
  color: #d29922; font-size: 9px; padding: 1px 6px; border-radius: 10px;
}
.archived-badge {
  display: inline-block; background: #1c0000; border: 1px solid #f85149;
  color: #f85149; font-size: 9px; padding: 1px 6px; border-radius: 10px;
}
#inspector-close {
  background: none; border: none; color: #484f58; font-size: 16px;
  cursor: pointer; padding: 0; line-height: 1; flex-shrink: 0;
}
#inspector-close:hover { color: #c9d1d9; }
#inspector-content-text {
  font-size: 13px; color: #e6edf3; line-height: 1.6;
  background: #161b22; padding: 10px 12px; border-radius: 6px;
  border: 1px solid #21262d; white-space: pre-wrap; word-break: break-word;
}
.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; }
.meta-item { display: flex; flex-direction: column; gap: 1px; }
.meta-key { font-size: 9px; color: #484f58; text-transform: uppercase; letter-spacing: 0.5px; }
.meta-val { font-size: 12px; color: #58a6ff; font-family: monospace; }
.inspector-section-title {
  font-size: 9px; color: #484f58; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 5px;
}
.conn-item {
  display: flex; align-items: flex-start; gap: 8px;
  background: #161b22; border: 1px solid transparent; border-radius: 4px;
  padding: 6px 8px; margin-bottom: 3px; cursor: pointer; font-size: 11px;
  transition: border-color 0.15s;
}
.conn-item:hover { border-color: #30363d; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 3px; }
.conn-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.conn-edge-type { font-size: 9px; color: #484f58; }
.conn-label { color: #c9d1d9; word-break: break-word; }

/* ── Nav sections dimming on node select ── */
#nav-sections { transition: opacity 0.2s; }
#nav-sections.dimmed { opacity: 0.3; pointer-events: none; }

/* ── Graph area ── */
#graph-area { flex: 1; position: relative; overflow: hidden; }

#offline-notice {
  display: none; margin: 16px; padding: 14px 16px; border-radius: 10px;
  border: 1px solid #21262d; background: #161b22; color: #c9d1d9;
  font-size: 12px; line-height: 1.5;
}
#offline-notice strong { color: #f0f6fc; }
#offline-notice code { color: #58a6ff; }

#fallback-view {
  display: none; padding: 16px; overflow-y: auto; height: calc(100vh - 52px);
}
.fallback-section {
  margin-bottom: 18px; background: #161b22; border: 1px solid #21262d;
  border-radius: 10px; padding: 14px 16px;
}
.fallback-section h3 { font-size: 11px; color: #484f58; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 10px; }
.fallback-row { padding: 7px 0; border-top: 1px solid #161b22; font-size: 11px; line-height: 1.5; }
.fallback-row:first-child { border-top: none; padding-top: 0; }
.fallback-type { color: #58a6ff; font-size: 10px; }
.fallback-meta { color: #484f58; font-size: 10px; }

svg { width: 100%; height: 100%; }

.link { transition: stroke-opacity 0.2s; }
.node circle { cursor: pointer; }
.node.selected circle { filter: brightness(1.3); }

.node-label {
  font-size: 10px; fill: #8b949e; pointer-events: none; text-anchor: middle;
}
.node-label.hidden { display: none; }

.core-ring { fill: none; stroke: #d29922; stroke-width: 2px; pointer-events: none; }

.edge-label {
  font-size: 9px; fill: #484f58; pointer-events: none; text-anchor: middle;
}

#tooltip {
  position: absolute; background: #161b22; border: 1px solid #30363d;
  border-radius: 6px; padding: 7px 10px; font-size: 11px;
  pointer-events: none; opacity: 0; transition: opacity 0.1s;
  max-width: 220px; z-index: 100;
}
#tooltip .tt-type { color: #58a6ff; font-size: 9px; text-transform: uppercase; }
#tooltip .tt-content { color: #f0f6fc; margin-top: 2px; line-height: 1.4; }

#search-bar { position: absolute; top: 12px; right: 12px; z-index: 10; }
#search-input {
  background: #161b22; border: 1px solid #21262d;
  color: #c9d1d9; padding: 5px 10px; border-radius: 6px;
  font-size: 11px; width: 190px; outline: none;
}
#search-input:focus { border-color: #58a6ff; }
#search-input::placeholder { color: #30363d; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <h1>Dory Memory</h1>
    <p>Knowledge graph · spreading activation</p>
  </div>

  <div id="stats">
    <div class="stat"><div class="stat-val" id="s-nodes">0</div><div class="stat-lbl">Nodes</div></div>
    <div class="stat"><div class="stat-val" id="s-edges">0</div><div class="stat-lbl">Edges</div></div>
    <div class="stat"><div class="stat-val" id="s-core">0</div><div class="stat-lbl">Core</div></div>
    <div class="stat"><div class="stat-val" id="s-archived">0</div><div class="stat-lbl">Archived</div></div>
  </div>

  <div id="query-panel">
    <div id="query-panel-title">Query Memory</div>
    <input id="query-input" type="text" placeholder="Ask a question…">
    <div id="query-examples"></div>
    <div id="route-badge"></div>
    <div id="reasoning-section">
      <div id="reasoning-title">Why these surfaced</div>
      <div id="activation-list"></div>
    </div>
    <button id="clear-query" onclick="clearQuery()">✕ clear</button>
  </div>

  <div id="nav-sections">
    <div id="legend">
      <h3>Node Types</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0">
        <div class="legend-item" data-type="ENTITY">       <div class="legend-dot" style="background:#58a6ff"></div>Entity</div>
        <div class="legend-item" data-type="CONCEPT">      <div class="legend-dot" style="background:#c084fc"></div>Concept</div>
        <div class="legend-item" data-type="EVENT">        <div class="legend-dot" style="background:#4ade80"></div>Event</div>
        <div class="legend-item" data-type="PREFERENCE">   <div class="legend-dot" style="background:#fb923c"></div>Preference</div>
        <div class="legend-item" data-type="BELIEF">       <div class="legend-dot" style="background:#f87171"></div>Belief</div>
        <div class="legend-item" data-type="WORKING">      <div class="legend-dot" style="background:#facc15"></div>Working</div>
        <div class="legend-item" data-type="SESSION_SUMMARY"><div class="legend-dot" style="background:#22d3ee"></div>Episodic</div>
        <div class="legend-item" data-type="PROCEDURE">    <div class="legend-dot" style="background:#e879f9"></div>Procedure</div>
      </div>
    </div>

    <div id="edge-legend">
      <h3>Edge Types</h3>
      <div class="edge-legend-item"><div class="edge-swatch dashed"></div>SUPERSEDES</div>
      <div class="edge-legend-item"><div class="edge-swatch" style="background:#d29922"></div>TEMPORALLY_AFTER</div>
      <div class="edge-legend-item"><div class="edge-swatch" style="background:#22d3ee"></div>SUPPORTS_FACT</div>
      <div class="edge-legend-item"><div class="edge-swatch" style="background:#58a6ff"></div>WORKS_ON / USES</div>
      <div class="edge-legend-item"><div class="edge-swatch" style="background:#334155;opacity:0.5"></div>CO_OCCURS</div>
    </div>

    <div id="zone-controls">
      <h3>Zones</h3>
      <button class="zone-btn active" data-zone="active">Active</button>
      <button class="zone-btn active" data-zone="archived">Archived</button>
      <button class="zone-btn" data-zone="expired">Expired</button>
    </div>
  </div>
</div>

<div id="graph-area">
  <div id="search-bar">
    <input id="search-input" type="text" placeholder="Search nodes…">
  </div>
  <div id="offline-notice"></div>
  <div id="fallback-view"></div>
  <div id="tooltip">
    <div class="tt-type" id="tt-type"></div>
    <div class="tt-content" id="tt-content"></div>
  </div>
  <svg id="graph-svg"></svg>
</div>

<div id="inspector">
  <div id="inspector-inner">
    <div id="inspector-header">
      <div id="inspector-badges">
        <span id="inspector-type-badge"></span>
      </div>
      <button id="inspector-close" onclick="clearSelection()">✕</button>
    </div>
    <div id="inspector-content-text"></div>
    <div class="meta-grid" id="inspector-meta"></div>
    <div id="inspector-connections" style="display:none">
      <div class="inspector-section-title" id="inspector-conn-title"></div>
      <div id="inspector-conn-list"></div>
    </div>
  </div>
</div>

<script>
const RAW_DATA    = __GRAPH_DATA__;
const RAW_STATS   = __GRAPH_STATS__;
const DEMO_QUERIES = __DEMO_QUERIES__;

function escapeHtml(v) {
  return String(v).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;");
}

// ── Fallback (no D3) ──
function renderFallbackView() {
  document.getElementById("graph-svg").style.display = "none";
  document.getElementById("tooltip").style.display = "none";
  document.getElementById("query-panel").style.display = "none";
  document.getElementById("legend").style.display = "none";
  document.getElementById("edge-legend").style.display = "none";
  document.getElementById("zone-controls").style.display = "none";

  const notice = document.getElementById("offline-notice");
  notice.style.display = "block";
  notice.innerHTML = "<strong>Local-only mode</strong><br>Regenerate with <code>allow_remote_js=True</code> for the interactive graph.";

  const fallback = document.getElementById("fallback-view");
  fallback.style.display = "block";
  const nodeRows = RAW_DATA.nodes.map(n => `
    <div class="fallback-row">
      <div class="fallback-type">${escapeHtml(n.type)}${n.is_core?" [CORE]":""}</div>
      <div>${escapeHtml(n.full)}</div>
      <div class="fallback-meta">zone=${escapeHtml(n.zone)} · salience=${escapeHtml(n.salience)} · deg=${escapeHtml(n.degree)}</div>
    </div>`).join("");
  fallback.innerHTML = `<div class="fallback-section"><h3>Nodes (${RAW_DATA.nodes.length})</h3>${nodeRows}</div>`;
}

if (!window.d3) {
  document.getElementById("s-nodes").textContent    = RAW_STATS.nodes      ?? 0;
  document.getElementById("s-edges").textContent    = RAW_STATS.edges      ?? 0;
  document.getElementById("s-core").textContent     = RAW_STATS.core_nodes ?? 0;
  document.getElementById("s-archived").textContent = RAW_STATS.archived   ?? 0;
  renderFallbackView();
} else {

document.getElementById("s-nodes").textContent    = RAW_STATS.nodes      ?? 0;
document.getElementById("s-edges").textContent    = RAW_STATS.edges      ?? 0;
document.getElementById("s-core").textContent     = RAW_STATS.core_nodes ?? 0;
document.getElementById("s-archived").textContent = RAW_STATS.archived   ?? 0;

// ── State ──
let activeZones  = new Set(["active", "archived"]);
let hiddenTypes  = new Set();
let selectedNode = null;
let activeQuery  = null;

// ── Compute top-N nodes by degree for always-on labels ──
const TOP_LABEL_COUNT = 8;
const sortedByDegree = [...RAW_DATA.nodes].sort((a,b) => b.degree - a.degree);
const topLabelIds = new Set(sortedByDegree.slice(0, TOP_LABEL_COUNT).map(n => n.id));

// ── Query chips ──
const examplesEl = document.getElementById("query-examples");
DEMO_QUERIES.forEach((q, i) => {
  const chip = document.createElement("button");
  chip.className = "query-chip";
  chip.textContent = q.text;
  chip.onclick = () => runQuery(i);
  examplesEl.appendChild(chip);
});

document.getElementById("query-input").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  const text = e.target.value.trim();
  if (!text) return;
  const idx = DEMO_QUERIES.findIndex(q =>
    q.text.toLowerCase().includes(text.toLowerCase()) ||
    text.toLowerCase().includes(q.text.toLowerCase().split(" ")[0])
  );
  if (idx >= 0) runQuery(idx);
});

// ── SVG setup ──
const svg    = d3.select("#graph-svg");
const width  = () => document.getElementById("graph-area").clientWidth;
const height = () => document.getElementById("graph-area").clientHeight;
const container = svg.append("g");

svg.call(
  d3.zoom().scaleExtent([0.05, 5])
    .on("zoom", event => container.attr("transform", event.transform))
);

// Arrowhead
svg.append("defs").selectAll("marker")
  .data(["default", "supersedes", "temporal"])
  .join("marker")
  .attr("id", d => `arrow-${d}`)
  .attr("viewBox", "0 -4 8 8")
  .attr("refX", 22).attr("refY", 0)
  .attr("markerWidth", 5).attr("markerHeight", 5)
  .attr("orient", "auto")
  .append("path")
    .attr("d", "M0,-4L8,0L0,4")
    .attr("fill", d => d === "supersedes" ? "#f85149" : d === "temporal" ? "#d29922" : "#30363d");

// ── Node sizing ──
function nodeRadius(d) {
  const r = 5 + d.degree * 1.8 + d.salience * 8;
  return Math.max(5, Math.min(28, r));
}

// ── Visible data ──
function visibleData() {
  const nodes = RAW_DATA.nodes.filter(n => activeZones.has(n.zone) && !hiddenTypes.has(n.type));
  const nodeIds = new Set(nodes.map(n => n.id));
  const links = RAW_DATA.links.filter(l =>
    nodeIds.has(l.source.id ?? l.source) && nodeIds.has(l.target.id ?? l.target)
  );
  return { nodes, links };
}

// ── Main build ──
let simulation = null;
let linkSel, nodeGroupSel, labelSel, coreRingSel, edgeLabelSel;

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
    .force("link",    d3.forceLink(linksCopy).id(d => d.id).distance(d => 60 + (1 - d.weight) * 50).strength(0.7))
    .force("charge",  d3.forceManyBody().strength(d => -200 - d.degree * 30 - d.salience * 150))
    .force("x",       d3.forceX(width()  / 2).strength(0.05))
    .force("y",       d3.forceY(height() / 2).strength(0.05))
    .force("collide", d3.forceCollide(d => nodeRadius(d) + 6))
    .alphaDecay(0.010)
    .velocityDecay(0.38);

  // ── Links ──
  linkSel = container.append("g").selectAll("line")
    .data(linksCopy).join("line")
    .attr("class", "link")
    .attr("stroke",       d => d.color)
    .attr("stroke-width", d => d.type === "SUPERSEDES" ? 1.5 : Math.max(0.8, d.weight * 2))
    .attr("stroke-dasharray", d => d.type === "SUPERSEDES" ? "5,3" : null)
    .attr("stroke-opacity", d => d.base_opacity)
    .attr("marker-end", d =>
      d.type === "SUPERSEDES" ? "url(#arrow-supersedes)" :
      d.type.startsWith("TEMPORALLY") ? "url(#arrow-temporal)" :
      "url(#arrow-default)"
    );

  // ── Edge labels (hover) ──
  edgeLabelSel = container.append("g").selectAll("text")
    .data(linksCopy).join("text")
    .attr("class", "edge-label")
    .text(d => d.type)
    .style("display", "none");

  // ── Nodes ──
  nodeGroupSel = container.append("g").selectAll("g")
    .data(nodesCopy).join("g")
    .attr("class", "node")
    .call(
      d3.drag()
        .on("start", (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end",   (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  nodeGroupSel.append("circle")
    .attr("r",    d => nodeRadius(d))
    .attr("fill", d => d.zone === "archived" ? "#1c1c1c" : d.color)
    .attr("fill-opacity", d => d.opacity)
    .attr("stroke", d => d.zone === "archived" ? "#f8514966" : "none")
    .attr("stroke-width", d => d.zone === "archived" ? 1.5 : 0)
    .attr("stroke-dasharray", d => d.zone === "archived" ? "3,2" : null);

  // Core ring
  coreRingSel = nodeGroupSel.filter(d => d.is_core)
    .append("circle")
    .attr("class", "core-ring")
    .attr("r", d => nodeRadius(d) + 4);

  // ── Labels — only top-N + hovered + selected shown by default ──
  labelSel = nodeGroupSel.append("text")
    .attr("class", "node-label")
    .attr("dy", d => nodeRadius(d) + 11)
    .text(d => d.label.length > 22 ? d.label.slice(0, 20) + "…" : d.label)
    .attr("opacity", d => topLabelIds.has(d.id) ? 0.7 : 0);

  // ── Tooltip + interactions ──
  const tooltip = document.getElementById("tooltip");
  nodeGroupSel
    .on("mouseover", (event, d) => {
      // Show label on hover
      d3.select(event.currentTarget).select(".node-label").attr("opacity", 1);
      document.getElementById("tt-type").textContent =
        d.type + (d.is_core ? " ★" : "") + (d.zone === "archived" ? " ⚠" : "");
      document.getElementById("tt-content").textContent = d.label;
      tooltip.style.opacity = "1";
    })
    .on("mousemove", event => {
      tooltip.style.left = (event.offsetX + 14) + "px";
      tooltip.style.top  = (event.offsetY - 8)  + "px";
    })
    .on("mouseout", (event, d) => {
      if (selectedNode !== d.id && !topLabelIds.has(d.id)) {
        d3.select(event.currentTarget).select(".node-label").attr("opacity", 0);
      }
      tooltip.style.opacity = "0";
    })
    .on("click", (event, d) => {
      event.stopPropagation();
      selectNode(d, nodeGroupSel, linksCopy, nodeMap);
    });

  // Edge hover — show label
  linkSel
    .on("mouseover", function(event, d) {
      d3.select(this).attr("stroke-opacity", Math.min(1, d.base_opacity + 0.4));
      const idx = linksCopy.indexOf(d);
      edgeLabelSel.filter((_,i) => i === idx).style("display", null);
    })
    .on("mouseout", function(event, d) {
      if (activeQuery === null && selectedNode === null) {
        d3.select(this).attr("stroke-opacity", d.base_opacity);
      }
      edgeLabelSel.style("display", "none");
    });

  svg.on("click", () => clearSelection());

  simulation.on("tick", () => {
    linkSel
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    edgeLabelSel
      .attr("x", d => (d.source.x + d.target.x) / 2)
      .attr("y", d => (d.source.y + d.target.y) / 2);
    nodeGroupSel.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  simulation.on("end", () => fitToView(nodesCopy));

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
  const scale = Math.min(0.92, Math.min(w / (x1 - x0 + pad * 2), h / (y1 - y0 + pad * 2)));
  const tx = w / 2 - scale * (x0 + x1) / 2;
  const ty = h / 2 - scale * (y0 + y1) / 2;
  svg.transition().duration(800).call(
    d3.zoom().transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
  );
}

// ── Query mode ──
function runQuery(idx) {
  activeQuery = idx;
  const q = DEMO_QUERIES[idx];
  document.querySelectorAll(".query-chip").forEach((c, i) => c.classList.toggle("active", i === idx));
  document.getElementById("query-input").value = q.text;

  const badgeEl = document.getElementById("route-badge");
  badgeEl.style.display = "block";
  badgeEl.innerHTML = `Route: <span class="badge badge-${q.route}">${q.route}</span>`;

  // Rank-decay the activation scores for visual differentiation
  const entries = Object.entries(q.activated).sort((a,b) => b[1] - a[1]);
  const ranked  = {};
  entries.forEach(([nid, _], i) => {
    ranked[nid] = Math.max(0.2, 1.0 - i * 0.042);
  });

  const reasoningEl = document.getElementById("reasoning-section");
  const listEl = document.getElementById("activation-list");
  reasoningEl.style.display = "block";
  listEl.innerHTML = entries.slice(0, 8).map(([nid]) => {
    const node  = RAW_DATA.nodes.find(n => n.id === nid);
    if (!node) return "";
    const score = ranked[nid];
    const pct   = Math.round(score * 100);
    return `<div class="activated-item" onclick="window.highlightById('${nid}')">
      <div class="activated-item-header">
        <span class="activated-item-type" style="color:${node.color}">${node.type}</span>
        <span style="color:#8b949e;font-size:10px">${pct}%</span>
      </div>
      <span class="activated-item-label">${node.label}</span>
      <div class="activation-bar-wrap">
        <div class="activation-bar" style="width:${pct}%;background:${node.color}"></div>
      </div>
    </div>`;
  }).join("");

  document.getElementById("clear-query").style.display = "block";
  applyQueryHighlight(idx, ranked);
}

function applyQueryHighlight(idx, ranked) {
  const q = DEMO_QUERIES[idx];
  if (!ranked) {
    const entries = Object.entries(q.activated).sort((a,b) => b[1] - a[1]);
    ranked = {};
    entries.forEach(([nid,_], i) => { ranked[nid] = Math.max(0.2, 1.0 - i * 0.042); });
  }

  // Nodes — glow activated, dim everything else hard
  nodeGroupSel.each(function(d) {
    const score  = ranked[d.id] || 0;
    const circle = d3.select(this).select("circle");
    const label  = d3.select(this).select(".node-label");
    if (score > 0) {
      circle
        .attr("fill-opacity", d.zone === "archived" ? 0.5 : Math.max(0.7, score))
        .style("filter", `drop-shadow(0 0 ${Math.round(5 + score * 12)}px ${d.color}cc)`);
      label.attr("opacity", score > 0.5 ? 1 : 0.6);
    } else {
      circle.attr("fill-opacity", d.opacity * 0.06).style("filter", null);
      label.attr("opacity", 0);
    }
  });

  // Edges — dim everything except paths between activated nodes
  if (linkSel) {
    linkSel.attr("stroke-opacity", l => {
      const s = l.source.id ?? l.source;
      const t = l.target.id ?? l.target;
      return (ranked[s] > 0 && ranked[t] > 0)
        ? Math.max(l.base_opacity, 0.7)
        : 0.03;
    });
  }
}

function clearQuery() {
  activeQuery = null;
  document.querySelectorAll(".query-chip").forEach(c => c.classList.remove("active"));
  document.getElementById("query-input").value = "";
  document.getElementById("route-badge").style.display = "none";
  document.getElementById("reasoning-section").style.display = "none";
  document.getElementById("clear-query").style.display = "none";

  nodeGroupSel.each(function(d) {
    d3.select(this).select("circle").attr("fill-opacity", d.opacity).style("filter", null);
    d3.select(this).select(".node-label").attr("opacity", topLabelIds.has(d.id) ? 0.7 : 0);
  });
  if (linkSel) linkSel.attr("stroke-opacity", d => d.base_opacity);
}

// ── Node selection / focus mode ──
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

  // Aggressive focus: everything outside 1-hop goes very dim
  nodeGroup.each(function(n) {
    const circle = d3.select(this).select("circle");
    const label  = d3.select(this).select(".node-label");
    if (connectedIds.has(n.id)) {
      circle.attr("fill-opacity", n.opacity).style("filter", n.id === d.id ? `drop-shadow(0 0 12px ${n.color}aa)` : null);
      label.attr("opacity", 1);
    } else {
      circle.attr("fill-opacity", n.opacity * 0.04).style("filter", null);
      label.attr("opacity", 0);
    }
  });

  if (linkSel) {
    linkSel.attr("stroke-opacity", l => {
      const s = l.source.id ?? l.source;
      const t = l.target.id ?? l.target;
      return (s === d.id || t === d.id) ? 0.9 : 0.02;
    });
  }

  // ── Inspector panel ──
  const inspector = document.getElementById("inspector");
  inspector.classList.add("open");
  document.getElementById("nav-sections").classList.add("dimmed");

  // Type badge
  const typeBadge = document.getElementById("inspector-type-badge");
  typeBadge.textContent = d.type;
  typeBadge.style.color = d.color;
  typeBadge.style.borderColor = d.color + "66";
  typeBadge.style.background  = d.color + "18";

  // Status badges alongside type badge
  const badgesEl = document.getElementById("inspector-badges");
  badgesEl.innerHTML = `<span id="inspector-type-badge" style="color:${d.color};border-color:${d.color}66;background:${d.color}18" class="" id="inspector-type-badge">${d.type}</span>` +
    (d.is_core ? ' <span class="core-badge">★ CORE</span>' : '') +
    (d.zone === "archived" ? ' <span class="archived-badge">ARCHIVED</span>' : '');

  // Full content text
  document.getElementById("inspector-content-text").textContent = d.full;

  // Metadata grid
  const metaItems = [
    ["Zone",        d.zone],
    ["Salience",    d.salience],
    ["Degree",      d.degree],
    ["Activations", d.activation_count],
    ["Created",     d.created_at],
    ...(d.superseded_at ? [["Superseded", d.superseded_at.slice(0,10)]] : []),
    ...(d.tags.length   ? [["Tags",       d.tags.join(", ")]]           : []),
  ];
  document.getElementById("inspector-meta").innerHTML = metaItems.map(([k, v]) =>
    `<div class="meta-item"><span class="meta-key">${k}</span><span class="meta-val">${escapeHtml(String(v))}</span></div>`
  ).join("");

  // Connections
  const connSection = document.getElementById("inspector-connections");
  if (connectedLinks.length) {
    document.getElementById("inspector-conn-title").textContent = `Connections (${connectedLinks.length})`;
    document.getElementById("inspector-conn-list").innerHTML = connectedLinks.map(l => {
      const otherId = (l.source.id ?? l.source) === d.id ? (l.target.id ?? l.target) : (l.source.id ?? l.source);
      const other   = nodeMap.get(otherId);
      const dir     = (l.source.id ?? l.source) === d.id ? "→" : "←";
      if (!other) return "";
      return `<div class="conn-item" onclick="window.highlightById('${other.id}')">
        <div class="conn-dot" style="background:${other.color}"></div>
        <div class="conn-body">
          <span class="conn-edge-type">${dir} ${l.type}</span>
          <span class="conn-label">${escapeHtml(other.label)}</span>
        </div>
      </div>`;
    }).join("");
    connSection.style.display = "block";
  } else {
    connSection.style.display = "none";
  }
}

function clearSelection() {
  if (selectedNode === null) return;
  selectedNode = null;
  if (nodeGroupSel) nodeGroupSel.classed("selected", false);
  if (activeQuery !== null) {
    applyQueryHighlight(activeQuery);
  } else {
    nodeGroupSel.each(function(d) {
      d3.select(this).select("circle").attr("fill-opacity", d.opacity).style("filter", null);
      d3.select(this).select(".node-label").attr("opacity", topLabelIds.has(d.id) ? 0.7 : 0);
    });
    if (linkSel) linkSel.attr("stroke-opacity", d => d.base_opacity);
  }
  document.getElementById("inspector").classList.remove("open");
  document.getElementById("nav-sections").classList.remove("dimmed");
}

// ── Zone toggle ──
document.querySelectorAll(".zone-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const zone = btn.dataset.zone;
    if (activeZones.has(zone)) { activeZones.delete(zone); btn.classList.remove("active"); }
    else                       { activeZones.add(zone);    btn.classList.add("active"); }
    buildGraph();
  });
});

// ── Type legend toggle ──
document.querySelectorAll(".legend-item").forEach(item => {
  item.addEventListener("click", () => {
    const type = item.dataset.type;
    if (hiddenTypes.has(type)) { hiddenTypes.delete(type); item.classList.remove("dimmed"); }
    else                       { hiddenTypes.add(type);    item.classList.add("dimmed"); }
    buildGraph();
  });
});

// ── Search ──
document.getElementById("search-input").addEventListener("input", function() {
  const q = this.value.toLowerCase().trim();
  if (!q) {
    nodeGroupSel.each(function(d) {
      d3.select(this).select("circle").attr("fill-opacity", d.opacity);
      d3.select(this).select(".node-label").attr("opacity", topLabelIds.has(d.id) ? 0.7 : 0);
    });
    return;
  }
  nodeGroupSel.each(function(d) {
    const match = d.full.toLowerCase().includes(q) || d.tags.some(t => t.toLowerCase().includes(q));
    d3.select(this).select("circle").attr("fill-opacity", match ? d.opacity : d.opacity * 0.05);
    d3.select(this).select(".node-label").attr("opacity", match ? 1 : 0);
  });
});

// ── Init ──
buildGraph();
window.addEventListener("resize", buildGraph);

window.highlightById = function(id) {
  const data    = nodeGroupSel.data();
  const nodeMap = new Map(data.map(d => [d.id, d]));
  const d       = nodeMap.get(id);
  if (!d) return;
  selectNode(d, nodeGroupSel, linkSel ? linkSel.data() : [], nodeMap);
};

} // end d3 block
</script>
</body>
</html>
"""