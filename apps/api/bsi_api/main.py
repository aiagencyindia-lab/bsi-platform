import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from . import problems
from .routers import brands, prompts, runs


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
    ):
        app.include_router(router, prefix="/v1")
    return app


app = create_app()
