# -*- coding: utf-8 -*-
"""T03｜真实服务商冒烟（live）：只有显式提供 ATLAS_API_KEY 且开启开关才执行。

运行方式（需真实密钥与预算授权，任务书 §17.2）：

    ATLAS_API_KEY=... GEMINI_ANALYSIS_MODEL_ID=... H3_DEVELOPER_REFERENCE_MODEL_ID=... \
    COMMERCIAL_LIVE_TESTS=1 pytest tests/commercial/live -q

未配置时全部跳过，不做任何付费调用。
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("COMMERCIAL_LIVE_TESTS") and os.environ.get("ATLAS_API_KEY")),
    reason="真实联调未授权：需要 ATLAS_API_KEY 与 COMMERCIAL_LIVE_TESTS=1（BLOCKED，见 provider_contracts.md）",
)


@pytest.mark.asyncio
async def test_gemini_hears_and_sees_short_video() -> None:
    """5～15 秒带对白视频：验证 Gemini 真正读到画面与音轨（A01/G05 前置）。

    需准备 COMMERCIAL_LIVE_SAMPLE_MP4 指向本地授权测试视频。
    """
    sample = os.environ.get("COMMERCIAL_LIVE_SAMPLE_MP4")
    if not sample:
        pytest.skip("未提供测试视频 COMMERCIAL_LIVE_SAMPLE_MP4")
    from pathlib import Path

    from app.services.providers.atlas.client import resolve_provider_for_commercial_task
    from app.services.providers.atlas.gemini import GeminiAnalysisRequest, analyze_video
    from app.services.commercial.storage import probe_media_bytes

    provider = resolve_provider_for_commercial_task()
    raw = Path(sample).read_bytes()
    probe = await probe_media_bytes(raw, sample, role_is_video=True)
    request = GeminiAnalysisRequest(
        source_id=0, model_id=provider.models["analysis"],
        video_bytes=raw, video_mime=probe.mime, source_duration_ms=probe.duration_ms or 0,
    )
    result = await analyze_video(request, base_url=provider.base_url, api_key=provider.api_key)
    assert result.shots, "解析未返回任何镜头"
    # 证据保存：脱敏写盘由 T10 验收流程统一归档


@pytest.mark.asyncio
async def test_h3_accepts_image_voice_new_dialogue() -> None:
    """自有图片+音色+与样本不同的新台词：先报价再提交（H3 关键验收前置）。

    需准备 COMMERCIAL_LIVE_ACTOR_PNG / VOICE_MP3；断言报价金额>0 且生成含音轨。
    """
    for var in ("COMMERCIAL_LIVE_ACTOR_PNG", "COMMERCIAL_LIVE_VOICE_MP3"):
        if not os.environ.get(var):
            pytest.skip(f"未提供 {var}")
    pytest.skip("BLOCKED：等待真实密钥、素材授权与预算确认后启用（任务书 §19）")
