from __future__ import annotations

import pytest
import pytest_asyncio

from app.models_commercial import (
    CvActor,
    CvActorVersion,
    CvMediaAsset,
    CvProduct,
    CvProductVersion,
    CvProduction,
    CvReplicationProject,
    CvScriptVersion,
    CvTemplate,
    CvTemplateVersion,
    CvVoiceProfile,
)
from app.services.commercial.voice import VoiceRenderError, VoiceRenderRequest, VoiceStrategy
from tests.conftest import make_user


@pytest_asyncio.fixture
async def voice_render_graph(db_session):
    user = await make_user(db_session)
    template = CvTemplate(name="声音绑定模板", created_by=user.id)
    actor = CvActor(name="达人 A", created_by=user.id)
    other_actor = CvActor(name="达人 B", created_by=user.id)
    product = CvProduct(name="声音绑定商品", created_by=user.id)
    db_session.add_all([template, actor, other_actor, product])
    await db_session.flush()

    template_version = CvTemplateVersion(
        template_id=template.id, version=1, status="published",
        structure_json={"shots": []}, published_by=user.id,
    )
    actor_version = CvActorVersion(
        actor_id=actor.id, version=1, status="published", published_by=user.id,
    )
    product_version = CvProductVersion(
        product_id=product.id, version=1, status="published", published_by=user.id,
    )
    db_session.add_all([template_version, actor_version, product_version])
    await db_session.flush()

    assets = [
        CvMediaAsset(
            kind="audio", object_key=f"owned_voice_reference/test-{suffix}.mp3",
            sha256=suffix * 64, mime="audio/mpeg", size_bytes=10,
            source_role="owned_voice_reference", uploaded_by=user.id,
        )
        for suffix in ("a", "b")
    ]
    db_session.add_all(assets)
    await db_session.flush()
    voice = CvVoiceProfile(actor_id=actor.id, audio_asset_id=assets[0].id)
    other_voice = CvVoiceProfile(actor_id=other_actor.id, audio_asset_id=assets[1].id)
    db_session.add_all([voice, other_voice])
    await db_session.flush()

    production = CvProduction(
        template_version_id=template_version.id, actor_version_id=actor_version.id,
        voice_profile_id=voice.id, product_version_id=product_version.id,
        created_by=user.id,
    )
    db_session.add(production)
    await db_session.flush()
    project = CvReplicationProject(production_id=production.id, created_by=user.id)
    db_session.add(project)
    await db_session.flush()
    script = CvScriptVersion(
        replication_project_id=project.id, version=1, mode="structural_rewrite",
        script_json={"scripts": [{"dialogue": "这是已批准的台词"}]}, status="approved",
    )
    db_session.add(script)
    await db_session.flush()
    return db_session, script, voice, other_voice, project


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


@pytest.mark.asyncio
async def test_voice_render_accepts_voice_bound_to_project_actor(voice_render_graph):
    db, script, voice, _other_voice, project = voice_render_graph
    # An unverified rights object stops before synthesis, proving the binding
    # check passed without invoking the provider or writing output assets.
    request = VoiceRenderRequest(
        script_version_id=script.id,
        voice_profile_id=voice.id,
        replication_project_id=project.id,
        rights_evidence={"verified": False},
    )
    with pytest.raises(VoiceRenderError) as exc:
        await VoiceStrategy(db).render(request)
    assert exc.value.code == "RIGHTS_UNVERIFIED"


@pytest.mark.asyncio
async def test_voice_render_blocks_voice_bound_to_other_actor(voice_render_graph):
    db, script, _voice, other_voice, project = voice_render_graph
    request = VoiceRenderRequest(
        script_version_id=script.id,
        voice_profile_id=other_voice.id,
        replication_project_id=project.id,
        rights_evidence={"verified": True},
    )
    with pytest.raises(VoiceRenderError) as exc:
        await VoiceStrategy(db).render(request)
    assert exc.value.code == "VOICE_BINDING_INVALID"
