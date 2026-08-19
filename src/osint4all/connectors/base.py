"""Contrato dos conectores e DTOs de resultado."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from osint4all.config import Settings
from osint4all.db.models import Entity, Investigation


@dataclass
class FoundEntity:
    entity_type: str
    kind: str
    value: str
    display_name: str
    attrs: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.6


@dataclass
class FoundEdge:
    from_ref: str
    to_ref: str
    rel_type: str
    confidence: float = 0.6
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FoundEvidence:
    source_label: str
    url: str | None = None
    snippet: str | None = None
    payload: dict[str, Any] | None = None
    entity_ref: str | None = None


@dataclass
class ConnectorResult:
    entities: list[FoundEntity] = field(default_factory=list)
    edges: list[FoundEdge] = field(default_factory=list)
    evidence: list[FoundEvidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def merge(self, other: ConnectorResult) -> ConnectorResult:
        self.entities.extend(other.entities)
        self.edges.extend(other.edges)
        self.evidence.extend(other.evidence)
        self.notes.extend(other.notes)
        return self


@dataclass
class ExpandContext:
    investigation: Investigation
    settings: Settings
    enabled: set[str]


class Connector(Protocol):
    name: str

    def accepts(self, entity: Entity) -> bool: ...

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult: ...

    def health(self) -> dict[str, Any]: ...
