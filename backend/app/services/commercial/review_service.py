"""逐镜人工质检（§15）：硬阻断项不抵消、历史只追加、N/A 边界。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import CvReview

if TYPE_CHECKING:
    from app.models_commercial import CvGenerationAttempt

REVIEW_DIMENSIONS: tuple[str, ...] = (
    "人物身份", "商品准确", "音色", "台词", "口型",
    "动作与画面", "模板表达", "技术输出",
)
# 阻断项：任一 FAIL 整体驳回，不允许用其他维度 PASS 抵消（§15.2）
BLOCKING_DIMENSIONS: frozenset[str] = frozenset({
    "人物身份", "商品准确", "音色", "台词", "口型",
})
Verdict = Union[str, tuple[str, str]]  # "PASS" 或 ("FAIL", "原因")


@dataclass(frozen=True)
class ReviewDecision:
    attempt_id: int
    overall: str  # REVIEW_APPROVED | REVIEW_REJECTED


def _normalize(verdict: Verdict) -> tuple[str, str]:
    if isinstance(verdict, tuple):
        return verdict[0], verdict[1]
    return verdict, ""


async def record_review(
    db: AsyncSession, attempt: CvGenerationAttempt, *,
    reviewer_id: int, dimensions: dict[str, Verdict],
    speech_required: bool = False,
) -> ReviewDecision:
    """记录一次审核（追加历史），并推进 attempt 状态。

    规则：
    - 任何阻断维度 FAIL → REVIEW_REJECTED；
    - 口型 N/A 仅对无口播镜头合法；要求口播时 N/A 视为规避 → 驳回；
    - 全部 PASS → REVIEW_APPROVED（GENERATED≠APPROVED 的最后一道门槛）。
    """
    rows: list[CvReview] = []
    overall_reject_reasons: list[str] = []
    for dim, verdict in dimensions.items():
        status, reason = _normalize(verdict)
        rows.append(CvReview(
            attempt_id=attempt.id, dimension=dim, verdict=status,
            reason=reason, reviewer_id=reviewer_id,
        ))
        if status == "FAIL" and dim in BLOCKING_DIMENSIONS:
            overall_reject_reasons.append(f"{dim}: {reason}" or dim)
        if status == "NOT_APPLICABLE" and dim == "口型" and speech_required:
            overall_reject_reasons.append("口型：要求口播的镜头不允许 N/A 规避")

    db.add_all(rows)
    overall = "REVIEW_REJECTED" if overall_reject_reasons else "REVIEW_APPROVED"
    attempt.status = overall
    if overall_reject_reasons:
        attempt.error_code = "REVIEW_REJECTED"
        attempt.error_message = "；".join(overall_reject_reasons)[:500]
    await db.flush()
    return ReviewDecision(attempt_id=attempt.id, overall=overall)
