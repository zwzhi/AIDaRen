"""参考视频与商业素材：上传建档、受控下载与元数据。

- POST /sources：multipart 上传 → 真实 MIME/时长探测 → 私有存储 → cv_media_assets；
- GET /assets/{id}：元数据（不暴露对象键与本地路径）；
- GET /assets/{id}/download：权限校验后的受控下载（404 语义防枚举）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import CvMediaAsset
from app.services.commercial.asset_policy import (
    CommercialAssetPolicyError,
    SOURCE_ROLES,
    ensure_asset_readable,
)
from app.services.commercial.storage import (
    MediaValidationError,
    asset_disk_path,
    new_object_key,
    persist_asset_bytes,
    probe_media_bytes,
)

router = APIRouter()


def _parse_authorized_until(raw: str | None) -> datetime | None:
    if not raw or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="授权截止时间格式无效（需 ISO 8601）") from exc
    return parsed


@router.post(
    "/sources",
    summary="上传参考/自有素材（私有存储）",
    description="文件经真实媒体探测后保存到后端私有目录；返回内部资产 ID，不暴露存储路径。",
)
async def create_source(
    file: UploadFile = File(..., description="媒体文件；按角色校验大小与时长上限"),
    source_role: str = Form(..., description="来源角色，见资产策略（owned_*/reference_source_*）"),
    rights_declaration: str = Form("", description="来源与权利说明（原片须确认有权使用）"),
    authorized_until: str | None = Form(None, description="授权截止时间，ISO 8601；留空表示长期"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if source_role not in SOURCE_ROLES:
        raise HTTPException(status_code=422, detail=f"未知来源角色：{source_role}")
    limit_mb = max(1, int(get_settings().commercial_max_source_file_mb))
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="空文件")
    if len(raw) > limit_mb * 1024 * 1024:
        raise HTTPException(status_code=422, detail=f"文件超过上限 {limit_mb}MB")

    try:
        probe = await probe_media_bytes(raw, file.filename or "", role_is_video=True)
    except MediaValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if probe.kind == "video" and source_role == "reference_source_video":
        max_sec = int(get_settings().commercial_max_reference_duration_seconds)
        if probe.duration_ms is not None and probe.duration_ms > max_sec * 1000:
            raise HTTPException(
                status_code=422,
                detail=f"参考视频时长 {(probe.duration_ms / 1000):.0f}s 超过上限 {max_sec}s，请先裁剪后再上传",
            )

    object_key = new_object_key(source_role, (file.filename or "bin").rsplit(".", 1)[-1])
    persist_asset_bytes(raw, object_key)
    asset = CvMediaAsset(
        team_id=None,  # 首版共享工作区；团队化后由绑定接口回填
        kind=probe.kind,
        object_key=object_key,
        sha256=probe.sha256,
        mime=probe.mime,
        size_bytes=probe.size_bytes,
        width=probe.width,
        height=probe.height,
        duration_ms=probe.duration_ms,
        has_audio=probe.has_audio,
        source_role=source_role,
        rights_declaration=rights_declaration or "",
        authorized_until=_parse_authorized_until(authorized_until),
        uploaded_by=user.id,
    )
    db.add(asset)
    await db.commit()
    return {
        "id": asset.id,
        "kind": asset.kind,
        "source_role": asset.source_role,
        "mime": asset.mime,
        "size_bytes": asset.size_bytes,
        "sha256": asset.sha256,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "has_audio": asset.has_audio,
        "storage": "private",
    }


@router.get("/assets/{asset_id}", summary="素材元数据（脱敏）")
async def get_asset_meta(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset = await db.get(CvMediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        await ensure_asset_readable(db, asset, user.id, is_admin=(user.role == "admin"))
    except CommercialAssetPolicyError:
        raise HTTPException(status_code=404, detail="素材不存在") from None
    return {
        "id": asset.id,
        "kind": asset.kind,
        "source_role": asset.source_role,
        "mime": asset.mime,
        "size_bytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "has_audio": asset.has_audio,
        "rights_status": asset.rights_status,
        "authorized_until": asset.authorized_until.isoformat() if asset.authorized_until else None,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "storage": "private",
    }


@router.get("/assets/{asset_id}/download", summary="受控下载（权限校验）")
async def download_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset = await db.get(CvMediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        await ensure_asset_readable(db, asset, user.id, is_admin=(user.role == "admin"))
    except CommercialAssetPolicyError:
        raise HTTPException(status_code=404, detail="素材不存在") from None
    return FileResponse(
        asset_disk_path(asset.object_key),
        media_type=asset.mime,
        filename=f"asset-{asset.id}.{asset.object_key.rsplit('.', 1)[-1]}",
    )


@router.post("/sources/by-asset/{asset_id}", summary="把已上传的原片资产登记为参考源")
async def register_reference_source(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models_commercial import CvReferenceSource

    asset = await db.get(CvMediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if asset.source_role != "reference_source_video":
        raise HTTPException(status_code=400, detail="仅 reference_source_video 角色可登记为参考源")
    source = CvReferenceSource(
        team_id=None, media_asset_id=asset.id, duration_ms=asset.duration_ms,
        origin_note="页面上传", uploaded_by=user.id, status="probed",
    )
    db.add(source)
    await db.commit()
    return {"source_id": source.id}


@router.post("/sources/{source_id}/analyze", status_code=202, summary="创建解析任务（幂等）")
async def analyze_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对参考视频创建解析任务；Mock 模式即时完成，真实模式要求能力验证。"""
    from app.config import get_settings as _gs
    from app.models_commercial import CvReferenceSource
    from app.services.commercial import mock_provider
    from app.services.commercial.analysis import get_or_create_analysis_run, run_analysis

    source = await db.get(CvReferenceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="参考视频不存在")
    settings = _gs()
    model_id = (settings.gemini_analysis_model_id or "").strip()
    run = await get_or_create_analysis_run(
        db, source=source, model_id=model_id, requested_by=user.id,
    )
    mock = mock_provider.mock_enabled()
    if mock:
        async def analyzer(_request):
            return mock_provider.mock_analyze_payload(source.duration_ms or 30_000)
    else:
        # 真实解析与报价/生成同门：付费总开关 + 双模型 ID + 已验证清单（P1-6）
        from app.services.providers.atlas.client import (
            CapabilityUnverified,
            ProviderNotConfigured,
            resolve_provider_for_commercial_task,
        )

        try:
            resolve_provider_for_commercial_task(require_verified=True)
        except (ProviderNotConfigured, CapabilityUnverified) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        from app.services.providers.atlas.gemini import GeminiAnalysisRequest, analyze_video
        from app.services.commercial.storage import asset_disk_path as _adp

        asset = await db.get(CvMediaAsset, source.media_asset_id)

        async def analyzer(_request):
            request = GeminiAnalysisRequest(
                source_id=source.id, model_id=model_id,
                video_bytes=_adp(asset.object_key).read_bytes(), video_mime=asset.mime,
                source_duration_ms=source.duration_ms or 0,
            )
            result = await analyze_video(
                request, base_url=settings.atlas_base_url, api_key=settings.atlas_api_key,
            )
            return {
                "duration_ms": result.duration_ms,
                "shots": [
                    {"shot_id": s.shot_id, "start_ms": s.start_ms, "end_ms": s.end_ms,
                     "keyframe_hints_ms": s.keyframe_hints_ms, "observation": s.observation,
                     "inference": s.inference, "uncertainty": s.uncertainty}
                    for s in result.shots
                ],
                "transcript": result.transcript, "uncertainties": result.uncertainties,
            }

    run = await run_analysis(db, run=run, analyzer=analyzer)
    await db.commit()
    return {"analysis_run_id": run.id, "status": run.status, "mock": mock,
            "error": run.error}


@router.get("/analyses/{run_id}", summary="查询结构化解析结果")
async def get_analysis(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models_commercial import CvAnalysisRun

    run = await db.get(CvAnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="解析任务不存在")
    return {
        "id": run.id, "status": run.status, "model_id": run.model_id,
        "result": run.result, "error": run.error,
        "cache_key": run.cache_key[:16],
    }
