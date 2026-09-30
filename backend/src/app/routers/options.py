from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.models import User
from app.schemas import OptionsOut
from story_scraper.config import EBOOK_TYPES, asset_names

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("", response_model=OptionsOut)
async def get_options(user: User = Depends(current_user)) -> OptionsOut:
    """The values a template or job may name for the settings that are chosen
    from a fixed list, so the UI can offer exactly those."""
    return OptionsOut(
        ebook_types=list(EBOOK_TYPES),
        styles=asset_names("styles"),
        scripts=asset_names("scripts"),
    )
