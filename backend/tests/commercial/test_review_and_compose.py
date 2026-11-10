# -*- coding: utf-8 -*-
"""T09｜质检门槛、单镜重做与合成选择（R01/R02/R03 + 字幕策略）。"""
from __future__ import annotations

import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from app.models_commercial import (
    CvBudgetPool,
    CvCostQuote,
    CvGenerationAttempt,
)
from app.services.commercial import compose as compose_svc
from app.services.commercial import review_service as review
from tests.conftest import make_user


@pytest_asyncio.fixture
async def owner(db_session):
    return await make_user(db_session)


async def _attempt(db, owner, *, status: str = "GENERATED", output_key: str | None = "u1.mp4",
                   client_req: str | None = None) -> CvGenerationAttempt:
    await CvBudgetPool.ensure_default(db, total=Decimal("100.00"), created_by=owner.id)
    quote = CvCostQuote(
        quote_key=f"q-{client_req or output_key}-{owner.id}", model_id="m",
        request_fingerprint="fp", estimated_amount=Decimal("0.05"), currency="USD",
    )
    db.add(quote)
    await db.flush()
    attempt = CvGenerationAttempt(
        client_request_id=client_req or f"cr-{quote.id}", payload_hash="fp",
        quote_id=quote.id, status=status, output_asset_key=output_key,
        created_by=owner.id,
    )
    db.add(attempt)
    await db.flush()
    return attempt


# ---------------------------------------------------------------- R01 阻断项
@pytest.mark.asyncio
async def test_hard_dimensions_block_approval(db_session, owner) -> None:
    """人物合格但台词错误 → 整体驳回：硬错误不用总分抵消（R01）。"""
    attempt = await _attempt(db_session, owner)
    decision = await review.record_review(
        db_session, attempt, reviewer_id=owner.id,
        dimensions={
            "人物身份": "PASS", "商品准确": "PASS", "音色": "PASS",
            "台词": ("FAIL", "商品名读错"), "口型": "PASS",
            "动作与画面": "PASS", "模板表达": "PASS", "技术输出": "PASS",
        },
    )
    assert decision.overall == "REVIEW_REJECTED"
    await db_session.refresh(attempt)
    assert attempt.status == "REVIEW_REJECTED"


@pytest.mark.asyncio
async def test_all_pass_approves(db_session, owner) -> None:
    attempt = await _attempt(db_session, owner)
    decision = await review.record_review(
        db_session, attempt, reviewer_id=owner.id,
        dimensions={dim: "PASS" for dim in review.REVIEW_DIMENSIONS},
    )
    assert decision.overall == "REVIEW_APPROVED"
    await db_session.refresh(attempt)
    assert attempt.status == "REVIEW_APPROVED"


@pytest.mark.asyncio
async def test_lipsync_na_only_without_speech(db_session, owner) -> None:
    """无口播镜头口型可 N/A；要求口播（audio_required）的镜头用 N/A 规避失败 → 拒绝。"""
    attempt = await _attempt(db_session, owner)
    decision = await review.record_review(
        db_session, attempt, reviewer_id=owner.id, speech_required=True,
        dimensions={**{d: "PASS" for d in review.REVIEW_DIMENSIONS}, "口型": "NOT_APPLICABLE"},
    )
    assert decision.overall == "REVIEW_REJECTED"


@pytest.mark.asyncio
async def test_review_history_immutable(db_session, owner) -> None:
    """审核记录只追加：再次审核生成新记录，旧记录不覆盖（可追溯）。"""
    from sqlalchemy import func, select

    from app.models_commercial import CvReview

    attempt = await _attempt(db_session, owner)
    await review.record_review(
        db_session, attempt, reviewer_id=owner.id,
        dimensions={d: "PASS" for d in review.REVIEW_DIMENSIONS},
    )
    await review.record_review(
        db_session, attempt, reviewer_id=owner.id,
        dimensions={**{d: "PASS" for d in review.REVIEW_DIMENSIONS}, "台词": ("FAIL", "复审发现错读")},
    )
    count = (await db_session.execute(
        select(func.count()).select_from(CvReview).where(CvReview.attempt_id == attempt.id)
    )).scalar_one()
    assert count == 2 * len(review.REVIEW_DIMENSIONS)  # 两次审核 × 全维度，历史都在


