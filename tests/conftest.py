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
def make_observation(owner):
    from datetime import UTC, datetime

    from bsi_core.storage import LocalRawStore
    from sqlalchemy import select

    def _make(
        org,
        brand_id,
        raw=None,
        status="fetched",
        text="best shoes",
        prompt_id=None,  # reuse a prompt: pass a new sample_index with it
        sample_index=0,
    ):
        slot = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        with owner() as s, s.begin():
            locale = s.scalars(
                select(m.Locale).where(m.Locale.brand_id == brand_id)
            ).first()
            engine = s.scalars(select(m.Engine)).first()
            if prompt_id is None:
                prompt = m.Prompt(
                    org_id=org.id,
                    brand_id=brand_id,
                    locale_id=locale.id,
                    text=text,
                )
                s.add(prompt)
                s.flush()
                prompt_id = prompt.id
            job = s.scalars(
                select(m.Job).where(m.Job.brand_id == brand_id)
            ).first()
            if job is None:
                job = m.Job(
                    org_id=org.id, brand_id=brand_id, scheduled_slot=slot
                )
                s.add(job)
                s.flush()
            obs = m.Observation(
                org_id=org.id,
                brand_id=brand_id,
                job_id=job.id,
                prompt_id=prompt_id,
                engine_id=engine.id,
                locale_id=locale.id,
                sample_index=sample_index,
                scheduled_slot=slot,
                status=status,
            )
            s.add(obs)
            s.flush()
            if raw is not None:
                obs.raw_uri = LocalRawStore().put(org.id, obs.id, raw)
        return obs.id

    return _make


@pytest.fixture
def client(db):
    from bsi_api.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app(), raise_server_exceptions=False)


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
