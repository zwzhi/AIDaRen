# -*- coding: utf-8 -*-
"""T05｜模板复用不复用原片（G03/T03）：换商品只做文本适配。"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.models_commercial import (
    CvAnalysisRun,
    CvMediaAsset,
    CvProduct,
    CvProductVersion,
    CvReferenceSource,
    CvTemplate,
)
from app.services.commercial.adaptation import adapt_template
from app.services.commercial.template_service import publish_template
from tests.conftest import make_user


@pytest_asyncio.fixture
async def uploader(db_session):
    return await make_user(db_session)


def _template_shots() -> list[dict]:
    return [
        {"shot_id": "S01", "start_ms": 0, "end_ms": 8000, "observation": "提问引入",
         "dialogue_template": "{{opening_question}}", "action_template": "看向镜头轻微抬手"},
        {"shot_id": "S02", "start_ms": 8000, "end_ms": 20000, "observation": "商品展示",
         "dialogue_template": "{{approved_core_claim}}", "action_template": "拿起本次商品正面朝向镜头，动作按商品形态适配"},
        {"shot_id": "S03", "start_ms": 20000, "end_ms": 30000, "observation": "总结引导",
         "dialogue_template": "{{closing_cta}}", "action_template": "面向镜头自然总结"},
    ]


async def _published_template(db, user) -> int:
    template = CvTemplate(name="T1", created_by=user.id)
    db.add(template)
    await db.flush()
    version = await publish_template(
        db, template=template, draft_payload={
            "shots": _template_shots(),
            "variables": ["opening_question", "approved_core_claim", "closing_cta"],
        },
        expected_version=1, publisher_id=user.id,
    )
    return version.id


async def _product(db, user, name: str, claim_text: str, old_claim: str | None = None) -> CvProductVersion:
    product = CvProduct(name=name, created_by=user.id)
    db.add(product)
    await db.flush()
    version = CvProductVersion(
        product_id=product.id, version=1, form="贴片", published_by=user.id,
        claims=[
            {"claim_id": f"{name}-c1", "text": claim_text, "approved": True},
        ],
        forbidden_phrases=[old_claim] if old_claim else [],
        allowed_actions=["贴敷手背展示"],
    )
    db.add(version)
    await db.flush()
    return version


@pytest.mark.asyncio
async def test_second_product_adapts_text_only(db_session, uploader) -> None:
    """同一模板换 P2：只触发文本适配，输入不含原片任何形态，旧卖点不迁移。"""
    version_id = await _published_template(db_session, uploader)
    p2 = await _product(
        db_session, uploader, "P2", claim_text="贴敷八小时持久清凉",
        old_claim="拧开瓶盖质地清爽",
    )

    captured: dict = {}

    async def fake_adaptor(request: dict) -> dict:
        captured.update(request)
        return {
            "shots": [
                {"shot_key": "S01", "dialogue": "夏天出门手心也出汗吗", "action": "看向镜头"},
                {"shot_key": "S02", "dialogue": "贴敷八小时持久清凉", "action": "贴敷手背展示"},
                {"shot_key": "S03", "dialogue": "点击下方链接试试", "action": "总结"},
            ],
            "pending_review": [],
        }

    draft = await adapt_template(
        db_session, template_version_id=version_id, product=p2,
        marketing_goal="种草", user_locked_dialogue=None,
        adaptor=fake_adaptor,
    )

    # 适配输入只有模板文本 + 我方商品资料：无原片/关键帧/原音轨
    serialized = str(captured).lower()
    for banned in ("source_video", "source_frame", "source_asset", "keyframe", "video_bytes", "reference_source"):
        assert banned not in serialized, f"适配输入泄漏了原片内容：{banned}"
    assert captured["product"]["claims"][0]["text"] == "贴敷八小时持久清凉"

    # 产物台词使用 P2 卖点，不携带 P1 旧卖点
    dialogues = " ".join(s["dialogue"] for s in draft["shots"])
    assert "贴敷八小时持久清凉" in dialogues
    assert "拧开瓶盖质地清爽" not in dialogues


@pytest.mark.asyncio
async def test_no_new_analysis_run_for_reuse(db_session, uploader) -> None:
    """复用模板不重新解析：适配过程不创建任何 CvAnalysisRun。"""
    from sqlalchemy import func, select

    version_id = await _published_template(db_session, uploader)
    p2 = await _product(db_session, uploader, "P2b", claim_text="温和不刺激")

    async def fake_adaptor(request: dict) -> dict:
        return {"shots": [
            {"shot_key": "S01", "dialogue": "问题", "action": "a"},
            {"shot_key": "S02", "dialogue": "温和不刺激", "action": "b"},
            {"shot_key": "S03", "dialogue": "引导", "action": "c"},
        ], "pending_review": []}

    before = (await db_session.execute(select(func.count()).select_from(CvAnalysisRun))).scalar_one()
    await adapt_template(
        db_session, template_version_id=version_id, product=p2,
        marketing_goal="种草", user_locked_dialogue=None, adaptor=fake_adaptor,
    )
    after = (await db_session.execute(select(func.count()).select_from(CvAnalysisRun))).scalar_one()
    assert before == after  # 无新解析任务（也没有隐性上传）


@pytest.mark.asyncio
async def test_locked_dialogue_not_rewritten(db_session, uploader) -> None:
    """台词锁定：适配只能建议动作，模型改写台词的输出被丢弃并回填定稿。"""
    version_id = await _published_template(db_session, uploader)
    p2 = await _product(db_session, uploader, "P2c", claim_text="成分温和")
    locked = {
        "S01": "手汗星人看过来",
        "S02": "成分温和，贴上就凉快",
        "S03": "点链接带走",
    }

    async def fake_adaptor(request: dict) -> dict:
        return {"shots": [
            {"shot_key": "S01", "dialogue": "被我改写的台词A", "action": "a"},
            {"shot_key": "S02", "dialogue": "被我改写的台词B", "action": "b"},
            {"shot_key": "S03", "dialogue": "被我改写的台词C", "action": "c"},
        ], "pending_review": []}

    draft = await adapt_template(
        db_session, template_version_id=version_id, product=p2,
        marketing_goal="种草", user_locked_dialogue=locked, adaptor=fake_adaptor,
    )
    for shot in draft["shots"]:
        assert locked[shot["shot_key"]] == shot["dialogue"]  # 定稿台词原样保留
        assert "被我改写" not in shot["dialogue"]
    # 改写尝试被记录为待审核提示
    assert draft.get("dialogue_locked") is True
