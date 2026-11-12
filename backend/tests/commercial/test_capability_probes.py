from __future__ import annotations

import asyncio

import httpx


def test_h3_real_probe_uses_capability_endpoint_and_never_generation() -> None:
    from app.services.providers.atlas.h3_reference import H3VideoAdapter

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        assert request.url.path.endswith("/api/v1/model/capabilities")
        assert request.url.params.get("model") == "h3-real"
        return httpx.Response(
            200,
            json={
                "model": "h3-real",
                "capability_verified": True,
                "duration_min_ms": 5000,
                "duration_max_ms": 15000,
                "duration_step_ms": 1000,
                "resolutions": ["480p", "768p"],
                "aspect_ratios": ["9:16"],
                "audio_supported": True,
                "voice_reference_supported": True,
            },
        )

    adapter = H3VideoAdapter(mode="real", model_id="h3-real", base_url="https://atlas.test", api_key="k", capabilities=None)
    caps = asyncio.run(adapter.probe_capabilities(real=True, transport=httpx.MockTransport(handler)))

    assert caps.capability_verified is True
    assert caps.resolutions == frozenset({"480p", "768p"})
    assert seen == ["GET /api/v1/model/capabilities"]


def test_h3_real_probe_failure_is_unverified_and_does_not_charge() -> None:
    from app.services.providers.atlas.h3_reference import H3VideoAdapter

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(503, json={"error": "unavailable"})

    adapter = H3VideoAdapter(mode="real", base_url="https://atlas.test", api_key="k")
    caps = asyncio.run(adapter.probe_capabilities(real=True, transport=httpx.MockTransport(handler)))

    assert caps.capability_verified is False
    assert caps.probe_status == "failed"
    assert all("generate" not in item.lower() for item in seen)


def test_image_edit_real_probe_requires_explicit_verification() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/api/v1/model/capabilities")
        return httpx.Response(200, json={"model": "image2.6", "supports_anchor_reference": True})

    adapter = ImageEditAdapter(model_id="image2.6", mode="real", base_url="https://atlas.test", api_key="k")
    caps = asyncio.run(adapter.probe(real=True, transport=httpx.MockTransport(handler)))

    assert caps.model_id == "image2.6"
    assert caps.capability_verified is False
    assert caps.probe_status == "unverified"


def test_image_edit_real_probe_failure_cannot_enable_generation() -> None:
    from app.services.providers.atlas.image_edit import ImageEditAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    adapter = ImageEditAdapter(model_id="image2.6", mode="real", base_url="https://atlas.test", api_key="k")
    caps = asyncio.run(adapter.probe(real=True, transport=httpx.MockTransport(handler)))
    assert caps.capability_verified is False
    assert caps.probe_status == "failed"


def test_voice_capabilities_keep_h3_native_and_tts_fallback_separate() -> None:
    from app.services.commercial.voice import VoiceAdapter, VoiceStrategy

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"model": "h3-voice", "native_voice_supported": True, "capability_verified": True})

    adapter = VoiceAdapter(model_id="h3-voice", mode="real", base_url="https://atlas.test", api_key="k")
    caps = asyncio.run(adapter.probe(real=True, transport=httpx.MockTransport(handler)))

    assert caps.native_voice_supported is True
    assert caps.capability_verified is True
    assert caps.tts_fallback_supported is True
    assert caps.native_provider == "h3"
    assert VoiceStrategy.voice_mode_for(caps) == "h3_native"
    fallback = VoiceAdapter(model_id="tts-fallback", mode="mock")
    assert VoiceStrategy.voice_mode_for(fallback.probe()) == "tts_fallback"
