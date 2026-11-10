"""商品卖点与台词边界（§6.2 / G02）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models_commercial import CvProductVersion


class ClaimError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _claims(product: CvProductVersion) -> list[dict]:
    return list((product.claims if isinstance(product.claims, list) else []) or [])


def approved_claim_texts(product: CvProductVersion) -> list[str]:
    return [c["text"] for c in _claims(product) if c.get("approved")]


def validate_dialogue_claims(
    product: CvProductVersion, *, dialogue: str, used_claim_ids: list[str]
) -> None:
    """台词只能引用已审核卖点，且不得出现禁止表述。"""
    claims = {c.get("claim_id"): c for c in _claims(product)}
    for claim_id in used_claim_ids:
        claim = claims.get(claim_id)
        if claim is None or not claim.get("approved"):
            raise ClaimError(
                "CLAIM_NOT_APPROVED", f"卖点 {claim_id} 未审核通过，不能进入台词"
            )
    for phrase in (product.forbidden_phrases if isinstance(product.forbidden_phrases, list) else []) or []:
        if phrase and phrase in dialogue:
            raise ClaimError("CLAIM_FORBIDDEN_PHRASE", f"台词包含禁止表述：{phrase}")
