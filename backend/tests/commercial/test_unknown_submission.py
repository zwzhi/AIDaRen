# -*- coding: utf-8 -*-
"""T07｜提交结果不明与恢复语义（J02/J03）：绝不自动重发收费请求。"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from app.models_commercial import (
    CvBudgetPool,
    CvCostQuote,
    CvGenerationAttempt,
)
from app.services.commercial import generation as gen
import pytest

# T07 单元层用真实适配器路径（关闭 Mock），并携带完整计划参数快照
_PARAMS = {
    "model_id": "minimax-h3-developer-reference",
    "actor_image_asset_ids": [101], "product_image_asset_ids": [201],
    "voice_reference_asset_ids": [301], "prompt": "达人手持商品面向镜头讲解",
    "approved_dialogue": "这款精华质地清爽",
    "resolution_id": "768p", "duration_ms": 6000, "aspect_ratio": "9:16",
    "audio_required": True, "params_version": 1,
}


@pytest.fixture(autouse=True)
def _real_provider_mode(monkeypatch):
    monkeypatch.setattr("app.services.commercial.mock_provider.mock_enabled", lambda: False)
    # 模拟"管理员已完成授权"的真实模式配置（P1-6 后执行前门禁要求全套）
    from app import config

    for name, value in {
        "COMMERCIAL_ENABLED": "true",
        "COMMERCIAL_PAID_EXECUTION_ENABLED": "true",
        "ATLAS_API_KEY": "atlas-test-key-do-not-leak",
        "GEMINI_ANALYSIS_MODEL_ID": "gemini-3-flash-preview",
        "H3_DEVELOPER_REFERENCE_MODEL_ID": "minimax-h3-developer-reference",
        "COMMERCIAL_VERIFIED_MODELS": "gemini-3-flash-preview,minimax-h3-developer-reference",
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def _generation_assets(db_session, owner):
    """提交路径素材交付需要真实 owned_* 资产与文件。"""
    import secrets

    from app.models_commercial import CvMediaAsset
    from app.services.commercial.storage import asset_disk_path

    def _mk(role: str, mime: str, kind: str) -> CvMediaAsset:
        key = f"{role}/t/{secrets.token_hex(6)}.bin"
        asset = CvMediaAsset(
            kind=kind, object_key=key, sha256="f" * 64,
            mime=mime, size_bytes=16, source_role=role, uploaded_by=owner.id,
        )
        db_session.add(asset)
        return asset

    actor = _mk("owned_actor_image", "image/png", "image")
    product = _mk("owned_product_image", "image/png", "image")
    voice = _mk("owned_voice_reference", "audio/mpeg", "audio")
    await db_session.flush()
    for asset in (actor, product, voice):
        path = asset_disk_path(asset.object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"TESTBYTES-0123456789")
    _PARAMS["actor_image_asset_ids"] = [actor.id]
    _PARAMS["product_image_asset_ids"] = [product.id]
    _PARAMS["voice_reference_asset_ids"] = [voice.id]
    yield

from tests.conftest import make_user

_PARAMS = {
    "model_id": "minimax-h3-developer-reference",
    "actor_image_asset_ids": [101], "product_image_asset_ids": [201],
    "voice_reference_asset_ids": [301], "prompt": "达人手持商品面向镜头讲解",
    "approved_dialogue": "台词",
    "resolution_id": "768p", "duration_ms": 6000, "aspect_ratio": "9:16",
    "audio_required": True, "params_version": 1,
}


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


async def _attempt(db, owner, *, status: str = "APPROVED", prediction: str | None = None) -> CvGenerationAttempt:
    await CvBudgetPool.ensure_default(db, total=Decimal("100.00"), created_by=owner.id)
    quote = CvCostQuote(
        quote_key=f"q-{prediction or 'p'}-{owner.id}", model_id="m",
        request_fingerprint="fp", estimated_amount=Decimal("0.05"), currency="USD",
    )
    db.add(quote)
    await db.flush()
    attempt = CvGenerationAttempt(
        client_request_id=f"cr-{quote.id}", payload_hash="fp", quote_id=quote.id,
        status=status, provider_prediction_id=prediction, created_by=owner.id,
        params_json=dict(_PARAMS),
    )
    db.add(attempt)
    await db.flush()
    return attempt


class _Task:
    """轻量 TaskRun 替身（单元层测试不落 task_runs 表）。"""

    def __init__(self, attempt_id: int):
        self.id = 990001
        self.domain = "commercial"
        self.task_type = "video_generate"
        self.payload = {"attempt_id": attempt_id}
        self.provider_task_id = None
        self.status = "running"
        self.cancel_requested = False


# ---------------------------------------------------------------- J02 提交结果不明
@pytest.mark.asyncio
async def test_submit_timeout_marks_unknown_no_resubmit(db_session, owner) -> None:
    """上游收到请求但本地读超时 → SUBMIT_UNKNOWN；再次执行也不得重发。"""
    attempt = await _attempt(db_session, owner)
    submit_calls = []

    def handler(request):
        if "uploadMedia" in request.url.path:
            return httpx.Response(200, json={"id": "media-ok"})
        submit_calls.append(1)
        raise httpx.ReadTimeout("读超时")

    transport = httpx.MockTransport(handler)
    result = await gen.execute_generation_task(
        _Task(attempt.id), db=db_session, base_url="https://api.atlascloud.ai",
        api_key="k", transport=transport,
    )
    await db_session.refresh(attempt)
    assert attempt.status == "SUBMIT_UNKNOWN"
    assert attempt.error_code == "SUBMIT_RESULT_UNKNOWN"
    assert result is None or result.get("failed")

    # “恢复”再跑一次：仍不重发（提交次数保持 1）
    await gen.execute_generation_task(
        _Task(attempt.id), db=db_session, base_url="https://api.atlascloud.ai",
        api_key="k", transport=transport,
    )
    assert len(submit_calls) == 1, "SUBMIT_UNKNOWN 状态下绝不允许再次提交（INV-04）"
    await db_session.refresh(attempt)
    assert attempt.status == "SUBMIT_UNKNOWN"


# ---------------------------------------------------------------- J03 重启恢复只查询
@pytest.mark.asyncio
async def test_recovery_with_prediction_polls_instead_of_submitting(db_session, owner) -> None:
    """提交成功后进程重启：prediction_id 已落库 → 恢复只查询，新增提交次数为 0。"""
    attempt = await _attempt(db_session, owner, status="PROVIDER_RUNNING",
                             prediction="pred-recovered-1")
    submit_calls = []

    def handler(request):
        if "generateVideo" in request.url.path:
            submit_calls.append(1)
            return httpx.Response(200, json={"id": "pred-NEW"})
        return httpx.Response(200, json={"id": "pred-recovered-1", "status": "processing"})

    transport = httpx.MockTransport(handler)
    result = await gen.execute_generation_task(
        _Task(attempt.id), db=db_session, base_url="https://api.atlascloud.ai",
        api_key="k", transport=transport,
    )
    assert len(submit_calls) == 0, "已有上游任务号的恢复路径不得再次提交"
    assert result and result.get("awaiting_poll"), "恢复应转入轮询"


@pytest.mark.asyncio
async def test_prediction_id_persisted_immediately(db_session, owner) -> None:
    """上游 ID 一创建立即落库（下载中断后只拉成片不重新生成）。"""
    attempt = await _attempt(db_session, owner)

    def handler(request):
        return httpx.Response(200, json={"id": "pred-immediate"})

    await gen.execute_generation_task(
        _Task(attempt.id), db=db_session, base_url="https://api.atlascloud.ai",
        api_key="k", transport=httpx.MockTransport(handler),
    )
    await db_session.refresh(attempt)
    assert attempt.provider_prediction_id == "pred-immediate"
    assert attempt.status == "PROVIDER_RUNNING"


# ---------------------------------------------------------------- J06 取消
@pytest.mark.asyncio
async def test_cancel_before_submit_releases_budget(db_session, owner) -> None:
    """未提交即取消：不调用上游，预留释放，attempt CANCELLED。"""
    attempt = await _attempt(db_session, owner)
    submit_calls = []

    def handler(request):
        submit_calls.append(1)
        return httpx.Response(200, json={"id": "pred-x"})

    task = _Task(attempt.id)
    task.cancel_requested = True
    await gen.execute_generation_task(
        task, db=db_session, base_url="https://api.atlascloud.ai",
        api_key="k", transport=httpx.MockTransport(handler),
    )
    assert submit_calls == []
    await db_session.refresh(attempt)
    assert attempt.status == "CANCELLED"
