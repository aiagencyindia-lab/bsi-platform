"""Citation intelligence: which domains the engine cites for the brand."""

import uuid
from typing import Any

from bsi_core.citations import sources
from bsi_core.metrics import Filters
from fastapi import APIRouter, Depends

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import SourceOut
from .metrics import filters

router = APIRouter(prefix="/brands/{brand_id}", tags=["citations"])


@router.get("/citations", response_model=list[SourceOut])
def list_citations(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    return sources(c.s, brand_id, f)
