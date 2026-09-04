from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import current_user
from app.models import Template, User
from app.schemas import TemplateCreate, TemplateOut, TemplateUpdate
from story_scraper.templates import iter_templates

router = APIRouter(prefix="/api/templates", tags=["templates"])

BUILTIN_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "templates"


async def _get_owned(db: AsyncSession, user: User, template_id: UUID) -> Template:
    template = await db.get(Template, template_id)
    if template is None or template.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return template


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> list[Template]:
    result = await db.execute(
        select(Template).where(Template.owner_id == user.id).order_by(Template.name)
    )
    return list(result.scalars())


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Template:
    template = Template(owner_id=user.id, **data.model_dump())
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> Template:
    return await _get_owned(db, user, template_id)


@router.put("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: UUID,
    data: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Template:
    template = await _get_owned(db, user, template_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(template, key, value)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> None:
    template = await _get_owned(db, user, template_id)
    await db.delete(template)
    await db.commit()


@router.post("/import", response_model=list[TemplateOut])
async def import_builtin_templates(
    db: AsyncSession = Depends(get_db), user: User = Depends(current_user)
) -> list[Template]:
    existing = await db.execute(select(Template.name).where(Template.owner_id == user.id))
    existing_names = set(existing.scalars())

    created: list[Template] = []
    for name, data in iter_templates(BUILTIN_TEMPLATE_DIR).items():
        if name in existing_names:
            continue
        created.append(
            Template(
                owner_id=user.id,
                name=name,
                container=data.get("container", "div.chapter-content"),
                next_selector=data.get("next", "a#next_chap"),
                detect_title=data.get("detect_title"),
                style=data.get("style", "white-style.css"),
                scripts=data.get("scripts") or [],
                ebook_type=data.get("type", "epub"),
            )
        )
    db.add_all(created)
    await db.commit()
    for template in created:
        await db.refresh(template)
    return created
