import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from . import problems
from .routers import (
    alerts,
    audits,
    brands,
    citations,
    clusters,
    competitors,
    labels,
    metrics,
    observations,
    ops,
    pages,
    prompts,
    public,
    recommendations,
    reports,
    runs,
    schedules,
    tasks,
)


def create_app() -> FastAPI:
    app = FastAPI(title="BSI Platform API", version="0.1.0")
    problems.install(app)

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for router in (
        brands.router,
        prompts.router,
        runs.router,
        runs.jobs_router,
        observations.router,
        metrics.router,
        schedules.router,
        ops.router,
        labels.router,
        recommendations.router,
        tasks.router,
        citations.router,
        audits.router,
        competitors.router,
        clusters.router,
        pages.router,
        alerts.router,
        reports.router,
        public.router,
    ):
        app.include_router(router, prefix="/v1")
    return app


app = create_app()
