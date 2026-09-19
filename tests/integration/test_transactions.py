import importlib
import pkgutil
import uuid

from bsi_api import routers
from bsi_api.deps import TENANT, Ctx, ctx
from bsi_api.main import create_app
from bsi_core import models as m
from fastapi import APIRouter
from fastapi.testclient import TestClient


def test_commit_failure_is_not_reported_as_success(
    db, make_org, make_brand, owner
):
    app = create_app()

    @app.post("/v1/_probe/{brand_id}")
    def rename_then_break(brand_id: uuid.UUID, c: Ctx = TENANT):
        brand = c.s.get(m.Brand, brand_id)
        brand.name = "Renamed"
        brand.workspace_id = uuid.uuid4()  # FK violation, raised at commit
        return {"ok": True}

    org = make_org()
    bid = make_brand(org, "Original")
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(f"/v1/_probe/{bid}", headers=org.headers)
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/problem+json"
    with owner() as s:
        assert s.get(m.Brand, bid).name == "Original"


def test_every_route_commits_before_responding():
    # A request-scoped session commits after the response is sent, so a
    # failed commit would reach the client as a success.
    def tenant_deps(dependant):
        for dep in dependant.dependencies:
            if dep.call is ctx:
                yield dep
            yield from tenant_deps(dep)

    found = 0
    for module_info in pkgutil.iter_modules(routers.__path__):
        module = importlib.import_module(
            f"{routers.__name__}.{module_info.name}"
        )
        for router in vars(module).values():
            if not isinstance(router, APIRouter):
                continue
            for route in router.routes:
                for dep in tenant_deps(route.dependant):
                    found += 1
                    assert dep.scope == "function", route.path
    assert found >= 20
