from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial_v2 import CvWardrobeItem, CvWardrobeVersion

router = APIRouter()


class WardrobeCreateBody(BaseModel):
    name: str
    category: str = "other"
    scope: str = "personal"
    team_id: int | None = None


class WardrobeVersionBody(BaseModel):
    asset_ids: list[int] = Field(default_factory=list)
    color: str = ""
    material: str = ""
    description: str = ""


@router.get("/wardrobes")
async def list_wardrobes(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(select(CvWardrobeItem).order_by(CvWardrobeItem.id.desc()))).scalars().all()
    items = [row for row in rows if row.created_by == user.id or user.role == "admin" or (row.scope == "team" and row.team_id)]
    out = []
    for item in items:
        versions = (await db.execute(select(CvWardrobeVersion).where(CvWardrobeVersion.item_id == item.id).order_by(CvWardrobeVersion.version.desc()))).scalars().all()
        out.append({"id": item.id, "name": item.name, "category": item.category, "scope": item.scope, "status": item.status, "versions": [{"id": v.id, "version": v.version, "asset_ids": v.asset_ids or [], "color": v.color, "material": v.material, "description": v.description, "status": v.status} for v in versions]})
    return {"items": out}


@router.post("/wardrobes")
async def create_wardrobe(body: WardrobeCreateBody, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if body.scope not in {"personal", "team", "project"}:
        raise HTTPException(status_code=422, detail="服饰共享范围无效")
    item = CvWardrobeItem(name=body.name, category=body.category, scope=body.scope, team_id=body.team_id, created_by=user.id)
    db.add(item)
    await db.flush()
    await db.commit()
    return {"id": item.id, "status": item.status}


@router.post("/wardrobes/{wardrobe_id}/versions")
async def create_wardrobe_version(wardrobe_id: int, body: WardrobeVersionBody, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await db.get(CvWardrobeItem, wardrobe_id)
    if item is None or (user.role != "admin" and item.created_by != user.id):
        raise HTTPException(status_code=404, detail="服饰不存在")
    latest = (await db.execute(select(CvWardrobeVersion).where(CvWardrobeVersion.item_id == item.id).order_by(CvWardrobeVersion.version.desc()).limit(1))).scalar_one_or_none()
    version = CvWardrobeVersion(item_id=item.id, version=(latest.version + 1 if latest else 1), asset_ids=body.asset_ids, color=body.color, material=body.material, description=body.description, rights_status="pending", status="draft")
    db.add(version)
    item.status = "draft"
    await db.commit()
    return {"wardrobe_id": item.id, "wardrobe_version_id": version.id, "version": version.version}

