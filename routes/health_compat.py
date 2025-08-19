# routes/health_compat.py
from __future__ import annotations
import os
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])

class BasicStatus(BaseModel):
    status: str = Field("ok", examples=["ok"])
    version: str = Field(..., examples=["2.14.3"])

@router.get("/health", response_model=BasicStatus, operation_id="getBasicHealth")
def health() -> BasicStatus:
    return BasicStatus(status="ok", version=os.getenv("ALGOGPT_VERSION", "unknown"))

