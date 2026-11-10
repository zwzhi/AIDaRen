"""商业域核心业务流 REST：作品 → 适配 → 计划 → 报价 → 生成 → 审核 → 合成导出。

权限：登录用户可读；创建/变更限创建者或管理员（首版共享工作区，团队化在 T10）。
Mock：commercial_mock_mode=true 时解析/适配/报价/生成走显著标记的本地模拟，
真实模式在能力未验证时全部拒绝付费执行（不绕过任何保护）。
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
    """真实模式付费门槛：Mock 关闭时，未验证能力直接拒绝（不绕保护）。"""
    settings = get_settings()
    if settings.commercial_mock_mode:
        return
    if not settings.commercial_enabled or not (settings.atlas_api_key or "").strip():
        raise HTTPException(status_code=400, detail="商业域未配置：需要管理员配置 Atlas 密钥并验证能力后才能真实执行")
    verified = {m.strip() for m in (settings.commercial_verified_models or "").split(",") if m.strip()}
    models = {m.strip() for m in (
        settings.gemini_analysis_model_id, settings.h3_developer_reference_model_id,
    ) if m.strip()}
    if models and not models <= verified:
        raise HTTPException(status_code=400, detail="模型能力未通过真实契约验证，付费执行被拒绝（MODEL_CAPABILITY_UNVERIFIED）")


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
                 "published_at": v.published_at.isoformat() if v.published_at else None}
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
    from app.models_commercial import CvProduct

    products = (await db.execute(select(CvProduct).order_by(CvProduct.id.desc()))).scalars().all()
    return {"items": [{"id": p.id, "name": p.name, "current_version": p.current_version} for p in products]}


# ---------------------------------------------------------------- 作品与制作
class ProductionCreateBody(BaseModel):
    template_version_id: int
    actor_version_id: int
    voice_profile_id: int
    product_version_id: int
    target_duration_ms: int = 30_000
    resolution_id: str = "720p"
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


def _build_unit_params(production: CvProduction, unit: dict[str, Any], user_id: int) -> dict:
    """从已确认计划构造该单元的完整生成参数（报价与生成同源）。"""
    actor_version = None  # 延迟加载在调用处
    return {
        "model_id": get_settings().h3_developer_reference_model_id or "minimax-h3-developer-reference",
        "actor_image_asset_ids": [],  # 由 production 的达人版本填充（见下）
        "product_image_asset_ids": [],
        "voice_reference_asset_ids": [],
        "prompt": "按模板镜头描述生成：" + "；".join(unit.get("covered_shot_keys") or []),
        "approved_dialogue": "；".join(
            str(s.get("dialogue") or "") for s in (production.plan_json or {}).get("shots", [])
            if s.get("shot_key") in (unit.get("covered_shot_keys") or [])
        ),
        "resolution_id": production.resolution_id,
        "duration_ms": int(unit.get("request_duration_ms") or 0),
        "aspect_ratio": production.aspect_ratio,
        "audio_required": True,
        "params_version": 1,
        "production_id": production.id,
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
    params = await _enrich_unit_params(db, production, _build_unit_params(production, unit, user.id))
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
    params = await _enrich_unit_params(db, production, _build_unit_params(production, unit, user.id))
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

    # 建 TaskRun（commercial/video_generate）走统一任务平台
    from app.models_tasks import TaskRun

    task = TaskRun(
        domain="commercial", task_type="video_generate", queue_type="video",
        status="pending", requested_by=user.id,
        payload={"attempt_id": approval.attempt_id, "unit_key": body.unit_key},
        next_action_at=None,
    )
    db.add(task)
    await db.flush()
    attempt = await db.get(CvGenerationAttempt, approval.attempt_id)
    if attempt is not None:
        attempt.status = "QUEUED"
    await db.commit()

    drove = False
    if body.drive and mock_provider.mock_enabled():
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
    ledger = (await db.execute(
        select(CvUsageLedger).order_by(CvUsageLedger.id.desc()).limit(50)
    )).scalars().all()
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
            "status": a.status, "prediction_id": a.provider_prediction_id,
            "output_asset_key": a.output_asset_key,
            "error_code": a.error_code, "error_message": a.error_message,
        } for a in attempts],
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


@router.post("/productions/{production_id}/compose", summary="仅合成审核通过镜头")
async def compose(
    production_id: int, body: ComposeBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.services.commercial.compose import build_subtitle_draft, compose_production

    production = await _get_production(db, production_id, user)
    pairs = []
    shots_meta = []
    for selection in body.selections:
        attempt = await db.get(CvGenerationAttempt, selection.attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail=f"attempt {selection.attempt_id} 不存在")
        ranges = [(attempt.output_asset_key or "", int(s), int(e)) for s, e in selection.ranges]
        pairs.append((attempt, ranges))
        for s, e in selection.ranges:
            shots_meta.append({"shot_key": f"attempt{attempt.id}", "dialogue": "", "adopt": (int(s), int(e))})
    try:
        result = await compose_production(db, selections=pairs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    srt_content = None
    if body.subtitles:
        draft = build_subtitle_draft(shots=shots_meta, source_transcript=None)
        lines = []
        for i, item in enumerate(draft, 1):
            def _ts(ms: int) -> str:
                h, r = divmod(ms, 3600000)
                m, r = divmod(r, 60000)
                s, ms2 = divmod(r, 1000)
                return f"{h:02}:{m:02}:{s:02},{ms2:03}"
            lines.append(f"{i}\n{_ts(item['start_ms'])} --> {_ts(item['end_ms'])}\n{item['text']}\n")
        srt_content = "\n".join(lines)

    export = CvExport(
        production_id=production.id, master_path=result.master_path,
        total_adopt_ms=result.total_adopt_ms,
        selections_json={"items": [s.model_dump() for s in body.selections]},
        srt_content=srt_content, created_by=user.id,
    )
    db.add(export)
    production.status = "composed"
    await db.commit()
    return {"export_id": export.id, "master_path": result.master_path,
            "total_adopt_ms": result.total_adopt_ms, "subtitles": bool(srt_content)}


@router.get("/exports/{export_id}/download", summary="下载成片母版")
async def download_export(
    export_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    export = await db.get(CvExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="导出不存在")
    _ensure_writer(export, user)
    from pathlib import Path as _Path

    path = _Path(export.master_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="成片文件缺失")
    return FileResponse(path, media_type="video/mp4", filename=f"export-{export.id}.mp4")


# ---------------------------------------------------------------- 预算（管理）
class BudgetPoolBody(BaseModel):
    total_usd: Decimal


@router.post("/budget", summary="设置测试总预算（管理员）")
async def set_budget(
    body: BudgetPoolBody,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    if (user.role or "user") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    pool = await CvBudgetPool.ensure_default(db, total=body.total_usd, created_by=user.id)
    pool.total_amount = body.total_usd
    await db.commit()
    return {"pool_id": pool.id, "total_usd": str(pool.total_amount),
            "reserved_usd": str(pool.reserved_amount), "settled_usd": str(pool.settled_amount),
            "paused": pool.paused}
