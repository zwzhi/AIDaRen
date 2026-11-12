"""Fixture-first Image2.6 image-edit adapter for approved anchor workflows."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, Mapping

import httpx


class ImageEditInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ImageEditCapabilityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ImageEditCapabilities:
    model_id: str
    model_version: str = "fixture-1"
    capability_verified: bool = False
    supports_anchor_reference: bool = True
    supports_actor_reference: bool = True
    supports_product_reference: bool = True
    probe_status: str = "unverified"
    probe_source: str | None = None
    probe_error: str | None = None


@dataclass(frozen=True)
class ImageEditRequest:
    source_anchor: Mapping[str, Any]
    actor_version: Mapping[str, Any]
    product_version: Mapping[str, Any] | None
    product_presence: str
    prompt: str


@dataclass(frozen=True)
class ImageEditResult:
    status: str
    review_status: str
    needs_human_review: bool
    parent_anchor_id: int
    source_asset_id: int
    actor_version_id: int
    product_version_id: int | None
    model_id: str
    model_version: str
    prompt_hash: str
    edited_asset_payload: dict[str, Any]
    h3_eligible: bool = False


class ImageEditAdapter:
    def __init__(
        self,
        *,
        model_id: str = "image2.6-sandbox",
        mode: str = "fixture",
        capabilities: ImageEditCapabilities | None = None,
        base_url: str = "",
        api_key: str = "",
    ) -> None:
        self.model_id = model_id
        self.mode = mode
        self.base_url = base_url
        self.api_key = api_key
        self.capabilities = capabilities or ImageEditCapabilities(model_id=model_id)

    @classmethod
    def from_fixture(cls, fixture: Mapping[str, Any] | None = None) -> "ImageEditAdapter":
        fixture = dict(fixture or {})
        return cls(
            model_id=str(fixture.get("model_id") or "image2.6-sandbox"),
            mode="fixture",
            capabilities=ImageEditCapabilities(
                model_id=str(fixture.get("model_id") or "image2.6-sandbox"),
                model_version=str(fixture.get("model_version") or "fixture-1"),
                capability_verified=False,
            ),
        )

    def probe_capabilities(self, real: bool = False, *, transport: httpx.AsyncBaseTransport | None = None) -> ImageEditCapabilities | Any:
        return self.probe(real=real, transport=transport)

    def probe(self, real: bool = False, *, transport: httpx.AsyncBaseTransport | None = None) -> ImageEditCapabilities | Any:
        """Return fixture capabilities or an awaitable read-only real probe."""
        if not real:
            return self.capabilities
        return self._probe_real(transport=transport)

    async def _probe_real(self, *, transport: httpx.AsyncBaseTransport | None = None) -> ImageEditCapabilities:
        caps = self.capabilities
        if not self.base_url:
            result = replace(caps, capability_verified=False, probe_status="failed",
                             probe_source="local", probe_error="base_url is not configured")
            self.capabilities = result
            return result
        from app.config import get_settings
        settings = get_settings()
        path = str(getattr(settings, "atlas_capabilities_path", "/api/v1/model/capabilities") or "/api/v1/model/capabilities")
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    float(getattr(settings, "commercial_probe_timeout_sec", 20.0)),
                    connect=float(getattr(settings, "commercial_probe_connect_timeout_sec", 10.0)),
                ), transport=transport, headers=headers,
            ) as client:
                response = await client.get(url, params={"model": self.model_id})
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            payload = response.json()
            if isinstance(payload.get("data"), dict):
                payload = dict(payload["data"])
            if isinstance(payload.get("capabilities"), dict):
                payload = dict(payload["capabilities"])
            if not isinstance(payload, dict):
                raise ValueError("capability response must be an object")
            response_model = str(payload.get("model") or payload.get("model_id") or self.model_id).strip()
            explicit_verified = bool(payload.get("capability_verified") is True or payload.get("verified") is True)
            if self.model_id and response_model and response_model != self.model_id:
                explicit_verified = False
            result = replace(
                caps,
                model_version=str(payload.get("model_version") or payload.get("version") or caps.model_version),
                capability_verified=explicit_verified,
                supports_anchor_reference=bool(payload.get("supports_anchor_reference", caps.supports_anchor_reference)),
                supports_actor_reference=bool(payload.get("supports_actor_reference", caps.supports_actor_reference)),
                supports_product_reference=bool(payload.get("supports_product_reference", caps.supports_product_reference)),
                probe_status="verified" if explicit_verified else "unverified",
                probe_source="http-capabilities",
                probe_error=None,
            )
        except Exception as exc:
            result = replace(caps, capability_verified=False, probe_status="failed",
                             probe_source="http-capabilities", probe_error=str(exc)[:500])
        self.capabilities = result
        return result

    def edit_anchor(self, request: ImageEditRequest) -> ImageEditResult:
        caps = self.probe_capabilities()
        if self.mode == "real" and not caps.capability_verified:
            raise ImageEditCapabilityError("MODEL_CAPABILITY_UNVERIFIED", "Image2.6 能力尚未验证")
        source = dict(request.source_anchor)
        actor = dict(request.actor_version)
        product = dict(request.product_version or {})
        product_presence = request.product_presence
        if product_presence == "absent" and product:
            raise ImageEditInputError("PRODUCT_INPUT_FORBIDDEN", "商品为 absent 时不能提交商品参考")
        if product_presence == "required" and not product:
            raise ImageEditInputError("PRODUCT_REFERENCE_REQUIRED", "商品为 required 时必须提交商品参考")
        parent_anchor_id = int(source.get("id") or 0)
        source_asset_id = int(source.get("source_asset_id") or 0)
        actor_version_id = int(actor.get("id") or 0)
        product_version_id = int(product["id"]) if product else None
        if not parent_anchor_id or not source_asset_id or not actor_version_id:
            raise ImageEditInputError("ANCHOR_INPUT_INVALID", "源锚帧和达人版本信息不完整")
        prompt_hash = hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()
        needs_review = product_presence == "unknown"
        return ImageEditResult(
            status="anchor_candidate",
            review_status="needs_human_review" if needs_review else "pending",
            needs_human_review=needs_review,
            parent_anchor_id=parent_anchor_id,
            source_asset_id=source_asset_id,
            actor_version_id=actor_version_id,
            product_version_id=product_version_id,
            model_id=caps.model_id,
            model_version=caps.model_version,
            prompt_hash=prompt_hash,
            edited_asset_payload={
                "source_role": "source_derived_anchor_candidate",
                "derived_from_asset_id": source_asset_id,
                "shot_key": source.get("shot_key"),
                "time_ms": source.get("time_ms"),
                "product_presence": product_presence,
                "prompt_hash": prompt_hash,
            },
            h3_eligible=False,
        )