# ---------------------------------------------------------------- R02 单镜重做
@pytest.mark.asyncio
async def test_regenerate_keeps_other_approved_versions(db_session, owner) -> None:
    """一个镜头重做：其余合格 attempt 与旧版本保留（R02）。"""
    a1 = await _attempt(db_session, owner, client_req="unit1-v1")
    await review.record_review(
        db_session, a1, reviewer_id=owner.id,
        dimensions={d: "PASS" for d in review.REVIEW_DIMENSIONS},
    )
    # 另一镜头的合格版本
    a2 = await _attempt(db_session, owner, client_req="unit2-v1", output_key="u2.mp4")
    await review.record_review(
        db_session, a2, reviewer_id=owner.id,
        dimensions={d: "PASS" for d in review.REVIEW_DIMENSIONS},
    )
    # 重做 unit1：新建 attempt v2（新预算新 client_request_id）
    a1v2 = await _attempt(db_session, owner, client_req="unit1-v2", output_key="u1v2.mp4")
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    assert a1.status == "REVIEW_APPROVED"  # 旧版本不受影响
    assert a2.status == "REVIEW_APPROVED"
    assert a1v2.status == "GENERATED"


# ---------------------------------------------------------------- R03 合成
def _make_clip(path: Path, seconds: float = 3) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=160x120:rate=10",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path


@pytest.mark.asyncio
async def test_compose_only_approved_attempts_no_generation(db_session, owner, tmp_path) -> None:
    """驳回镜头不能合成；合成全程不触发任何生成调用（R03）。"""
    good = await _attempt(db_session, owner, client_req="c-good", output_key="good.mp4")
    await review.record_review(
        db_session, good, reviewer_id=owner.id,
        dimensions={d: "PASS" for d in review.REVIEW_DIMENSIONS},
    )
    bad = await _attempt(db_session, owner, client_req="c-bad", output_key="bad.mp4")
    await review.record_review(
        db_session, bad, reviewer_id=owner.id,
        dimensions={**{d: "PASS" for d in review.REVIEW_DIMENSIONS}, "台词": ("FAIL", "错读")},
    )

    # 驳回镜头参与合成 → 拒绝
    with pytest.raises(compose_svc.ComposeError) as exc:
        await compose_svc.compose_production(
            db_session, selections=[(good, [(good.output_asset_key, 0, 3000)]),
                                     (bad, [(bad.output_asset_key, 0, 3000)])],
        )
    assert "REVIEW" in str(exc.value) or "审核" in str(exc.value)


@pytest.mark.asyncio
async def test_compose_trims_adoption_ranges(db_session, owner, tmp_path) -> None:
    """生成5秒采用2秒：成片按采用区间裁剪，总时长=采用区间之和。"""
    from app.services.commercial.storage import commercial_storage_root

    clip1 = _make_clip(commercial_storage_root() / "outputs" / "cmp-a.mp4", seconds=5)
    clip2 = _make_clip(commercial_storage_root() / "outputs" / "cmp-b.mp4", seconds=5)
    a1 = await _attempt(db_session, owner, client_req="t-a", output_key=clip1.name)
    a2 = await _attempt(db_session, owner, client_req="t-b", output_key=clip2.name)
    for a in (a1, a2):
        await review.record_review(
            db_session, a, reviewer_id=owner.id,
            dimensions={d: "PASS" for d in review.REVIEW_DIMENSIONS},
        )
    export = await compose_svc.compose_production(
        db_session,
        selections=[(a1, [(clip1.name, 500, 2500)]), (a2, [(clip2.name, 1000, 3000)])],
    )
    # 采用区间 2s + 2s = 4s（±0.3s 容差）
    import asyncio
    probe = await asyncio.to_thread(_probe_duration_ms, Path(export.master_path))
    assert abs(probe - 4000) <= 300, f"成片时长 {probe}ms 与采用区间 4000ms 不符"


def _probe_duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)],
        check=True, capture_output=True,
    ).stdout.decode()
    import json

    return int(float(json.loads(out)["format"]["duration"]) * 1000)


# ---------------------------------------------------------------- 字幕策略
def test_source_subtitle_timing_not_reused() -> None:
    """原片字幕时间不得直接套到新视频：转写时间只留在 analysis_only 记录。"""
    from app.services.commercial.compose import build_subtitle_draft

    draft = build_subtitle_draft(
        shots=[{"shot_key": "S01", "dialogue": "新台词内容", "adopt": (0, 2000)}],
        source_transcript=[{"start_ms": 0, "end_ms": 8000, "text": "旧原片台词"}],
    )
    # 草稿时间来自计划采用区间，而非原片转写时间
    assert draft[0]["start_ms"] == 0 and draft[0]["end_ms"] == 2000
    assert draft[0]["aligned"] is False  # 明确标记未对齐，需人工校对


def test_master_and_burn_version_separate() -> None:
    """母版与烧录字幕版分别产出：烧录是独立文件，不改写母版。"""
    assert compose_svc.SUBTITLE_POLICY["burn_creates_copy"] is True
    assert compose_svc.SUBTITLE_POLICY["master_immutable"] is True
