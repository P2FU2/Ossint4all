"""Export GraphML do grafo do caso (Maltego / Gephi / yEd)."""

from __future__ import annotations

from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from osint4all.db.repository import graph_payload


def _esc(value: object) -> str:
    return escape(str(value or ""), {'"': "&quot;"})


def render_graphml(session: Session, investigation_id: str) -> str:
    payload = graph_payload(session, investigation_id)
    nodes = payload.get("nodes") or []
    links = payload.get("links") or payload.get("edges") or []
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="type" for="node" attr.name="type" attr.type="string"/>',
        '  <key id="key" for="node" attr.name="key" attr.type="string"/>',
        '  <key id="rel" for="edge" attr.name="rel" attr.type="string"/>',
        '  <graph id="G" edgedefault="directed">',
    ]
    for node in nodes:
        nid = _esc(node.get("id"))
        lines.append(f'    <node id="{nid}">')
        lines.append(f'      <data key="label">{_esc(node.get("label"))}</data>')
        lines.append(f'      <data key="type">{_esc(node.get("type"))}</data>')
        lines.append(f'      <data key="key">{_esc(node.get("key"))}</data>')
        lines.append("    </node>")
    for link in links:
        src = _esc(link.get("source") or link.get("from") or link.get("from_id"))
        dst = _esc(link.get("target") or link.get("to") or link.get("to_id"))
        if not src or not dst:
            continue
        rel = _esc(link.get("type") or link.get("rel") or link.get("rel_type") or "")
        lines.append(f'    <edge source="{src}" target="{dst}">')
        lines.append(f'      <data key="rel">{rel}</data>')
        lines.append("    </edge>")
    lines.append("  </graph>")
    lines.append("</graphml>")
    return "\n".join(lines) + "\n"
