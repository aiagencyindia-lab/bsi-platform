"""Sessions. Application code must use tenant_session()."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from .config import get_settings


@lru_cache
def app_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def owner_engine() -> Engine:
    """Migrations, seed and tests only. Bypasses RLS."""
    return create_engine(get_settings().owner_database_url)


@contextmanager
def tenant_session(org_id: uuid.UUID) -> Iterator[Session]:
    # Objects stay readable after commit: API responses are built from them
    # once the transaction has closed.
    with Session(app_engine(), expire_on_commit=False) as s, s.begin():
        s.execute(
            text("SELECT set_config('app.org_id', :o, true)"),
            {"o": str(org_id)},
        )
        yield s


@contextmanager
def system_session() -> Iterator[Session]:
    """No tenant: sees no rows. Only for the SECURITY DEFINER functions."""
    with Session(app_engine()) as s, s.begin():
        yield s
