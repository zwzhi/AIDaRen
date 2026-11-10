# -*- coding: utf-8 -*-
"""T07｜输出下载与查询退避（J04/J05）：下载失败只重试下载。"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from app.models_commercial import CvBudgetPool, CvCostQuote, CvGenerationAttempt
from app.services.commercial import generation as gen
import pytest

# T07 单元层用真实适配器路径（关闭 Mock），并携带完整计划参数快照
_PARAMS = {
    "model_id": "minimax-h3-developer-reference",
    "actor_image_asset_ids": [101], "product_image_asset_ids": [201],
    "voice_reference_asset_ids": [301], "prompt": "达人手持商品面向镜头讲解",
    "approved_dialogue": "这款精华质地清爽",
    "resolution_id": "720p", "duration_ms": 6000, "aspect_ratio": "9:16",
    "audio_required": True, "params_version": 1,
}


@pytest.fixture(autouse=True)
def _real_provider_mode(monkeypatch):
    monkeypatch.setattr("app.services.commercial.mock_provider.mock_enabled", lambda: False)


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


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


async def _attempt(db, owner, *, prediction: str) -> CvGenerationAttempt:
    await CvBudgetPool.ensure_default(db, total=Decimal("100.00"), created_by=owner.id)
    quote = CvCostQuote(
        quote_key=f"q-{prediction}-{owner.id}", model_id="m", request_fingerprint="fp",
        estimated_amount=Decimal("0.05"), currency="USD",
    )
    db.add(quote)
    await db.flush()
    attempt = CvGenerationAttempt(
        client_request_id=f"cr-{quote.id}", payload_hash="fp", quote_id=quote.id,
        status="PROVIDER_RUNNING", provider_prediction_id=prediction, created_by=owner.id,
        params_json=dict(_PARAMS),
    )
    db.add(attempt)
    await db.flush()
    return attempt


@pytest.mark.asyncio
async def test_poll_error_backs_off_without_failing(db_session, owner) -> None:
    """J04：查询 429/网络错误 → 退避续查，不创建新视频不判死。"""
    attempt = await _attempt(db_session, owner, prediction="pred-429")
    polls = []

    def handler(request):
        polls.append(request.url.path)
        return httpx.Response(429, json={"error": "rate limited"})

    result = await gen.poll_attempt(
        attempt, db=db_session, base_url="https://api.atlascloud.ai",
        api_key="k", transport=httpx.MockTransport(handler),
    )
    await db_session.refresh(attempt)
    assert attempt.status == "PROVIDER_RUNNING"  # 未判死
    assert result.get("retry_poll") is True       # 继续按退避查询


@pytest.mark.asyncio
async def test_download_failure_only_retries_download(db_session, owner, tmp_path) -> None:
    """J05：生成成功下载中断 → 保留上游任务号进入待下载；下一轮只下载不重新生成。"""
    attempt = await _attempt(db_session, owner, prediction="pred-dl")
    state = {"phase": "download-fail", "generates": 0}

    def handler(request):
        path = request.url.path
        if "prediction" in path:
            if state["phase"] == "download-fail":
                return httpx.Response(200, json={
                    "id": "pred-dl", "status": "succeeded",
                    "output": ["https://example.com/out.mp4"],
                })
            state["generates"] += 1
            return httpx.Response(200, json={"id": "pred-dl", "status": "succeeded"})
        if "generateVideo" in path:
            state["generates"] += 1  # 不应发生
            return httpx.Response(200, json={"id": "pred-NEW"})
        # 输出文件下载第一次失败
        if state["phase"] == "download-fail":
            state["phase"] = "download-ok"
            return httpx.Response(500, text="cdn boom")
        return httpx.Response(200, content=b"FAKEVIDEO")

    transport = httpx.MockTransport(handler)
    # 第一次：下载失败 → OUTPUT_PENDING_DOWNLOAD（不重新生成）
    await gen.poll_attempt(attempt, db=db_session, base_url="https://api.atlascloud.ai",
                           api_key="k", transport=transport)
    await db_session.refresh(attempt)
    assert attempt.status == "OUTPUT_PENDING_DOWNLOAD"
    assert attempt.provider_prediction_id == "pred-dl"

    # 第二次：仅重新下载成功 → GENERATED；generateVideo 从未被调用
    await gen.poll_attempt(attempt, db=db_session, base_url="https://api.atlascloud.ai",
                           api_key="k", transport=transport)
    await db_session.refresh(attempt)
    assert attempt.status == "GENERATED"
    assert state["generates"] == 0, "下载重试阶段绝不允许再次生成"
    # 输出登记为资产
    assert attempt.output_asset_key, "下载完成后应登记输出资产"


@pytest.mark.asyncio
async def test_generated_not_equal_approved(db_session, owner) -> None:
    """ GENERATED≠审核通过：生成完成只落 GENERATED 状态。"""
    attempt = await _attempt(db_session, owner, prediction="pred-ok")

    def handler(request):
        if "prediction" in request.url.path:
            return httpx.Response(200, json={
                "id": "pred-ok", "status": "succeeded",
                "output": ["https://example.com/ok.mp4"],
            })
        return httpx.Response(200, content=b"FAKEVIDEO")

    await gen.poll_attempt(attempt, db=db_session, base_url="https://api.atlascloud.ai",
                           api_key="k", transport=httpx.MockTransport(handler))
    await db_session.refresh(attempt)
    assert attempt.status == "GENERATED"
