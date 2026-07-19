"""오늘의 테니스 FastAPI 진입점.

실행:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.routers import lessons as lessons_router
from app.routers import public as public_router

# ─────────────────────────────────────────────────────────────────────
# 로깅
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=get_settings().LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("tennis-lesson-api")


# ─────────────────────────────────────────────────────────────────────
# FastAPI 인스턴스
# ─────────────────────────────────────────────────────────────────────
settings = get_settings()

app = FastAPI(
    title="오늘의 테니스 API",
    description="Phase 1 MVP — YouTube 레슨 영상을 분석해 3단 오답노트를 생성한다.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────
# 공통 에러 응답 포맷
# ─────────────────────────────────────────────────────────────────────


def _build_error_payload(
    code: str,
    message: str,
    *,
    details: Dict[str, Any] | None = None,
    request_id: str | None = None,
) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    if request_id:
        err["request_id"] = request_id
    return {"error": err}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
    detail = exc.detail
    # 라우터에서 이미 {"error": {...}} 포맷으로 detail을 던진 경우 그대로 사용.
    if isinstance(detail, dict) and "error" in detail:
        body = dict(detail)
        if isinstance(body.get("error"), dict) and "request_id" not in body["error"]:
            body["error"]["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=body)

    # 기본 매핑
    code_by_status = {
        400: "VALIDATION_ERROR",
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "LESSON_NOT_FOUND",
        409: "LESSON_ALREADY_EXISTS",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "UPSTREAM_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_by_status.get(exc.status_code, "INTERNAL_ERROR")
    message = str(detail) if detail else exc.__class__.__name__
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_payload(code, message, request_id=request_id),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_build_error_payload(
            "VALIDATION_ERROR",
            "요청 본문 검증에 실패했습니다.",
            details={"errors": exc.errors()},
            request_id=request_id,
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
    logger.exception("Unhandled error [%s]: %s", request_id, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_build_error_payload(
            "INTERNAL_ERROR",
            "서버 내부 오류가 발생했습니다.",
            request_id=request_id,
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# 라우터 등록
# ─────────────────────────────────────────────────────────────────────
app.include_router(lessons_router.router, prefix="/api/v1")
app.include_router(public_router.router, prefix="/api/v1")


# ─────────────────────────────────────────────────────────────────────
# 헬스체크
# ─────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "version": app.version,
    }


@app.get("/", include_in_schema=False)
def root() -> Dict[str, Any]:
    return {
        "service": settings.APP_NAME,
        "docs": "/docs",
        "health": "/health",
    }
