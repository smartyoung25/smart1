from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class BaseResponse(BaseModel):
    farm_id: str
    updated_at: datetime
    data_quality: str = "FINETUNED"   # FINETUNED | TRANSFER | SIMULATION | LITERATURE
    confidence_80pct: Optional[dict[str, float]] = None  # {"lower": x, "upper": y}
