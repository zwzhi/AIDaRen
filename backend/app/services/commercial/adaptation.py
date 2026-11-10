"""文案适配器（§6.3）：只吃模板文本与我方资料，产出可审核计划草稿。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import CvTemplateVersion

if TYPE_CHECKING:
    from app.models_commercial import CvProductVersion

Adaptor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# 商品形态 → 动作适配提示（无法机械适配时返回 inapplicable，交给人工）
_FORM_ACTION_HINTS: dict[str, str] = {
    "贴片": "取一片贴于手背内侧，轻压展示贴合度与贴片延展性",
    "瓶装": "拧开瓶盖倒少量于掌心，摊开手掌展示质地流动性",
    "盒装": "打开盒盖取出内容物，正面朝向镜头逐件展示",
}


class AdaptationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def adapt_action_for_form(*, template_action: str, product_form: str) -> dict[str, str]:
    """按商品形态适配模板展示动作；适配不了就明确不适用，不原样套用。"""
    hint = _FORM_ACTION_HINTS.get((product_form or "").strip())
    if hint is None:
        return {"status": "inapplicable", "action": "", "reason": f"暂无「{product_form}」形态的适配动作，需人工校准"}
    return {"status": "adapted", "action": hint}


def flag_new_facts(draft: dict[str, Any], product: CvProductVersion) -> list[dict[str, Any]]:
    """标记台词中不属于审核卖点的新增内容（claim_id=None → 待人工审核）。

    判定方式：从台词中剔除已审核卖点文本与标点后，若仍残留实质内容
    （≥4 个非标点字符），说明出现了新事实，需要人工确认。
    """
    import re

    from app.services.commercial.products import approved_claim_texts

    approved = [t for t in approved_claim_texts(product) if t]
    flagged: list[dict[str, Any]] = []
    for shot in draft.get("shots") or []:
        dialogue = str(shot.get("dialogue") or "").strip()
        if not dialogue:
            continue
        residual = dialogue
        for text in approved:
            residual = residual.replace(text, "")
        residual = re.sub(r"[\s，。！？、,.!?~～了的地得吗呢吧呀啊哦]", "", residual)
        if len(residual) >= 4:
            flagged.append({
                "shot_key": shot.get("shot_key"), "claim_id": None,
                "text": dialogue[:60],
                "reason": "台词包含审核卖点之外的新内容，需人工确认事实来源",
            })
    return flagged


def _build_adaptor_input(
    *, structure: dict[str, Any], product: CvProductVersion,
    marketing_goal: str, user_locked_dialogue: dict[str, str] | None,
) -> dict[str, Any]:
    """适配输入：只有模板文本结构 + 我方商品资料（附录 A.3 规则）。"""
    from app.services.commercial.products import approved_claim_texts

    return {
        "template": {
            "shots": [
                {
                    "shot_key": s.get("shot_id") or s.get("shot_key"),
                    "purpose": s.get("observation") or s.get("inference") or "",
                    "dialogue_template": s.get("dialogue_template") or "",
                    "action_template": s.get("action_template") or "",
                    "source_range_ms": [s.get("start_ms"), s.get("end_ms")],
                }
                for s in structure.get("shots") or []
            ],
            "variables": list(structure.get("variables") or []),
        },
        "product": {
            "name": "",
            "form": product.form,
            "claims": [
                {"claim_id": c.get("claim_id"), "text": c.get("text")}
                for c in (product.claims if isinstance(product.claims, list) else [])
                if c.get("approved")
            ],
            "forbidden_phrases": list(product.forbidden_phrases or []),
            "allowed_actions": list(product.allowed_actions or []),
        },
        "marketing_goal": marketing_goal,
        "dialogue_locked": user_locked_dialogue is not None,
        "user_locked_dialogue": dict(user_locked_dialogue or {}),
    }


async def adapt_template(
    db: AsyncSession, *, template_version_id: int, product: CvProductVersion,
    marketing_goal: str, user_locked_dialogue: dict[str, str] | None,
    adaptor: Adaptor,
) -> dict[str, Any]:
    """按已发布模板为我方商品适配文案与动作。

    - 输入不含原片任何形态（调用方可断言 captured 请求，见测试）；
    - 台词锁定时模型改写被丢弃，回填用户定稿；
    - 新事实/形态不适配标记 pending_review，不静默通过。
    """
    version = await db.get(CvTemplateVersion, template_version_id)
    if version is None or version.status != "published":
        raise AdaptationError("TEMPLATE_NOT_PUBLISHED", "模板版本未发布或已撤销")
    structure = dict(version.structure_json or {})
    raw = await adaptor(_build_adaptor_input(
        structure=structure, product=product,
        marketing_goal=marketing_goal, user_locked_dialogue=user_locked_dialogue,
    ))

    shots_out: list[dict[str, Any]] = []
    template_shots = structure.get("shots") or []
    raw_by_key = {str(s.get("shot_key")): s for s in raw.get("shots") or []}
    dialogue_locked = user_locked_dialogue is not None
    for shot in template_shots:
        key = str(shot.get("shot_id") or shot.get("shot_key"))
        candidate = raw_by_key.get(key, {})
        dialogue = str(candidate.get("dialogue") or "")
        if dialogue_locked:
            if key in (user_locked_dialogue or {}):
                dialogue = user_locked_dialogue[key]  # 定稿台词不得被改写
        action = str(candidate.get("action") or "")
        action_adapted = adapt_action_for_form(
            template_action=str(shot.get("action_template") or ""),
            product_form=product.form,
        )
        if action_adapted["status"] == "adapted" and (not action or "瓶盖" in action and product.form != "瓶装"):
            action = action_adapted["action"]
        shots_out.append({
            "shot_key": key,
            "dialogue": dialogue,
            "action": action,
            "target_duration_ms": int(shot.get("end_ms", 0)) - int(shot.get("start_ms", 0)),
            "action_adaptation": action_adapted["status"],
        })

    return {
        "template_version_id": template_version_id,
        "product_version_id": product.id,
        "dialogue_locked": dialogue_locked,
        "shots": shots_out,
        "pending_review": flag_new_facts({"shots": shots_out}, product),
    }
