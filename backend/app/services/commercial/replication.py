"""复刻项目状态和报价接受的确定性规则。"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas_commercial import ScriptVersionPayload


class InvalidReplicationTransition(ValueError):
    pass


class QuoteStateError(ValueError):
    pass


REPLICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"analyzing", "cancelled"}),
    "analyzing": frozenset({"analyzed", "failed", "cancelled"}),
    "analyzed": frozenset({"script_review", "failed", "cancelled"}),
    "script_review": frozenset({"anchor_review", "failed", "cancelled"}),
    "anchor_review": frozenset({"voice_ready", "failed", "cancelled"}),
    "voice_ready": frozenset({"preview_ready", "failed", "cancelled"}),
    "preview_ready": frozenset({"finalizing", "failed", "cancelled"}),
    "finalizing": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"analyzing", "cancelled"}),
    "cancelled": frozenset(),
}

QUOTE_STATES = frozenset({"draft", "pending_user_acceptance", "accepted", "expired", "settled", "disputed"})


def transition_status(current: str, target: str) -> str:
    if target not in REPLICATION_TRANSITIONS.get(current, frozenset()):
        raise InvalidReplicationTransition(f"不允许从 {current} 转移到 {target}")
    return target


def accept_quote(status: str) -> str:
    if status != "pending_user_acceptance":
        raise QuoteStateError("只有待用户确认的报价可以接受")
    return "accepted"

class ScriptContractError(ValueError):
    """结构化脚本不满足商品或镜头时长契约。"""

    code = "SCRIPT_CONTRACT_INVALID"


def extract_catalog_claim_ids(catalog: Any) -> set[str]:
    """提取商品目录中可用且审核通过的 claim_id。"""
    if isinstance(catalog, Mapping):
        if "claims" in catalog:
            catalog = catalog["claims"]
        else:
            return {str(key) for key in catalog}
    ids: set[str] = set()
    for item in catalog or ():
        if isinstance(item, str):
            ids.add(item)
            continue
        if isinstance(item, Mapping) and item.get("claim_id") and item.get("approved", True):
            ids.add(str(item["claim_id"]))
    return ids


catalog_claim_ids = extract_catalog_claim_ids

def product_review_status(confidence: float | int | None, presence: str = "unknown") -> str:
    """低置信商品识别必须进入人工审核队列。"""
    try:
        score = float(confidence if confidence is not None else 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return "needs_human_review" if score < 0.7 or presence == "unknown" else "approved"


def validate_script_contract(
    script: ScriptVersionPayload,
    *,
    catalog_claim_ids: set[str] | list[Mapping[str, Any]] | Mapping[str, Any],
    locked_durations: Mapping[str, int] | None = None,
) -> ScriptVersionPayload:
    """校验 claim 来源及模式对应的镜头时长约束。"""
    available = extract_catalog_claim_ids(catalog_claim_ids)
    unknown = [claim_id for claim_id in script.claim_ids if claim_id not in available]
    if unknown:
        raise ScriptContractError(f"claim_id 不在商品目录：{unknown}")
    locked_durations = locked_durations or {}
    expected = locked_durations.get(script.shot_key) if script.shot_key else None
    if expected is not None:
        if script.mode == "high_fidelity":
            if script.duration_ms != int(expected):
                raise ScriptContractError(
                    f"高保真镜头 {script.shot_key} 必须锁定为 {expected}ms"
                )
        else:
            # 结构改写可以重写节奏，但防止超出原镜头两倍或短于一半。
            lower = max(1, int(expected * 0.5))
            upper = int(expected * 2.0)
            if not lower <= script.duration_ms <= upper:
                raise ScriptContractError(
                    f"结构改写镜头 {script.shot_key} 时长须在 {lower}–{upper}ms"
                )
    if script.duration_ms <= 0:
        raise ScriptContractError("duration_ms 必须为正")
    return script


def shot_graph_payload_to_records(payload: Any) -> list[dict[str, Any]]:
    """转换为 CvShotGraph 可直接持久化的 JSON 字段。"""
    shots = payload.shots if hasattr(payload, "shots") else payload.get("shots", [])
    records: list[dict[str, Any]] = []
    for shot in shots:
        item = shot.model_dump() if hasattr(shot, "model_dump") else dict(shot)
        records.append({
            "shot_key": item["shot_key"],
            "start_ms": int(item.get("start", item.get("start_ms", 0))),
            "end_ms": int(item.get("end", item.get("end_ms", 0))),
            "purpose": item.get("purpose", ""),
            "camera_json": item.get("camera", {}),
            "composition_json": item.get("composition", {}),
            "action_json": item.get("action", {}),
            "emotion_json": item.get("emotion", {}),
            "product_presence": str(item.get("product_presence", "unknown").value if hasattr(item.get("product_presence"), "value") else item.get("product_presence", "unknown")),
            "product_confidence": item.get("product_confidence", 0.0),
            "product_evidence_json": item.get("product_evidence", []),
            "anchor_candidates_json": item.get("anchor_candidates", []),
            "source_span_json": item.get("source_span", {}),
            "status": "needs_human_review" if item.get("review_status") == "needs_human_review" else "active",
        })
    return records


def script_payload_to_json(script: ScriptVersionPayload) -> dict[str, Any]:
    data = script.model_dump()
    data["product_presence"] = getattr(script.product_presence, "value", script.product_presence)
    return data




