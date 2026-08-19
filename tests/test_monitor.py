from sqlalchemy import select

from osint4all.db.models import ExpansionJob
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
    queued = requeue_monitored_seeds()
    assert queued == 1
    with session_scope() as session:
        jobs = session.scalars(select(ExpansionJob)).all()
        assert len(jobs) >= 3
