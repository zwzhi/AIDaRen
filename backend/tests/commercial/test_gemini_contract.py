# -*- coding: utf-8 -*-
"""T03｜Gemini 原生协议契约测试（Fixture 驱动；真实联调见 live/ 标记 BLOCKED）。

Fixture 为 DRAFT 样本：字段结构按任务书 §5.2 与公开 Gemini 协议构造，
真实账号响应落地后替换（docs/handoff/provider_contracts.md 记录状态）。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.schemas_commercial import AnalysisSchemaInvalid
from app.services.providers.atlas.gemini import (
    GeminiAnalysisRequest,
    ProviderRequestError,
    analyze_video,
    build_generate_content_body,
    parse_analysis_response,
)

BASE = "https://api.atlascloud.ai"


def _request() -> GeminiAnalysisRequest:
    return GeminiAnalysisRequest(
        source_id=1, model_id="gemini-3-flash-preview",
        video_bytes=b"FAKEVIDEOBYTES", video_mime="video/mp4",
        source_duration_ms=30_000,
    )


def _happy_payload() -> dict:
    return {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps({
                "duration_ms": 30_000,
                "shots": [
                    {"shot_id": "S01", "start_ms": 0, "end_ms": 8000,
                     "keyframe_hints_ms": [0, 4000], "observation": "单人讲解",
                     "inference": "提出问题", "uncertainty": ""},
                    {"shot_id": "S02", "start_ms": 8000, "end_ms": 20000,
                     "keyframe_hints_ms": [9000], "observation": "商品特写",
                     "inference": "展示卖点", "uncertainty": "商品名不确定"},
                    {"shot_id": "S03", "start_ms": 20000, "end_ms": 30000,
                     "keyframe_hints_ms": [], "observation": "总结",
                     "inference": "引导行动", "uncertainty": ""},
                ],
                "transcript": [{"speaker": "SPK1", "start_ms": 0, "end_ms": 7500, "text": "……"}],
                "uncertainties": [{"at_ms": 9000, "note": "商品名不确定"}],
            }, ensure_ascii=False)}]}
        }]
    }


def _transport(handler):
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- 请求构造
def test_request_carries_video_inline_data() -> None:
    """原生视频输入：inline_data 携带字节与 MIME，不是只传文件名/URL。"""
    body = build_generate_content_body(_request())
    parts = body["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "video/mp4"
    assert parts[0]["inline_data"]["data"]  # base64 非空
    assert body["generation_config"]["response_mime_type"] == "application/json"
    serialized = json.dumps(body)
    assert ".mp4?url" not in serialized and "source_video_url" not in serialized


# ---------------------------------------------------------------- 响应解析
def test_happy_fixture_parses_and_validates() -> None:
    result = parse_analysis_response(_happy_payload(), _request())
    assert [s.shot_id for s in result.shots] == ["S01", "S02", "S03"]
    assert result.duration_ms == 30_000  # 以后端探测为准
    result.validate()  # 不抛


def test_error_payload_not_treated_as_success() -> None:
    with pytest.raises(ProviderRequestError):
        parse_analysis_response({"error": {"message": "quota exceeded"}}, _request())


def test_http_401_raises() -> None:
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})
    with pytest.raises(ProviderRequestError) as exc:
        import asyncio
        asyncio.run(analyze_video(_request(), base_url=BASE, api_key="bad", transport=_transport(handler)))
    assert exc.value.status_code == 401


def test_truncated_json_rejected() -> None:
    truncated = '{"shots": [{"shot_id": "S01", "star'
    payload = {"candidates": [{"content": {"parts": [{"text": truncated}]}}]}
    with pytest.raises(AnalysisSchemaInvalid):
        parse_analysis_response(payload, _request())


def test_out_of_range_timeline_rejected() -> None:
    bad = _happy_payload()
    text = json.loads(bad["candidates"][0]["content"]["parts"][0]["text"])
    text["shots"][2]["end_ms"] = 45_000  # 越出原片
    bad["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(text)
    with pytest.raises(AnalysisSchemaInvalid):
        parse_analysis_response(bad, _request())


def test_reversed_shot_order_rejected() -> None:
    bad = _happy_payload()
    text = json.loads(bad["candidates"][0]["content"]["parts"][0]["text"])
    text["shots"].reverse()
    bad["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(text)
    with pytest.raises(AnalysisSchemaInvalid):
        parse_analysis_response(bad, _request())
