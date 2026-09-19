"""RFC 9457 problem+json errors."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class Problem(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str = "",
        errors: list[Any] | None = None,
    ) -> None:
        self.status, self.title = status, title
        self.detail, self.errors = detail, errors or []


def _response(
    request: Request,
    status: int,
    title: str,
    detail: str = "",
    errors: list[Any] | None = None,
) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers={"X-Request-Id": rid},
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "request_id": rid,
            "errors": errors or [],
        },
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return _response(request, exc.status, exc.title, exc.detail, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _invalid(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"loc": e["loc"], "msg": e["msg"]}
            for e in jsonable_encoder(exc.errors())
        ]
        return _response(request, 422, "Validation failed", errors=errors)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        return _response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception) -> JSONResponse:
        return _response(request, 500, "Internal error")
