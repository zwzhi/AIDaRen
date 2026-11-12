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



@router.get("/wardrobes/{wardrobe_id}")
async def get_wardrobe_detail(wardrobe_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """服饰详情：完整版本列表（含图集、颜色、材质、权利状态）。"""
    from sqlalchemy import select
    from app.models_commercial_v2 import CvWardrobeItem, CvWardrobeVersion

    item = await db.get(CvWardrobeItem, wardrobe_id)
    if item is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="服饰不存在")
    versions = (await db.execute(
        select(CvWardrobeVersion).where(CvWardrobeVersion.item_id == wardrobe_id)
        .order_by(CvWardrobeVersion.version.desc())
    )).scalars().all()
    return {
        "id": item.id, "name": item.name, "category": item.category,
        "scope": item.scope, "status": item.status,
        "versions": [{
            "id": v.id, "version": v.version, "color": v.color,
            "material": v.material, "description": v.description,
            "asset_ids": v.asset_ids or [], "rights_status": v.rights_status,
            "status": v.status,
        } for v in versions],
    }


class WardrobeGenerateBody(BaseModel):
    mode: str = "text-to-image"  # text-to-image | image-to-image
    prompt: str = ""
    base_version_id: int | None = None


@router.post("/wardrobes/{wardrobe_id}/generate")
async def generate_wardrobe_image(
    wardrobe_id: int, body: WardrobeGenerateBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """服饰 AI 生图（文生图/图生图）。当前为 Mock 模式生成占位图。"""
    from fastapi import HTTPException
    from app.models_commercial_v2 import CvWardrobeItem

    item = await db.get(CvWardrobeItem, wardrobe_id)
    if item is None:
        raise HTTPException(status_code=404, detail="服饰不存在")
    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="请输入描述")
    if body.mode not in ("text-to-image", "image-to-image"):
        raise HTTPException(status_code=422, detail="mode 仅支持 text-to-image / image-to-image")

    # Mock：生成纯色占位图（正式版接入 Flare/Sunburst）
    from app.services.commercial.mock_provider import mock_enabled
    if not mock_enabled():
        raise HTTPException(status_code=503, detail="真实生图未联调（BLOCKED）")

    import secrets as _sec
    from PIL import Image as PILImage
    from app.services.commercial.storage import commercial_storage_root, new_object_key
    from app.models_commercial import CvMediaAsset

    # 生成 512x512 纯色图
    colors = [(255, 200, 200), (200, 255, 200), (200, 200, 255), (255, 255, 200), (255, 200, 255)]
    rgb = colors[hash(body.prompt) % len(colors)]
    img = PILImage.new("RGB", (512, 512), rgb)
    key = new_object_key("owned_wardrobe_image", "png")
    path = commercial_storage_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), "PNG")

    import hashlib
    raw = path.read_bytes()
    asset = CvMediaAsset(
        kind="image", object_key=key, sha256=hashlib.sha256(raw).hexdigest(),
        mime="image/png", size_bytes=len(raw), width=512, height=512,
        source_role="owned_wardrobe_image", uploaded_by=user.id,
    )
    db.add(asset)
    await db.flush()

    # 追加到最新版本（或创建 V1）
    from app.models_commercial_v2 import CvWardrobeVersion
    latest = (await db.execute(
        __import__("sqlalchemy").select(CvWardrobeVersion)
        .where(CvWardrobeVersion.item_id == wardrobe_id)
        .order_by(CvWardrobeVersion.version.desc()).limit(1)
    )).scalar_one_or_none()
    if latest:
        ids = list(latest.asset_ids or [])
        ids.append(asset.id)
        latest.asset_ids = ids
        latest.status = "draft"  # 重新进入草稿待审核
    await db.commit()

    return {"asset_id": asset.id, "message": "Mock 生图完成（正式版接入 Flare）", "mock": True}
