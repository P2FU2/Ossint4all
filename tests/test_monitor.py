from sqlalchemy import select

from osint4all.db.models import ExpansionJob, Investigation
from osint4all.db.session import session_scope
from osint4all.graph.monitor import requeue_monitored_seeds
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed


def test_requeue_only_monitored(settings) -> None:
    seed = parse_seed("Maria Silva Souza")
    assert seed
    with session_scope() as session:
        create_investigation(
            session,
            title="off",
            hypothesis=None,
            seeds=[seed],
            connectors=[],
            max_depth=1,
            monitor=False,
            created_by="t",
        )
        create_investigation(
            session,
            title="on",
            hypothesis=None,
            seeds=[seed],
            connectors=[],
            max_depth=1,
            monitor=True,
            created_by="t",
        )
    assert requeue_monitored_seeds() == 0
    with session_scope() as session:
        jobs = session.scalars(select(ExpansionJob)).all()
        assert len(jobs) == 2
        pending = [job for job in jobs if job.status == "PENDING"]
        assert len(pending) == 2
    with session_scope() as session:
        inv = session.scalar(select(Investigation).where(Investigation.monitor.is_(True)))
        assert inv
        for job in session.scalars(select(ExpansionJob).where(ExpansionJob.investigation_id == inv.id)):
            job.status = "DONE"
    assert requeue_monitored_seeds() == 1
    assert requeue_monitored_seeds() == 0
    with session_scope() as session:
        jobs = session.scalars(select(ExpansionJob)).all()
        assert len(jobs) == 3
