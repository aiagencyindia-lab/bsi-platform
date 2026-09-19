import os

_T = "postgresql+psycopg://{u}:{p}@localhost:5433/bsi_test"
os.environ["DATABASE_URL"] = _T.format(u="bsi_app", p="app")
os.environ["OWNER_DATABASE_URL"] = _T.format(u="bsi_owner", p="owner")
os.environ["RAW_STORE_DIR"] = "./data/test"

import hashlib
import secrets
import uuid
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from bsi_core import models as m
from bsi_core.db import owner_engine
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def _migrated():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def db(_migrated):
    with owner_engine().begin() as c:
        c.execute(text("TRUNCATE organization CASCADE"))


@pytest.fixture
def owner(db):
    """Owner session factory: bypasses RLS, for arranging test data."""
    return lambda: Session(owner_engine(), expire_on_commit=False)


@pytest.fixture
def make_org(owner):
    def _make(name: str = "Org A") -> SimpleNamespace:
        token = "bsi_" + secrets.token_hex(32)
        with owner() as s, s.begin():
            org = m.Organization(name=name)
            s.add(org)
            s.flush()
            ws = m.Workspace(org_id=org.id, name="Default")
            s.add(ws)
            s.flush()
            s.add(
                m.ApiKey(
                    org_id=org.id,
                    workspace_id=ws.id,
                    hashed_key=hashlib.sha256(token.encode()).hexdigest(),
                )
            )
        return SimpleNamespace(
            id=org.id,
            workspace_id=ws.id,
            token=token,
            headers={"Authorization": f"Bearer {token}"},
        )

    return _make


@pytest.fixture
def make_brand(owner):
    def _make(org, name: str = "Acme", aliases=()) -> uuid.UUID:
        with owner() as s, s.begin():
            b = m.Brand(
                org_id=org.id,
                workspace_id=org.workspace_id,
                name=name,
                aliases=list(aliases),
            )
            s.add(b)
            s.flush()
            s.add(
                m.Locale(
                    org_id=org.id, brand_id=b.id, country="IN", language="en"
                )
            )
        return b.id

    return _make
