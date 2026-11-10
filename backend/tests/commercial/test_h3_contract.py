# -*- coding: utf-8 -*-
"""T03｜H3 Developer Reference 契约测试（Fixture 驱动；真实联调 BLOCKED）。

锁定 §8.4 不变量：参考视频字段禁入、声音未绑定即拒绝、分辨率不受支持
即拒绝、上游错误体不得判成功。
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.schemas_commercial import GenerationInputError, VideoGenerationInput
from app.services.providers.atlas.h3_reference import (
    DRAFT_H3_CAPABILITIES,
    ProviderRequestError,
    build_h3_request,
    map_prediction,
    poll_prediction,
    submit_generation,
    validate_request,
)
from app.services.providers.atlas.pricing import (
    ProviderRequestError as PricingError,
    quote_generation,
)

BASE = "https://api.atlascloud.ai"


def _input(**overrides) -> VideoGenerationInput:
    params = dict(
        team_id=None, production_id=1, generation_unit_id=10, attempt_id="att-1",
        model_id="minimax-h3-developer-reference",
        actor_image_asset_ids=(101,), product_image_asset_ids=(201,),
        voice_reference_asset_ids=(301,),
        prompt="达人手持商品面向镜头讲解", approved_dialogue="这款精华质地清爽",
        resolution_id="720p", duration_ms=6_000, aspect_ratio="9:16",
        audio_required=True,
    )
    params.update(overrides)
    return VideoGenerationInput(**params)


# ---------------------------------------------------------------- INV-01 与输入校验
def test_source_video_fields_rejected() -> None:
    """内部输入层禁止出现原片字段（INV-01）。"""
    base = _input().__dict__
    for banned in ("source_video_url", "source_frame_url", "source_video_id"):
        with pytest.raises(TypeError):
            VideoGenerationInput(**base, **{banned: "https://evil/x.mp4"})


def test_missing_voice_binding_rejected() -> None:
    with pytest.raises(GenerationInputError) as exc:
        _input(voice_reference_asset_ids=())
    assert exc.value.code == "VOICE_BINDING_INVALID"


def test_unsupported_resolution_rejected() -> None:
    with pytest.raises(GenerationInputError) as exc:
        build_h3_request(_input(resolution_id="2160p"), DRAFT_H3_CAPABILITIES)
    assert exc.value.code == "PROVIDER_RESOLUTION_UNSUPPORTED"


def test_unsupported_duration_rejected() -> None:
    with pytest.raises(GenerationInputError):
        build_h3_request(_input(duration_ms=90_000), DRAFT_H3_CAPABILITIES)  # 90s 非法单次
    with pytest.raises(GenerationInputError):
        build_h3_request(_input(duration_ms=2_000), DRAFT_H3_CAPABILITIES)   # 2s 低于最小 5s


def test_request_body_has_no_source_reference() -> None:
    body = build_h3_request(_input(), DRAFT_H3_CAPABILITIES)
    serialized = str(body)
    assert "source_video" not in serialized and "source_frame" not in serialized
    assert body["duration_ms"] == 6_000 and body["resolution"] == "720p"


# ---------------------------------------------------------------- 状态映射
def test_error_prediction_maps_failed() -> None:
    result = map_prediction({"id": "pred-1", "status": "failed", "error": "content blocked"})
    assert result.status == "failed" and result.error


def test_running_then_succeeded_mapping() -> None:
    running = map_prediction({"id": "pred-1", "status": "processing"})
    assert running.status == "running"
    done = map_prediction({"id": "pred-1", "status": "succeeded", "output": ["https://cdn.example.test/v.mp4"]})
    assert done.status == "succeeded" and done.output_urls[0].startswith("https://")


def test_success_without_output_is_pending_download() -> None:
    done = map_prediction({"id": "pred-1", "status": "succeeded"})
    assert done.status == "succeeded" and done.output_urls == ()


def test_error_body_in_prediction_not_success() -> None:
    result = map_prediction({"error": {"message": "model unavailable"}})
    assert result.status == "failed"


# ---------------------------------------------------------------- 提交/轮询/报价 HTTP
def test_submit_parses_prediction_id() -> None:
    def handler(request):
        assert request.url.path.endswith("/api/v1/model/generateVideo")
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"id": "pred-42"})
    pid = asyncio.run(submit_generation(build_h3_request(_input(), DRAFT_H3_CAPABILITIES), base_url=BASE, api_key="test-key", transport=httpx.MockTransport(handler)))
    assert pid == "pred-42"


def test_submit_error_status_raises() -> None:
    def handler(request):
        return httpx.Response(429, json={"error": {"message": "rate limited"}})
    with pytest.raises(ProviderRequestError):
        asyncio.run(submit_generation({"model": "x"}, base_url=BASE, api_key="k", transport=httpx.MockTransport(handler)))


def test_poll_maps_status() -> None:
    def handler(request):
        return httpx.Response(200, json={"id": "pred-42", "status": "succeeded", "output": ["https://cdn.example.test/a.mp4"]})
    result = asyncio.run(poll_prediction("pred-42", base_url=BASE, api_key="k", transport=httpx.MockTransport(handler)))
    assert result.status == "succeeded"


def test_quote_decimal_precision() -> None:
    """小额美元精确解析为 Decimal（C03 前置）。"""
    def handler(request):
        assert request.url.path.endswith("/api/v1/model/calculate")
        return httpx.Response(200, json={"amount": "0.001", "currency": "USD", "is_estimate": False})
    quote = asyncio.run(quote_generation(
        {"model": "x"}, base_url=BASE, api_key="k",
        request_fingerprint="fp-1", model_id="minimax-h3-developer-reference",
        requested_duration_ms=6_000, resolution_id="720p",
        transport=httpx.MockTransport(handler),
    ))
    from decimal import Decimal
    assert quote.estimated_amount == Decimal("0.001")
    assert quote.currency == "USD" and quote.is_estimated is False


def test_quote_error_not_success() -> None:
    def handler(request):
        return httpx.Response(200, json={"error": {"message": "model not priced"}})
    with pytest.raises(PricingError):
        asyncio.run(quote_generation(
            {"model": "x"}, base_url=BASE, api_key="k",
            request_fingerprint="fp-1", model_id="m",
            requested_duration_ms=6_000, resolution_id="720p",
            transport=httpx.MockTransport(handler),
        ))
