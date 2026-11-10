# -*- coding: utf-8 -*-
"""T05｜达人-音色绑定与商品卖点边界（G01/G02）。"""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio

from app.models_commercial import (
    CvActor,
    CvActorVersion,
    CvProduct,
    CvProductVersion,
    CvVoiceProfile,
)
from app.services.commercial.actors import VoiceBindingError, validate_voice_binding
from app.services.commercial.products import ClaimError, validate_dialogue_claims
from tests.conftest import make_user


@pytest_asyncio.fixture
async def uploader(db_session):
    return await make_user(db_session)


async def _actor(db, name: str, user_id: int = 1) -> tuple[CvActor, CvActorVersion]:
    actor = CvActor(name=name, created_by=user_id)
    db.add(actor)
    await db.flush()
    version = CvActorVersion(actor_id=actor.id, version=1, status="published", published_by=user_id)
    db.add(version)
    await db.flush()
    return actor, version


async def _voice(db, actor_id: int, user_id: int = 1, **kw) -> CvVoiceProfile:
    from app.models_commercial import CvMediaAsset

    asset = CvMediaAsset(
        kind="audio", object_key=f"owned_voice_reference/t/{kw.get('suffix', 'v1')}.mp3",
        sha256=kw.get("sha", "c" * 64), mime="audio/mpeg", size_bytes=10,
        source_role="owned_voice_reference", uploaded_by=user_id,
    )
    db.add(asset)
    await db.flush()
    voice = CvVoiceProfile(
        actor_id=actor_id, audio_asset_id=asset.id, language="zh-CN",
        authorized_until=kw.get("authorized_until"),
    )
    db.add(voice)
    await db.flush()
    return voice


async def _product(db, user, name: str, *, claims: list[dict], form: str = "瓶装精华",
                   forbidden: list[str] | None = None) -> CvProductVersion:
    product = CvProduct(name=name, created_by=user.id)
    db.add(product)
    await db.flush()
    version = CvProductVersion(
        product_id=product.id, version=1, form=form, published_by=user.id,
        claims=claims, forbidden_phrases=forbidden or [], allowed_actions=["手持正面展示"],
    )
    db.add(version)
    await db.flush()
    return version


# ---------------------------------------------------------------- G01 音色绑定
@pytest.mark.asyncio
async def test_cross_actor_voice_blocked(db_session, uploader) -> None:
    """达人 A 的作品绑定达人 B 的声音：必须拦截，除非显式批准特殊绑定。"""
    actor_a, version_a = await _actor(db_session, "达人A", user_id=uploader.id)
    actor_b, _ = await _actor(db_session, "达人B", user_id=uploader.id)
    voice_b = await _voice(db_session, actor_b.id, user_id=uploader.id)

    with pytest.raises(VoiceBindingError) as exc:
        validate_voice_binding(version_a, voice_b, allow_cross_actor=False)
    assert exc.value.code == "VOICE_BINDING_INVALID"

    # 显式批准后放行（记录在案的特殊绑定）
    validate_voice_binding(version_a, voice_b, allow_cross_actor=True)


@pytest.mark.asyncio
async def test_expired_voice_blocked(db_session, uploader) -> None:
    from datetime import UTC, datetime

    actor, version = await _actor(db_session, "达人A", user_id=uploader.id)
    voice = await _voice(
        db_session, actor.id, user_id=uploader.id,
        authorized_until=datetime.now(UTC) - timedelta(days=1),
    )
    with pytest.raises(VoiceBindingError) as exc:
        validate_voice_binding(version, voice, allow_cross_actor=False)
    assert exc.value.code == "VOICE_AUTHORIZATION_EXPIRED"


@pytest.mark.asyncio
async def test_same_actor_voice_ok(db_session, uploader) -> None:
    actor, version = await _actor(db_session, "达人A", user_id=uploader.id)
    voice = await _voice(db_session, actor.id, user_id=uploader.id)
    validate_voice_binding(version, voice, allow_cross_actor=False)


# ---------------------------------------------------------------- G02 卖点边界
@pytest.mark.asyncio
async def test_unapproved_claim_rejected(db_session, uploader) -> None:
    product = await _product(db_session, uploader, "P1", claims=[
        {"claim_id": "c1", "text": "质地清爽不粘腻", "approved": True},
        {"claim_id": "c2", "text": "美白效果显著", "approved": False},
    ])
    # 台词引用未审核卖点 → 拒绝（不得自动投放到台词）
    with pytest.raises(ClaimError) as exc:
        validate_dialogue_claims(product, dialogue="这款精华美白效果显著", used_claim_ids=["c2"])
    assert exc.value.code == "CLAIM_NOT_APPROVED"


@pytest.mark.asyncio
async def test_forbidden_phrase_rejected(db_session, uploader) -> None:
    product = await _product(db_session, uploader, "P1", claims=[
        {"claim_id": "c1", "text": "质地清爽", "approved": True},
    ], forbidden=["根治痘痘"])
    with pytest.raises(ClaimError) as exc:
        validate_dialogue_claims(product, dialogue="坚持使用可以根治痘痘", used_claim_ids=["c1"])
    assert exc.value.code == "CLAIM_FORBIDDEN_PHRASE"


@pytest.mark.asyncio
async def test_new_fact_flagged_not_approved(db_session, uploader) -> None:
    """适配输出中出现非审核卖点的新事实：待人工审核，不自动采用。"""
    from app.services.commercial.adaptation import flag_new_facts

    product = await _product(db_session, uploader, "P1", claims=[
        {"claim_id": "c1", "text": "质地清爽", "approved": True},
    ])
    draft = {
        "shots": [
            {"shot_key": "S01", "dialogue": "质地清爽，而且七天美白", "action": "展示商品"},
        ]
    }
    flagged = flag_new_facts(draft, product)
    assert any(f["claim_id"] is None for f in flagged)  # “七天美白”不在审核卖点内
    assert flagged, "新事实必须标记待审核"


@pytest.mark.asyncio
async def test_product_form_mismatch_requires_adaptation(db_session, uploader) -> None:
    """模板动作“开瓶盖”遇贴片商品：必须给适配动作或标记不适用，不得原样套用。"""
    from app.services.commercial.adaptation import adapt_action_for_form

    patch = await _product(db_session, uploader, "P2", claims=[
        {"claim_id": "p1", "text": "贴敷清凉", "approved": True},
    ], form="贴片")
    result = adapt_action_for_form(
        template_action="拧开瓶盖倒出精华展示质地", product_form=patch.form,
    )
    assert result["status"] in {"adapted", "inapplicable"}
    if result["status"] == "adapted":
        assert "瓶盖" not in result["action"]  # 原动作不可残留
