"""商业域核心业务流 REST：作品 → 适配 → 计划 → 报价 → 生成 → 审核 → 合成导出。

权限：登录用户可读；创建/变更限创建者或管理员（首版共享工作区，团队化在 T10）。
Mock：commercial_mock_mode=true 时解析/适配/报价/生成走显著标记的本地模拟，
真实模式在能力未验证时全部拒绝付费执行（不绕过任何保护）。
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import (
    CvActorVersion,
    CvBudgetPool,
    CvCostQuote,
    CvExport,
    CvGenerationAttempt,
    CvMediaAsset,
    CvProductVersion,
    CvProduction,
    CvReview,
    CvTemplateVersion,
    CvUsageLedger,
    CvVoiceProfile,
)
from app.services.commercial import mock_provider
from app.services.commercial.actors import VoiceBindingError, validate_voice_binding
from app.services.commercial.adaptation import AdaptationError, adapt_template
from app.services.commercial.budget_service import (
    BudgetError,
    IdempotencyConflict,
    approve_and_reserve,
    request_quote,
)
from app.services.commercial.generation import execute_generation_task, poll_commercial_task
from app.services.commercial.generation_request import RequestBuildError
from app.services.commercial.planning import (
    DialoguePacingError,
    PlanningError,
    compile_generation_units,
)
from app.services.commercial.template_service import TemplatePublishError, publish_template
from app.services.providers.atlas.h3_reference import DRAFT_H3_CAPABILITIES

router = APIRouter()


def _ensure_writer(obj, user: User) -> None:
    if (user.role or "user") == "admin":
        return
    if getattr(obj, "created_by", None) != user.id and getattr(obj, "uploaded_by", None) != user.id:
        raise HTTPException(status_code=403, detail="无权修改该资源")


async def _get_production(db: AsyncSession, production_id: int, user: User) -> CvProduction:
    production = await db.get(CvProduction, production_id)
    if production is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    _ensure_writer(production, user)
    return production


def _require_mock_or_verified() -> None:
    """真实模式付费门槛：统一走 resolve_provider(require_verified=True)。

    三层要求（任一不满足即 400，绝不回落占位模型）：
    商业域启用 + Atlas 密钥 + 付费执行总开关开启
    + 两个模型角色精确 ID 均已配置 + 均在管理员验证清单内。
    Mock 模式不受影响；已提交任务的查询/下载恢复不经过此门（见 generation）。
    """
    settings = get_settings()
    if settings.commercial_mock_mode:
        return
    from app.services.providers.atlas.client import (
        CapabilityUnverified,
        ProviderNotConfigured,
        resolve_provider_for_commercial_task,
    )

    try:
        resolve_provider_for_commercial_task(require_verified=True)
    except (ProviderNotConfigured, CapabilityUnverified) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/capabilities", summary="当前生成能力档案（前端选项唯一来源）")
async def get_capabilities(
    user: User = Depends(get_current_user),
):
    """分辨率/画幅/时长选项由能力档案驱动（P1-1），前端不得硬编码默认值。

    capability_verified=False 表示档案仍是 DRAFT（未经真实契约验证），
    页面不得声称真实模型能力已验证。
    """
    caps = DRAFT_H3_CAPABILITIES
    return {
        "duration_min_ms": caps.duration_min_ms,
        "duration_max_ms": caps.duration_max_ms,
        "duration_step_ms": caps.duration_step_ms,
        "resolutions": sorted(caps.resolutions),
        "aspect_ratios": sorted(caps.aspect_ratios),
        "audio_supported": caps.audio_supported,
        "voice_reference_supported": caps.voice_reference_supported,
        "capability_verified": caps.capability_verified,
        "capability_version": caps.capability_version,
    }


# ---------------------------------------------------------------- 模板
class TemplateCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    analysis_run_id: int
    shots: list[dict[str, Any]]  # 人工校准后的分镜结构


class TemplatePublishBody(BaseModel):
    expected_version: int
    structure: dict[str, Any]


@router.post("/templates", summary="从解析结果创建模板草稿")
async def create_template(
    body: TemplateCreateBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models_commercial import CvAnalysisRun, CvTemplate

    run = await db.get(CvAnalysisRun, body.analysis_run_id)
    if run is None or run.status != "completed":
        raise HTTPException(status_code=400, detail="解析未完成，无法建模板")
    template = CvTemplate(name=body.name, created_by=user.id)
    db.add(template)
    await db.flush()
    version = await publish_template(
        db, template=template, draft_payload={
            "shots": body.shots,
            "variables": ["opening_question", "approved_core_claim", "closing_cta"],
        },
        expected_version=1, publisher_id=user.id, analysis_run_id=run.id,
    )
    await db.commit()
    return {"template_id": template.id, "version_id": version.id, "version": 1}


@router.get("/templates", summary="模板列表（含版本）")
async def list_templates(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models_commercial import CvTemplate, CvTemplateVersion

    templates = (await db.execute(
        select(CvTemplate).where(CvTemplate.archived.is_(False)).order_by(CvTemplate.id.desc())
    )).scalars().all()
    out = []
    for template in templates:
        versions = (await db.execute(
            select(CvTemplateVersion).where(CvTemplateVersion.template_id == template.id)
            .order_by(CvTemplateVersion.version.desc())
        )).scalars().all()
        out.append({
            "id": template.id, "name": template.name,
            "current_version": template.current_version,
            "versions": [
                {"id": v.id, "version": v.version, "status": v.status,
                 "published_at": v.published_at.isoformat() if v.published_at else None,
                 # 卡片展示用的结构统计（从冻结快照计算，不改模板语义）
                 "shot_count": len((v.structure_json or {}).get("shots") or []),
                 "total_duration_ms": sum(
                     max(0, int(s.get("end_ms") or 0) - int(s.get("start_ms") or 0))
                     for s in (v.structure_json or {}).get("shots") or []),
                 "variables": list((v.structure_json or {}).get("variables") or []),
                }
                for v in versions
            ],
        })
    return {"items": out}


# ---------------------------------------------------------------- 达人/商品
class ActorCreateBody(BaseModel):
    name: str
    image_asset_ids: list[int] = Field(default_factory=list)
    appearance_desc: str = ""


class VoiceBindBody(BaseModel):
    audio_asset_id: int
    authorized_until: str | None = None


@router.post("/actors", summary="创建达人并发布 V1 形象")
async def create_actor(
    body: ActorCreateBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models_commercial import CvActor, CvActorVersion

    actor = CvActor(name=body.name, created_by=user.id)
    db.add(actor)
    await db.flush()
    version = CvActorVersion(
        actor_id=actor.id, version=1, status="published",
        image_asset_ids=body.image_asset_ids,
        appearance_desc=body.appearance_desc, published_by=user.id,
    )
    db.add(version)
    actor.current_version = 1
    await db.commit()
    return {"actor_id": actor.id, "actor_version_id": version.id}


@router.post("/actors/{actor_id}/voices", summary="绑定授权音色")
async def bind_voice(
    actor_id: int, body: VoiceBindBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from datetime import datetime

    from app.models_commercial import CvActor, CvVoiceProfile

    actor = await db.get(CvActor, actor_id)
    if actor is None:
        raise HTTPException(status_code=404, detail="达人不存在")
    _ensure_writer(actor, user)
    asset = await db.get(CvMediaAsset, body.audio_asset_id)
    if asset is None or asset.source_role != "owned_voice_reference":
        raise HTTPException(status_code=400, detail="音色样本必须来自已上传的授权音色素材")
    voice = CvVoiceProfile(
        actor_id=actor.id, audio_asset_id=asset.id,
        authorized_until=datetime.fromisoformat(body.authorized_until) if body.authorized_until else None,
    )
    db.add(voice)
    await db.commit()
    return {"voice_profile_id": voice.id}


@router.get("/actors", summary="达人列表")
async def list_actors(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models_commercial import CvActor, CvActorVersion, CvVoiceProfile

    actors = (await db.execute(select(CvActor).order_by(CvActor.id.desc()))).scalars().all()
    out = []
    for actor in actors:
        versions = (await db.execute(
            select(CvActorVersion).where(CvActorVersion.actor_id == actor.id)
            .order_by(CvActorVersion.version.desc())
        )).scalars().all()
        voices = (await db.execute(
            select(CvVoiceProfile).where(CvVoiceProfile.actor_id == actor.id)
        )).scalars().all()
        out.append({
            "id": actor.id, "name": actor.name, "current_version": actor.current_version,
            "versions": [{"id": v.id, "version": v.version, "image_asset_ids": v.image_asset_ids or []} for v in versions],
            "voices": [{"id": vo.id, "audio_asset_id": vo.audio_asset_id,
                        "authorized_until": vo.authorized_until.isoformat() if vo.authorized_until else None,
                        "status": vo.status} for vo in voices],
        })
    return {"items": out}


class ProductCreateBody(BaseModel):
    name: str
    form: str = ""
    specs_text: str = ""
    image_asset_ids: list[int] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)


@router.post("/products", summary="创建商品并发布 V1")
async def create_product(
    body: ProductCreateBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models_commercial import CvProduct, CvProductVersion

    product = CvProduct(name=body.name, created_by=user.id)
    db.add(product)
    await db.flush()
    version = CvProductVersion(
        product_id=product.id, version=1, form=body.form, specs_text=body.specs_text,
        image_asset_ids=body.image_asset_ids, claims=body.claims,
        forbidden_phrases=body.forbidden_phrases, allowed_actions=body.allowed_actions,
        published_by=user.id,
    )
    db.add(version)
    product.current_version = 1
    await db.commit()
    return {"product_id": product.id, "product_version_id": version.id}


@router.get("/products", summary="商品列表")
async def list_products(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.models_commercial import CvProduct, CvProductVersion

    products = (await db.execute(select(CvProduct).order_by(CvProduct.id.desc()))).scalars().all()
    out = []
    for p in products:
        latest = (await db.execute(
            select(CvProductVersion.id).where(CvProductVersion.product_id == p.id)
            .order_by(CvProductVersion.version.desc()).limit(1)
        )).scalar_one_or_none()
        # latest_version_id 是创建作品要引用的版本行 ID；
        # current_version 仅是版本号（多个商品会重复，不能当作 ID 使用）
        out.append({"id": p.id, "name": p.name, "current_version": p.current_version,
                    "latest_version_id": latest})
    return {"items": out}


# ---------------------------------------------------------------- 作品与制作
class ProductionCreateBody(BaseModel):
    template_version_id: int
    actor_version_id: int
    voice_profile_id: int
    product_version_id: int
    target_duration_ms: int = 30_000
    resolution_id: str = "768p"
    aspect_ratio: str = "9:16"
    marketing_goal: str = ""
    allow_cross_actor_voice: bool = False
    dialogue_locked: bool = True
    locked_dialogue: dict[str, str] | None = None


@router.post("/productions", summary="从模板与素材创建作品")
async def create_production(
    body: ProductionCreateBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    actor_version = await db.get(CvActorVersion, body.actor_version_id)
    voice = await db.get(CvVoiceProfile, body.voice_profile_id)
    if actor_version is None or voice is None:
        raise HTTPException(status_code=400, detail="达人版本或音色不存在")
    try:
        validate_voice_binding(actor_version, voice, allow_cross_actor=body.allow_cross_actor_voice)
    except VoiceBindingError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    production = CvProduction(
        template_version_id=body.template_version_id,
        actor_version_id=body.actor_version_id,
        voice_profile_id=body.voice_profile_id,
        product_version_id=body.product_version_id,
        allow_cross_actor_voice=body.allow_cross_actor_voice,
        dialogue_locked=body.dialogue_locked,
        locked_dialogue=body.locked_dialogue,
        marketing_goal=body.marketing_goal,
        target_duration_ms=body.target_duration_ms,
        resolution_id=body.resolution_id,
        aspect_ratio=body.aspect_ratio,
        created_by=user.id,
    )
    db.add(production)
    await db.commit()
    return {"production_id": production.id, "status": production.status}


class AdaptBody(BaseModel):
    marketing_goal: str = ""


@router.post("/productions/{production_id}/adapt", summary="文案适配（模板文本+我方素材）")
async def adapt_production(
    production_id: int, body: AdaptBody | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    production = await _get_production(db, production_id, user)
    _require_mock_or_verified()
    template_version = await db.get(CvTemplateVersion, production.template_version_id)
    product = await db.get(CvProductVersion, production.product_version_id)
    goal = (body.marketing_goal if body and body.marketing_goal else production.marketing_goal) or "种草推荐"

    if mock_provider.mock_enabled():
        async def adaptor(request: dict) -> dict:
            claims = request["product"]["claims"]
            actions = request["product"]["allowed_actions"]
            template_shots = request["template"]["shots"]
            locked = request.get("user_locked_dialogue") or {}
            return {"shots": [
                {
                    "shot_key": s["shot_key"],
                    "dialogue": locked.get(s["shot_key"]) or (
                        claims[i % len(claims)]["text"] if claims else "（请先审核商品卖点）"
                    ),
                    "action": actions[0] if actions else "手持展示",
                } for i, s in enumerate(template_shots)
            ], "pending_review": [], "mock": True}
    else:
        async def adaptor(request: dict) -> dict:  # 真实 Gemini 文本适配（待联调）
            raise HTTPException(status_code=503, detail="真实文案适配未联调（BLOCKED）：等待能力验证与预算")

    try:
        draft = await adapt_template(
            db, template_version_id=production.template_version_id, product=product,
            marketing_goal=goal,
            user_locked_dialogue=(production.locked_dialogue if production.dialogue_locked else None),
            adaptor=adaptor,
        )
    except AdaptationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    production.plan_json = {"shots": draft["shots"], "pending_review": draft["pending_review"],
                            "units": None}
    production.status = "adapted"
    await db.commit()
    return {"production_id": production.id, "shots": draft["shots"],
            "pending_review": draft["pending_review"],
            "dialogue_locked": draft["dialogue_locked"], "mock": mock_provider.mock_enabled()}


@router.post("/productions/{production_id}/plan", summary="编译生成单元（三时长分离）")
async def plan_production(
    production_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    production = await _get_production(db, production_id, user)
    plan = dict(production.plan_json or {})
    shots = plan.get("shots") or []
    if not shots:
        raise HTTPException(status_code=400, detail="请先完成文案适配")
    try:
        units = compile_generation_units(shots, DRAFT_H3_CAPABILITIES)
    except DialoguePacingError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except PlanningError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    plan["units"] = [u.as_plan_dict() for u in units]
    plan["capabilities"] = {
        "duration_min_ms": DRAFT_H3_CAPABILITIES.duration_min_ms,
        "duration_max_ms": DRAFT_H3_CAPABILITIES.duration_max_ms,
        "resolutions": sorted(DRAFT_H3_CAPABILITIES.resolutions),
        "capability_verified": DRAFT_H3_CAPABILITIES.capability_verified,
    }
    production.plan_json = plan
    production.status = "planned"
    await db.commit()
    return {"production_id": production.id, "units": plan["units"],
            "capabilities": plan["capabilities"]}


def _build_unit_params(production: CvProduction, unit: dict[str, Any], user_id: int,
                       dialogue_override: str = "") -> dict:
    """从已确认计划构造该单元的完整生成参数（报价与生成同源）。

    dialogue_override（P1-8）：单镜重做时用户修改后的台词——进入参数快照
    与报价指纹；与原计划台词不同 → 旧报价/旧批准自动失效（QUOTE_CHANGED）。
    """
    actor_version = None  # 延迟加载在调用处
    planned_dialogue = "；".join(
        str(s.get("dialogue") or "") for s in (production.plan_json or {}).get("shots", [])
        if s.get("shot_key") in (unit.get("covered_shot_keys") or [])
    )
    return {
        "model_id": (get_settings().h3_developer_reference_model_id or "").strip(),
        "actor_image_asset_ids": [],  # 由 production 的达人版本填充（见下）
        "product_image_asset_ids": [],
        "voice_reference_asset_ids": [],
        "prompt": "按模板镜头描述生成：" + "；".join(unit.get("covered_shot_keys") or []),
        "approved_dialogue": (dialogue_override or "").strip() or planned_dialogue,
        "resolution_id": production.resolution_id,
        "duration_ms": int(unit.get("request_duration_ms") or 0),
        "aspect_ratio": production.aspect_ratio,
        "audio_required": True,
        "params_version": 1,
        "production_id": production.id,
        "unit_key": unit.get("unit_key") or "",
        "team_id": None,
        "attempt_id": "",
    }


async def _enrich_unit_params(db: AsyncSession, production: CvProduction, params: dict) -> dict:
    """把达人/商品/音色的素材资产 ID 填入参数（生成素材策略校验在交付层执行）。"""
    actor_version = await db.get(CvActorVersion, production.actor_version_id)
    product = await db.get(CvProductVersion, production.product_version_id)
    voice = await db.get(CvVoiceProfile, production.voice_profile_id)
    params["actor_image_asset_ids"] = list(actor_version.image_asset_ids or [])
    params["product_image_asset_ids"] = list(product.image_asset_ids or [])
    params["voice_reference_asset_ids"] = [voice.audio_asset_id]
    return params


class QuoteBody(BaseModel):
    unit_key: str
    dialogue_override: str = Field(default="", max_length=2000,
                                   description="单镜重做的修改台词；非空时进入参数快照与报价指纹")


@router.post("/productions/{production_id}/quote", summary="对指定生成单元报价")
async def quote_unit(
    production_id: int, body: QuoteBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    production = await _get_production(db, production_id, user)
    _require_mock_or_verified()
    plan = dict(production.plan_json or {})
    units = plan.get("units") or []
    unit = next((u for u in units if u.get("unit_key") == body.unit_key), None)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"生成单元不存在：{body.unit_key}")
    params = await _enrich_unit_params(
        db, production, _build_unit_params(production, unit, user.id, body.dialogue_override))
    try:
        quote = await request_quote(
            db, params=params,
            base_url=get_settings().atlas_base_url, api_key=(get_settings().atlas_api_key or ""),
        )
        await db.commit()  # 报价必须落库，生成请求才能跨会话引用
    except RequestBuildError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return {
        "quote_id": quote.id, "quote_key": quote.quote_key,
        "amount": str(quote.estimated_amount), "currency": quote.currency,
        "is_estimated": quote.is_estimated, "price_source": quote.price_source,
        "expires_at": quote.expires_at.isoformat() if quote.expires_at else None,
        "duration_ms": quote.requested_duration_ms, "resolution_id": quote.resolution_id,
        "mock": mock_provider.mock_enabled(),
    }


class GenerateBody(BaseModel):
    unit_key: str
    quote_id: int
    client_request_id: str = Field(min_length=8, max_length=128)
    drive: bool = True  # Mock 模式下同步驱动任务（真实模式忽略，交给调度器）
    dialogue_override: str = Field(default="", max_length=2000,
                                   description="必须与报价时一致；不一致按 QUOTE_CHANGED 拒绝")


@router.post("/productions/{production_id}/generate", status_code=202, summary="确认预算并提交生成")
async def generate_unit(
    production_id: int, body: GenerateBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    production = await _get_production(db, production_id, user)
    _require_mock_or_verified()
    plan = dict(production.plan_json or {})
    unit = next((u for u in plan.get("units") or [] if u.get("unit_key") == body.unit_key), None)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"生成单元不存在：{body.unit_key}")
    quote = await db.get(CvCostQuote, body.quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="报价不存在")
    params = await _enrich_unit_params(
        db, production, _build_unit_params(production, unit, user.id, body.dialogue_override))
    try:
        approval = await approve_and_reserve(
            db, quote=quote, params=params, client_request_id=body.client_request_id,
            created_by=user.id, production_id=production.id,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BudgetError as exc:
        code_map = {"BUDGET_EXCEEDED": 402, "QUOTE_EXPIRED": 409, "QUOTE_CHANGED": 409}
        raise HTTPException(status_code=code_map.get(exc.code, 400), detail=exc.message) from exc
    await db.commit()

    # 建/复用 TaskRun（commercial/video_generate）走统一任务平台。
    # 幂等重放（P1-2）：返回原 attempt 的原任务，不重复建任务、不重复驱动、
    # 不重复计费；仅在崩溃窗口（预留已落但任务未建）补建一个恢复任务。
    # next_action_at 必须置为当前时间——调度器只认领"非空且已到期"的
    # pending 任务（scheduler._claim_queue），留 None 将永不被执行（P1-4）
    from datetime import UTC, datetime

    from app.models_tasks import TaskRun

    async def _find_existing_task(attempt_id: int) -> TaskRun | None:
        rows = (await db.execute(
            select(TaskRun).where(
                TaskRun.domain == "commercial",
                TaskRun.task_type == "video_generate",
                TaskRun.payload["attempt_id"].as_integer() == attempt_id,
            ).order_by(TaskRun.id.desc()).limit(1)
        )).scalars().first()
        return rows

    task_replayed = False
    task = None
    if approval.idempotent_replay:
        task = await _find_existing_task(approval.attempt_id)
        if task is not None:
            task_replayed = True
    if task is None:
        task = TaskRun(
            domain="commercial", task_type="video_generate", queue_type="video",
            status="pending", requested_by=user.id,
            payload={"attempt_id": approval.attempt_id, "unit_key": body.unit_key},
            next_action_at=datetime.now(UTC),
        )
        db.add(task)
        await db.flush()
        attempt = await db.get(CvGenerationAttempt, approval.attempt_id)
        if attempt is not None:
            attempt.status = "QUEUED"
        await db.commit()

    drove = False
    if body.drive and mock_provider.mock_enabled() and not task_replayed:
        # 开发模式同步驱动（真实 handler + 真实轮询函数，仅 Mock 供应商）
        task.status = "running"
        await db.commit()
        result = await execute_generation_task(
            task, db=db, base_url=get_settings().atlas_base_url,
            api_key=(get_settings().atlas_api_key or ""),
        )
        if isinstance(result, dict) and result.get("awaiting_poll"):
            task.status = "awaiting_poll"
            await db.commit()
            await poll_commercial_task(int(task.id), db=db)
        elif isinstance(result, dict) and result.get("failed"):
            task.status = "failed"
            task.error_message = str(result.get("error"))
            await db.commit()
        drove = True

    attempt = await db.get(CvGenerationAttempt, approval.attempt_id)
    return {
        "attempt_id": approval.attempt_id, "task_id": task.id,
        "idempotent_replay": approval.idempotent_replay,
        "task_replayed": task_replayed,
        "attempt_status": attempt.status if attempt else None,
        "prediction_id": attempt.provider_prediction_id if attempt else None,
        "mock": mock_provider.mock_enabled(), "drove": drove,
    }


@router.get("/productions/{production_id}", summary="作品详情（计划/单元/尝试/费用）")
async def get_production(
    production_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    production = await db.get(CvProduction, production_id)
    if production is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    attempts = (await db.execute(
        select(CvGenerationAttempt).where(CvGenerationAttempt.production_id == production.id)
        .order_by(CvGenerationAttempt.id)
    )).scalars().all()
    # 费用只聚合本作品的 attempt（attempt_ref = attempt.id）
    own_attempt_ids = [a.id for a in attempts]
    ledger = (await db.execute(
        select(CvUsageLedger).where(CvUsageLedger.attempt_ref.in_(
            [str(i) for i in own_attempt_ids] or ["-1"])
        ).order_by(CvUsageLedger.id.desc())
    )).scalars().all() if own_attempt_ids else []
    latest_export = (await db.execute(
        select(CvExport).where(CvExport.production_id == production.id)
        .order_by(CvExport.id.desc()).limit(1)
    )).scalar_one_or_none()
    total_usd = sum((e.amount for e in ledger if e.currency == "USD"), Decimal("0"))
    pending = sum((e.amount for e in ledger if e.settlement_status == "SETTLEMENT_PENDING"), Decimal("0"))
    return {
        "id": production.id, "status": production.status,
        "dialogue_locked": production.dialogue_locked,
        "target_duration_ms": production.target_duration_ms,
        "resolution_id": production.resolution_id, "aspect_ratio": production.aspect_ratio,
        "plan": production.plan_json,
        "attempts": [{
            "id": a.id, "client_request_id": a.client_request_id,
            "attempt_no": a.attempt_no,
            "unit_key": (a.params_json or {}).get("unit_key"),
            "status": a.status, "prediction_id": a.provider_prediction_id,
            "output_asset_key": a.output_asset_key,
            "error_code": a.error_code, "error_message": a.error_message,
        } for a in attempts],
        "latest_export": ({"id": latest_export.id, "kind": latest_export.kind or "master"}
                          if latest_export else None),
        "costs": {
            "total_usd": str(total_usd), "pending_usd": str(pending),
            "settlement_note": "待结算金额为估算（真实账单以联调后对账为准）",
            "mock": mock_provider.mock_enabled(),
        },
    }


# ---------------------------------------------------------------- 审核
class ReviewBody(BaseModel):
    dimensions: dict[str, str | list[str]]  # {"台词": ["FAIL", "原因"]} 或 "PASS"
    speech_required: bool = True


@router.post("/attempts/{attempt_id}/review", summary="逐镜审核（八维）")
async def review_attempt(
    attempt_id: int, body: ReviewBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.services.commercial.review_service import record_review

    attempt = await db.get(CvGenerationAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="生成尝试不存在")
    _ensure_writer(attempt, user)
    normalized: dict[str, object] = {}
    for dim, verdict in body.dimensions.items():
        normalized[dim] = tuple(verdict) if isinstance(verdict, list) else verdict
    decision = await record_review(
        db, attempt, reviewer_id=user.id, dimensions=normalized,
        speech_required=body.speech_required,
    )
    await db.commit()  # 审核结果必须落库（追加历史 + 状态推进）
    return {"attempt_id": attempt.id, "overall": decision.overall}


# ---------------------------------------------------------------- 合成与导出
class ComposeSelection(BaseModel):
    attempt_id: int
    ranges: list[list[int]]  # [[start_ms, end_ms], ...]


class ComposeBody(BaseModel):
    selections: list[ComposeSelection]
    subtitles: bool = True
    complete: bool = True  # true=完整成片（必需单元必须全部合格）；false=部分预览


def _plan_units(production: CvProduction) -> list[dict[str, Any]]:
    return (production.plan_json or {}).get("units") or []


async def _validate_compose_selection(
    db: AsyncSession, production: CvProduction, attempt: CvGenerationAttempt,
) -> str:
    """单条 selection 的归属与参数版本校验（P1-3/P2-1）。

    返回错误说明；通过返回空串。attempt 必须属于本作品、对应计划中的
    必需单元且参数版本与冻结计划一致——其他作品的合格 attempt 不能凑数，
    旧参数版本的产物也不能冒充当前计划。
    """
    if attempt.production_id != production.id:
        return (f"attempt {attempt.id} 不属于作品 {production.id}，不能进入本作品合成")
    unit_key = (attempt.params_json or {}).get("unit_key") or ""
    unit = next((u for u in _plan_units(production) if u.get("unit_key") == unit_key), None)
    if unit is None:
        return (f"attempt {attempt.id} 缺少与当前计划匹配的 unit_key（历史数据需先补映射，"
                "不会按数量猜测放行）")
    attempt_version = int((attempt.params_json or {}).get("params_version") or 0)
    plan_version = int(unit.get("params_version") or 0)
    if plan_version and attempt_version and attempt_version != plan_version:
        return (f"attempt {attempt.id}（参数版本 v{attempt_version}）与计划单元 "
                f"{unit_key}（v{plan_version}）不一致，请重做后再合成")
    return ""


async def _unit_coverage_error(
    db: AsyncSession, production: CvProduction,
    *, selected_attempts: list[CvGenerationAttempt] | None = None,
) -> str | None:
    """严格逐单元校验（P1-3）：完整成片要求每个必需 unit_key 都有明确映射。

    - 以「本作品 REVIEW_APPROVED attempt 的 unit_key」为覆盖依据；
    - selected_attempts 提供时以「用户明确选中的 attempt」为覆盖依据
      （多次重做的合格版本只覆盖自己的单元，不能顶替其他镜头）；
    - 无 unit_key 的历史 attempt 不计入覆盖（进入待处理，不按数量猜全）。
    """
    units = _plan_units(production)
    if not units:
        return "制作计划缺少生成单元，请先完成适配与计划"
    if selected_attempts is None:
        attempts = (await db.execute(
            select(CvGenerationAttempt).where(
                CvGenerationAttempt.production_id == production.id,
                CvGenerationAttempt.status == "REVIEW_APPROVED",
            )
        )).scalars().all()
    else:
        attempts = selected_attempts
    covered_unit_keys = {
        unit_key for unit_key in (
            (a.params_json or {}).get("unit_key") for a in attempts
        ) if unit_key
    }
    missing = [u["unit_key"] for u in units if u.get("unit_key") not in covered_unit_keys]
    return "、".join(missing) if missing else None


@router.post("/productions/{production_id}/compose", summary="合成（完整成片需全部必需单元合格）")
async def compose(
    production_id: int, body: ComposeBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.services.commercial.compose import build_subtitle_draft, compose_production

    production = await _get_production(db, production_id, user)
    pairs = []
    shots_meta = []
    timeline_cursor = 0  # 成片全局时间轴（秒表从 0 起拼接）
    for selection in body.selections:
        attempt = await db.get(CvGenerationAttempt, selection.attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail=f"attempt {selection.attempt_id} 不存在")
        # 归属/单元映射/参数版本校验（P1-3/P2-1：其他作品合格 attempt 不能凑数）
        problem = await _validate_compose_selection(db, production, attempt)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        ranges = [(attempt.output_asset_key or "", int(s), int(e)) for s, e in selection.ranges]
        pairs.append((attempt, ranges))
        # 字幕草稿文本：来自本次选中 attempt 的定稿台词快照（重做后即新台词），
        # 不使用原片旧台词/时间码；多采用区间按分隔符对齐，无法对齐时首段承载整段。
        # 必须逐 selection 构建（每段各自的时间轴累加），不得在循环外合并。
        dialogue_full = str((attempt.params_json or {}).get("approved_dialogue") or "")
        pieces = dialogue_full.split("；") if dialogue_full else []
        for idx, (s, e) in enumerate(selection.ranges):
            text = pieces[idx] if idx < len(pieces) else (dialogue_full if idx == 0 else "")
            # 字幕时间码对齐成片全局时间轴（拼接后的绝对区间），非单元内相对区间
            span = max(0, int(e) - int(s))
            shots_meta.append({"shot_key": f"attempt{attempt.id}", "dialogue": text.strip(),
                               "adopt": (timeline_cursor, timeline_cursor + span)})
            timeline_cursor += span
    # 完整成片：必需单元缺「明确选中」的合格版本 → 服务端阻断（严格逐单元，
    # 不按数量回退；多次重做的合格版本只覆盖自身单元，不得顶替其他镜头）
    if body.complete:
        selected = [attempt for attempt, _ranges in pairs]
        missing = await _unit_coverage_error(db, production, selected_attempts=selected)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"以下必需生成单元没有审核合格的版本，不能导出完整成片：{missing}。"
                       "请先重做并审核通过，或选择部分预览导出（将明确标记为部分预览）。",
            )
    try:
        result = await compose_production(db, selections=pairs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    srt_content = None
    if body.subtitles:
        draft = build_subtitle_draft(shots=shots_meta, source_transcript=None)
        lines = []
        numbered = [item for item in draft if item.get("text")]  # 空台词不生成字幕条目
        for i, item in enumerate(numbered, 1):
            def _ts(ms: int) -> str:
                h, r = divmod(ms, 3600000)
                m, r = divmod(r, 60000)
                s, ms2 = divmod(r, 1000)
                return f"{h:02}:{m:02}:{s:02},{ms2:03}"
            lines.append(f"{i}\n{_ts(item['start_ms'])} --> {_ts(item['end_ms'])}\n{item['text']}\n")
        srt_content = "\n".join(lines)

    kind = "master" if body.complete else "partial_preview"
    export = CvExport(
        production_id=production.id, kind=kind, master_path=result.master_path,
        total_adopt_ms=result.total_adopt_ms,
        selections_json={
            "items": [s.model_dump() for s in body.selections],
            "plan_units": (production.plan_json or {}).get("units") or [],
            "complete": body.complete,
        },
        srt_content=srt_content, created_by=user.id,
    )
    db.add(export)
    if body.complete:
        production.status = "composed"
    else:
        production.status = production.status if production.status == "composed" else "partial_preview"
    await db.commit()
    return {"export_id": export.id, "master_path": result.master_path,
            "total_adopt_ms": result.total_adopt_ms, "subtitles": bool(srt_content),
            "kind": kind}


@router.get("/exports/{export_id}", summary="导出详情（含字幕草稿/类型/烧录版）")
async def get_export(
    export_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    export = await db.get(CvExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    _ensure_writer(export, user)
    return {
        "id": export.id, "production_id": export.production_id,
        "kind": export.kind or "master",
        "total_adopt_ms": export.total_adopt_ms,
        "srt_content": export.srt_content,
        "srt_aligned": False,  # 草稿默认未对齐，需人工校对后烧录
        "subtitled_path": export.subtitled_path,
        "selections": export.selections_json,
        "created_at": export.created_at.isoformat() if export.created_at else None,
    }


class BurnBody(BaseModel):
    srt_content: str = ""  # 空则使用已存草稿


@router.post("/exports/{export_id}/burn", summary="烧录字幕（生成独立烧录版，不改母版）")
async def burn_export(
    export_id: int, body: BurnBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.services.commercial.compose import burn_subtitles

    export = await db.get(CvExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    _ensure_writer(export, user)
    srt = (body.srt_content or "").strip() or (export.srt_content or "")
    if not srt.strip():
        raise HTTPException(status_code=422, detail="没有可烧录的字幕内容（请先校对字幕草稿）")
    import tempfile
    from pathlib import Path as _Path

    # srt 放到输出同目录（避免临时目录中文/空格路径再叠加转义负担）
    srt_dir = _Path(export.master_path).parent
    srt_file = srt_dir / f"export-{export.id}-subtitle.srt"
    srt_file.write_text(srt, encoding="utf-8")
    srt_path = str(srt_file)
    try:
        target = await asyncio.get_event_loop().run_in_executor(
            None, burn_subtitles, export.master_path, srt_path,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"烧录失败（只重跑后期，不触发生成）：{exc}") from exc
    finally:
        pass  # srt 留档于导出目录，便于复现烧录参数
    export.subtitled_path = target
    await db.commit()
    return {"export_id": export.id, "subtitled_path": target, "master_immutable": True}


@router.get("/exports/{export_id}/download", summary="下载成片（母版或烧录版）")
async def download_export(
    export_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    request: Request = None,
):
    export = await db.get(CvExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    _ensure_writer(export, user)
    from pathlib import Path as _Path

    variant = "subtitled" if (request.query_params.get("variant") == "subtitled") else "master"
    raw_path = export.subtitled_path if variant == "subtitled" else export.master_path
    if not raw_path:
        raise HTTPException(status_code=404, detail="烧录版尚未生成（请先烧录字幕）")
    path = _Path(raw_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="成片文件缺失")
    suffix = "-subtitled" if variant == "subtitled" else ""
    return FileResponse(path, media_type="video/mp4", filename=f"export-{export.id}{suffix}.mp4")


# ---------------------------------------------------------------- 预算（管理）
class BudgetPoolBody(BaseModel):
    total_usd: Decimal
    scope: str = "mock"  # mock=演示预算；real=真实付费授权（互不继承）


@router.post("/budget", summary="设置测试总预算（管理员）")
async def set_budget(
    body: BudgetPoolBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    if (user.role or "user") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if body.scope not in ("mock", "real"):
        raise HTTPException(status_code=422, detail="scope 仅支持 mock/real")
    pool = await CvBudgetPool.ensure_default(
        db, total=body.total_usd, created_by=user.id, scope=body.scope,
    )
    pool.total_amount = body.total_usd
    await db.commit()
    return {"pool_id": pool.id, "total_usd": str(pool.total_amount),
            "reserved_usd": str(pool.reserved_amount), "settled_usd": str(pool.settled_amount),
            "paused": pool.paused}
