from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from backend.storage.models import Base
from backend.storage.db import _connection_string

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = _connection_string()
        # Pin psycopg2: unpinned SQLAlchemy can default to psycopg v3, which
        # Streamlit Cloud doesn't have ("No module named 'psycopg'").
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg2://" + url[len(prefix):]
                break
        _engine = create_engine(url, echo=False)
        Base.metadata.create_all(_engine)  # no-op for tables that already exist
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def db_session() -> Session:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
