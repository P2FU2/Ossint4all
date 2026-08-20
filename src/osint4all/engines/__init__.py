"""Cinco motores do dossiê profissional."""

from osint4all.engines.discovery import capability_registry, extract_document_facts, route_connectors
from osint4all.engines.intelligence import anomalies, communities, shortest_path
from osint4all.engines.investigation import gap_analysis, hypothesis_board
from osint4all.engines.playbooks import TEMPLATES, attach_playbook
from osint4all.engines.verification import quality_score

ENGINES = (
    ("DISCOVERY", "Encontra evidências e registra a consulta."),
    ("KNOWLEDGE", "Entende entidades, versões e relações."),
    ("VERIFICATION", "Testa se a conclusão é sustentável."),
    ("INVESTIGATION", "Organiza hipóteses, playbooks e workflow."),
    ("INTELLIGENCE", "Mostra padrões que o investigador pode não ter visto."),
)

__all__ = [
    "ENGINES",
    "TEMPLATES",
    "anomalies",
    "attach_playbook",
    "capability_registry",
    "communities",
    "extract_document_facts",
    "gap_analysis",
    "hypothesis_board",
    "quality_score",
    "route_connectors",
    "shortest_path",
]
