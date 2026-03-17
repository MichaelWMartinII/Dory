"""
JSON-LD export for Dory memory graphs.

Exports the full graph (nodes + edges) to JSON-LD format for
semantic web compatibility, interoperability with RDF tools,
and portable import/export between Dory instances.

Usage:
    from dory.graph import Graph
    from dory.export.jsonld import JSONLDExporter

    graph = Graph("engram.db")
    exporter = JSONLDExporter(graph)

    # Export to file
    exporter.export(Path("graph.jsonld"))

    # Export to dict (for API responses, etc.)
    doc = exporter.export()

    # Round-trip: import a previously exported graph
    JSONLDExporter.import_into(graph, Path("graph.jsonld"))
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..graph import Graph
from ..schema import Node, Edge, NodeType, EdgeType, ZONE_ACTIVE, now_iso, new_id


_CONTEXT = {
    "@vocab": "https://dory.memory/vocab/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "schema": "https://schema.org/",
    "id": "@id",
    "type": "@type",
    "content": "schema:description",
    "created_at": {"@id": "schema:dateCreated", "@type": "xsd:dateTime"},
    "last_activated": {"@id": "schema:dateModified", "@type": "xsd:dateTime"},
    "activation_count": {"@id": "schema:interactionCount", "@type": "xsd:integer"},
    "salience": {"@id": "schema:ratingValue", "@type": "xsd:float"},
    "is_core": {"@id": "schema:isFeatured", "@type": "xsd:boolean"},
    "zone": "schema:status",
    "tags": {"@id": "schema:keywords", "@container": "@set"},
    "weight": {"@id": "dory:weight", "@type": "xsd:float"},
    "source_id": {"@id": "schema:startPoint", "@type": "@id"},
    "target_id": {"@id": "schema:endPoint", "@type": "@id"},
    "decay_rate": {"@id": "dory:decayRate", "@type": "xsd:float"},
    "nodes": {"@id": "dory:nodes", "@container": "@set"},
    "edges": {"@id": "dory:edges", "@container": "@set"},
}

_BASE = "https://dory.memory/"


class JSONLDExporter:
    """
    Export and import Dory graphs as JSON-LD.

    JSON-LD is a W3C standard for Linked Data in JSON. Exported graphs
    can be loaded by any JSON-LD or RDF processor, posted to SPARQL
    endpoints, or imported back into Dory via ``import_into()``.
    """

    def __init__(self, graph: Graph, base_uri: str = _BASE) -> None:
        self.graph = graph
        self.base = base_uri.rstrip("/") + "/"

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(
        self,
        output_path: Path | None = None,
        include_archived: bool = False,
        include_expired: bool = False,
    ) -> dict[str, Any]:
        """
        Export the graph to a JSON-LD document.

        Parameters
        ----------
        output_path:
            If provided, write the document to this file.
        include_archived:
            Include archived (invisible to normal queries) nodes.
        include_expired:
            Include expired nodes. Implies include_archived.

        Returns the document as a dict.
        """
        zone_filter = ZONE_ACTIVE
        if include_expired:
            zone_filter = None       # all zones
        elif include_archived:
            zone_filter = None       # graph.all_nodes filters by zone param
            # handled below

        if include_expired:
            nodes = self.graph.all_nodes(zone=None)
        elif include_archived:
            active = self.graph.all_nodes(zone="active")
            archived = self.graph.all_nodes(zone="archived")
            nodes = active + archived
        else:
            nodes = self.graph.all_nodes(zone="active")

        edges = self.graph.all_edges()

        doc = {
            "@context": _CONTEXT,
            "id": f"{self.base}graph",
            "type": "dory:Graph",
            "nodes": [self._node_to_jsonld(n) for n in nodes],
            "edges": [self._edge_to_jsonld(e) for e in edges],
        }

        if output_path is not None:
            Path(output_path).write_text(json.dumps(doc, indent=2))

        return doc

    def _node_to_jsonld(self, node: Node) -> dict[str, Any]:
        return {
            "id": f"{self.base}nodes/{node.id}",
            "type": f"dory:{node.type.value}",
            "content": node.content,
            "created_at": node.created_at,
            "last_activated": node.last_activated,
            "activation_count": node.activation_count,
            "salience": round(node.salience, 4),
            "is_core": node.is_core,
            "tags": node.tags,
            "zone": node.zone,
            **({"superseded_at": node.superseded_at} if node.superseded_at else {}),
        }

    def _edge_to_jsonld(self, edge: Edge) -> dict[str, Any]:
        return {
            "id": f"{self.base}edges/{edge.id}",
            "type": f"dory:{edge.type.value}",
            "source_id": f"{self.base}nodes/{edge.source_id}",
            "target_id": f"{self.base}nodes/{edge.target_id}",
            "weight": round(edge.weight, 4),
            "created_at": edge.created_at,
            "last_activated": edge.last_activated,
            "activation_count": edge.activation_count,
            "decay_rate": edge.decay_rate,
        }

    # ------------------------------------------------------------------
    # Import (round-trip)
    # ------------------------------------------------------------------

    @staticmethod
    def import_into(graph: Graph, source: Path | dict) -> dict[str, int]:
        """
        Import a previously exported JSON-LD document into a graph.

        Nodes and edges are merged (existing IDs are skipped).
        Returns {"nodes_imported", "edges_imported", "nodes_skipped", "edges_skipped"}.
        """
        if isinstance(source, (str, Path)):
            doc = json.loads(Path(source).read_text())
        else:
            doc = source

        base = _BASE
        # Strip base prefix to recover raw IDs
        def _strip(uri: str) -> str:
            for prefix in (f"{base}nodes/", f"{base}edges/"):
                if uri.startswith(prefix):
                    return uri[len(prefix):]
            # Handle custom base URIs
            for segment in ("/nodes/", "/edges/"):
                if segment in uri:
                    return uri.split(segment)[-1]
            return uri

        def _strip_type(t: str) -> str:
            return t.replace("dory:", "").replace("schema:", "")

        nodes_imported = nodes_skipped = edges_imported = edges_skipped = 0

        for node_doc in doc.get("nodes", []):
            node_id = _strip(node_doc["id"])
            if node_id in graph._nodes:
                nodes_skipped += 1
                continue
            try:
                node = Node(
                    id=node_id,
                    type=NodeType(_strip_type(node_doc["type"])),
                    content=node_doc["content"],
                    created_at=node_doc.get("created_at", now_iso()),
                    last_activated=node_doc.get("last_activated", now_iso()),
                    activation_count=node_doc.get("activation_count", 0),
                    salience=node_doc.get("salience", 0.0),
                    is_core=node_doc.get("is_core", False),
                    tags=node_doc.get("tags", []),
                    zone=node_doc.get("zone", ZONE_ACTIVE),
                    superseded_at=node_doc.get("superseded_at"),
                )
                graph._nodes[node.id] = node
                graph._dirty = True
                nodes_imported += 1
            except Exception:
                nodes_skipped += 1

        for edge_doc in doc.get("edges", []):
            edge_id = _strip(edge_doc["id"])
            if edge_id in graph._edges:
                edges_skipped += 1
                continue
            try:
                edge = Edge(
                    id=edge_id,
                    source_id=_strip(edge_doc["source_id"]),
                    target_id=_strip(edge_doc["target_id"]),
                    type=EdgeType(_strip_type(edge_doc["type"])),
                    weight=edge_doc.get("weight", 0.5),
                    created_at=edge_doc.get("created_at", now_iso()),
                    last_activated=edge_doc.get("last_activated", now_iso()),
                    activation_count=edge_doc.get("activation_count", 0),
                    decay_rate=edge_doc.get("decay_rate", 0.02),
                )
                graph._edges[edge.id] = edge
                edges_imported += 1
            except Exception:
                edges_skipped += 1

        if nodes_imported or edges_imported:
            graph.save()

        return {
            "nodes_imported": nodes_imported,
            "nodes_skipped": nodes_skipped,
            "edges_imported": edges_imported,
            "edges_skipped": edges_skipped,
        }
