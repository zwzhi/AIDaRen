"""商业模板业务域 API。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.commercial import productions, sources, replications

router = APIRouter(tags=["商业短视频模板"])
router.include_router(sources.router)
router.include_router(productions.router)
router.include_router(replications.router)

