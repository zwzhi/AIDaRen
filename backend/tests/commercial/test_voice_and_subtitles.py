from __future__ import annotations

import pytest


def test_voice_render_requires_verified_rights():
    from app.services.commercial.voice import VoiceFixtureRequest, VoiceRenderError, render_voice_fixture

    request = VoiceFixtureRequest(
        script_version_id=1,
        script_hash="a" * 64,
        voice_profile_id=2,
        dialogue="你好",
        rights_verified=False,
    )
    with pytest.raises(VoiceRenderError) as exc:
        render_voice_fixture(request)
    assert exc.value.code == "VOICE_RIGHTS_REQUIRED"


def test_voice_render_returns_measured_duration_and_versioned_hash():
    from app.services.commercial.voice import VoiceFixtureRequest, render_voice_fixture

    result = render_voice_fixture(VoiceFixtureRequest(
        script_version_id=1,
        script_hash="a" * 64,
        voice_profile_id=2,
        dialogue="这是已批准的台词",
        rights_verified=True,
    ))

    assert result.status == "pending_review"
    assert result.duration_ms > 0
    assert result.script_hash == "a" * 64
    assert result.audio_asset_payload["source_role"] == "owned_generated_audio"


def test_subtitle_revision_is_invalidated_when_script_changes():
    from app.services.commercial.voice import SubtitleRevision, invalidate_subtitle_revision

    revision = SubtitleRevision(version=1, script_hash="a" * 64, status="approved")
    invalidated = invalidate_subtitle_revision(revision, reason="script_changed")
    assert invalidated.status == "invalidated"
    assert invalidated.invalidation_reason == "script_changed"
