"""Content-gap clusters (PRD F11)."""

import uuid
from typing import Any

from bsi_core.gaps import clusters, unlabelled
from bsi_core.metrics import Filters
from fastapi import APIRouter, Depends

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import ClustersOut
from .metrics import filters

router = APIRouter(prefix="/brands/{brand_id}", tags=["clusters"])


@router.get("/clusters/gaps", response_model=ClustersOut)
def list_gap_clusters(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return {
        "unlabelled": unlabelled(c.s, brand_id),
        "clusters": clusters(c.s, brand_id, f),
    }
