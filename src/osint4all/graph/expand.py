"""Motor de expansão: conectores → grafo → fila."""

from __future__ import annotations

from osint4all.config import Settings, get_settings
from osint4all.connectors.base import Connector, ExpandContext
from osint4all.connectors.registry import build_connectors
from osint4all.db.models import Entity, ExpansionJob, Investigation
from osint4all.db.repository import claim_next_job, utcnow
from osint4all.db.session import session_scope
from osint4all.exceptions import SkippedDisabled
from osint4all.graph.resolve import apply_result
from osint4all.logging_setup import get_logger

logger = get_logger(__name__)

PROBE_CONNECTORS = {
    "EMAIL": frozenset({"email_public", "web_search", "username_public", "google_public"}),
    "USERNAME": frozenset({"username_public", "web_search", "google_public"}),
    "PHONE": frozenset({"phone_public", "web_search"}),
    "NAME": frozenset({"socio_search", "web_search", "wikidata", "tse", "google_public"}),
    "CPF": frozenset({"socio_search", "tse", "transparencia", "web_search"}),
    "CNPJ": frozenset({"cnpj_receita", "opencorporates", "socio_search"}),
    "COMPANIES": frozenset({"socio_search", "cnpj_receita", "opencorporates"}),
    "QSA": frozenset({"cnpj_receita", "socio_search"}),
}


def connectors_for_kinds(kinds: list[str] | tuple[str, ...] | None) -> set[str] | None:
    if not kinds:
        return None
    wanted: set[str] = set()
    for kind in kinds:
        wanted |= PROBE_CONNECTORS.get(str(kind or "").upper(), set())
    return wanted


class ExpansionEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        connectors: list[Connector] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.connectors = connectors if connectors is not None else build_connectors(self.settings)

    def expand_entity(self, investigation: Investigation, entity: Entity, *, depth: int) -> int:
        from sqlalchemy.orm import object_session

        enabled = set(investigation.connectors or [])
        from osint4all.db.repository import case_target_profile

        session = object_session(entity)
        if session is None:
            raise RuntimeError("entity precisa estar ligado a uma Session")
        ctx = ExpandContext(
            investigation=investigation,
            settings=self.settings,
            enabled=enabled,
            profile=case_target_profile(session, investigation.id),
        )
        applied = 0
        scoped = connectors_for_kinds(list((entity.attrs or {}).get("probe_kinds") or []))
        for connector in self.connectors:
            if enabled and connector.name not in enabled:
                continue
            if scoped is not None and connector.name not in scoped:
                continue
            if not connector.accepts(entity):
                continue
            import time

            started = time.perf_counter()
            try:
                result = connector.collect(entity, ctx)
            except SkippedDisabled as exc:
                logger.info("connector_skipped %s %s", connector.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("connector_failed %s: %s", connector.name, exc)
                from osint4all.engines.discovery import log_query

                log_query(
                    session,
                    investigation,
                    connector=connector.name,
                    entity_id=entity.id,
                    params={"key": entity.canonical_key, "type": entity.entity_type, "error": str(exc)[:200]},
                    result_count=0,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    version=getattr(connector, "version", "1"),
                    failed=True,
                )
                continue
            from osint4all.engines.discovery import log_query

            count = len(result.entities) + len(result.evidence)
            log_query(
                session,
                investigation,
                connector=connector.name,
                entity_id=entity.id,
                params={"key": entity.canonical_key, "type": entity.entity_type},
                result_count=count,
                latency_ms=int((time.perf_counter() - started) * 1000),
                version=getattr(connector, "version", "1"),
            )
            apply_result(
                session,
                investigation,
                entity,
                result,
                connector=connector.name,
                depth=depth,
                enqueue_children=True,
                max_attempts=self.settings.job_max_attempts,
            )
            applied += 1
        attrs = dict(entity.attrs or {})
        if "probe_kinds" in attrs:
            attrs.pop("probe_kinds", None)
            entity.attrs = attrs
        entity.last_seen_at = utcnow()
        return applied

    def run_job(self, session, job: ExpansionJob) -> None:
        investigation = session.get(Investigation, job.investigation_id)
        entity = session.get(Entity, job.entity_id)
        if not investigation or not entity:
            job.status = "FAILED"
            job.last_error = "investigação ou entidade ausente"
            job.finished_at = utcnow()
            return
        try:
            self.expand_entity(investigation, entity, depth=job.depth)
            job.status = "DONE"
            job.last_error = None
        except Exception as exc:  # noqa: BLE001
            job.last_error = str(exc)[:1000]
            if job.attempt_count >= job.max_attempts:
                job.status = "FAILED"
            else:
                job.status = "PENDING"
        job.finished_at = utcnow()


def process_pending_jobs(
    *,
    investigation_id: str | None = None,
    limit: int = 25,
    settings: Settings | None = None,
    engine: ExpansionEngine | None = None,
) -> int:
    """Consome até `limit` jobs. Usado pelo worker e pela UI (EXPAND_SYNC)."""
    settings = settings or get_settings()
    engine = engine or ExpansionEngine(settings)
    processed = 0
    for _ in range(limit):
        with session_scope() as session:
            job = claim_next_job(session, investigation_id=investigation_id)
            if not job:
                break
            engine.run_job(session, job)
            processed += 1
    return processed
