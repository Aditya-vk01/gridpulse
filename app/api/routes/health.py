from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import ErrorOut

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness check",
    description="Returns 200 while the process is running. Does not touch the database.",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness check",
    description="Returns 200 when the database answers `SELECT 1`, otherwise 503.",
    responses={
        200: {"content": {"application/json": {"example": {"status": "ready"}}}},
        503: {"model": ErrorOut, "description": "Database unavailable"},
    },
)
def ready(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}
