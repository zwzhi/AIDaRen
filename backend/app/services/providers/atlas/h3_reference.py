"""Atlas H3 Developer Reference-to-Video 适配器（草案映射，待真实契约验证）。

⚠️ 能力档案与字段映射来自任务书 §8.2 的公开文档路径与示例；在真实账号
联调通过并进入 commercial_verified_models 前，本适配器仅用于离线 Fixture
测试与请求构造，付费提交被 capability_verified 阻断（T01 机制）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.schemas_commercial import GenerationInputError, VideoGenerationInput


class ProviderRequestError(Exception):
    """上游错误状态/错误体；不得被当作任务成功。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class H3Capabilities:
    """生成端能力档案（草案；verified=False 时付费路径拒绝）。"""

    duration_min_ms: int
    duration_max_ms: int
    duration_step_ms: int
    resolutions: frozenset[str]
    aspect_ratios: frozenset[str]
    audio_supported: bool
    voice_reference_supported: bool
    capability_verified: bool = False
    capability_version: str = "draft-2026-11-10"


# 草案能力：以任务书示例（最小 5s、G06 场景）初始化，待 T03 真实联调核实替换
DRAFT_H3_CAPABILITIES = H3Capabilities(
    duration_min_ms=5_000,
    duration_max_ms=10_000,
    duration_step_ms=1_000,
    resolutions=frozenset({"480p", "720p", "1080p"}),
    aspect_ratios=frozenset({"9:16", "16:9", "1:1"}),
    audio_supported=True,
    voice_reference_supported=True,
    capability_verified=False,
)

# 内部输入字段 → 上游请求键的显式映射；未列出的内部字段不得静默丢弃
_FIELD_MAPPING: dict[str, str] = {
    "model_id": "model",
    "prompt": "prompt",
    "approved_dialogue": "dialogue",
    "resolution_id": "resolution",
    "duration_ms": "duration_ms",
    "aspect_ratio": "aspect_ratio",
    "optional_seed": "seed",
    "actor_image_asset_ids": "subject_image_asset_ids",
    "product_image_asset_ids": "product_image_asset_ids",
    "scene_image_asset_ids": "scene_image_asset_ids",
    "voice_reference_asset_ids": "voice_reference_asset_ids",
    "audio_required": "audio_enabled",
}


def validate_request(request: VideoGenerationInput, caps: H3Capabilities) -> None:
    """按能力档案校验；违反即拒绝，绝不静默升降档。"""
    if request.resolution_id not in caps.resolutions:
        raise GenerationInputError(
            "PROVIDER_RESOLUTION_UNSUPPORTED",
            f"分辨率 {request.resolution_id} 不受当前端点支持，可选：{sorted(caps.resolutions)}",
        )
    if request.aspect_ratio not in caps.aspect_ratios:
        raise GenerationInputError(
            "PROVIDER_ASPECT_UNSUPPORTED",
            f"画幅 {request.aspect_ratio} 不受当前端点支持",
        )
    if request.audio_required and not caps.audio_supported:
        raise GenerationInputError("PROVIDER_AUDIO_UNSUPPORTED", "当前端点不支持音频输出")
    if request.voice_reference_asset_ids and not caps.voice_reference_supported:
        raise GenerationInputError("VOICE_BINDING_INVALID", "当前端点不支持音色参考字段")
    if not (caps.duration_min_ms <= request.duration_ms <= caps.duration_max_ms):
        raise GenerationInputError(
            "PROVIDER_DURATION_UNSUPPORTED",
            f"时长 {request.duration_ms}ms 超出端点支持 "
            f"[{caps.duration_min_ms},{caps.duration_max_ms}]ms",
        )
    if request.duration_ms % caps.duration_step_ms:
        raise GenerationInputError(
            "PROVIDER_DURATION_STEP",
            f"时长 {request.duration_ms}ms 不符合步长 {caps.duration_step_ms}ms",
        )


def build_h3_request(request: VideoGenerationInput, caps: H3Capabilities) -> dict[str, Any]:
    """内部输入 → 上游请求体（显式映射，未知字段拒绝而非丢弃）。"""
    validate_request(request, caps)
    payload: dict[str, Any] = {
        _FIELD_MAPPING["model_id"]: request.model_id,
        _FIELD_MAPPING["prompt"]: request.prompt,
        _FIELD_MAPPING["approved_dialogue"]: request.approved_dialogue,
        _FIELD_MAPPING["resolution_id"]: request.resolution_id,
        _FIELD_MAPPING["duration_ms"]: request.duration_ms,
        _FIELD_MAPPING["aspect_ratio"]: request.aspect_ratio,
        _FIELD_MAPPING["audio_required"]: request.audio_required,
        _FIELD_MAPPING["actor_image_asset_ids"]: list(request.actor_image_asset_ids),
        _FIELD_MAPPING["product_image_asset_ids"]: list(request.product_image_asset_ids),
        _FIELD_MAPPING["voice_reference_asset_ids"]: list(request.voice_reference_asset_ids),
    }
    if request.scene_image_asset_ids:
        payload[_FIELD_MAPPING["scene_image_asset_ids"]] = list(request.scene_image_asset_ids)
    if request.optional_seed is not None:
        payload[_FIELD_MAPPING["optional_seed"]] = request.optional_seed
    # INV-01 兜底：请求体任何键值不得包含原片地址/标识
    serialized = str(payload)
    for banned in ("source_video", "source_frame", "reference_source"):
        if banned in serialized:
            raise GenerationInputError("SOURCE_REFERENCE_FORBIDDEN", f"请求体包含禁止字段 {banned}")
    return payload


@dataclass(frozen=True)
class ProviderTaskResult:
    """上游任务状态映射结果。"""

    prediction_id: str
    status: str  # queued | running | succeeded | failed
    output_urls: tuple[str, ...] = ()
    error: str | None = None
    raw_status: str = ""


def map_prediction(payload: dict[str, Any]) -> ProviderTaskResult:
    """把 Atlas prediction 响应映射为内部状态；错误体绝不判成功。"""
    if isinstance(payload.get("error"), (dict, str)):
        message = payload["error"]
        if isinstance(message, dict):
            message = str(message.get("message") or message)
        return ProviderTaskResult(
            prediction_id=str(payload.get("id") or ""),
            status="failed",
            error=str(message),
            raw_status=str(payload.get("status") or ""),
        )
    raw_status = str(payload.get("status") or "").strip().lower()
    if raw_status in {"succeeded", "success", "completed"}:
        outputs = payload.get("output") or payload.get("outputs") or []
        if isinstance(outputs, str):
            outputs = [outputs]
        urls = tuple(str(u) for u in outputs if str(u).startswith("https://"))
        if not urls:
            # 成功但无输出 URL：仍算 succeeded，由下载阶段处理（OUTPUT_PENDING_DOWNLOAD）
            return ProviderTaskResult(prediction_id=str(payload.get("id") or ""), status="succeeded", raw_status=raw_status)
        return ProviderTaskResult(
            prediction_id=str(payload.get("id") or ""), status="succeeded",
            output_urls=urls, raw_status=raw_status,
        )
    if raw_status in {"failed", "error", "canceled", "cancelled"}:
        return ProviderTaskResult(
            prediction_id=str(payload.get("id") or ""), status="failed",
            error=str(payload.get("error") or "上游任务失败"), raw_status=raw_status,
        )
    return ProviderTaskResult(
        prediction_id=str(payload.get("id") or ""),
        status="running" if raw_status else "queued",
        raw_status=raw_status or "unknown",
    )


async def submit_generation(
    body: dict[str, Any], *, base_url: str, api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """提交生成；返回 prediction_id（错误状态抛异常）。"""
    url = f"{base_url}/api/v1/model/generateVideo"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=15.0), transport=transport,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            raise ProviderRequestError(resp.status_code, resp.text[:500])
        payload = resp.json()
        prediction_id = str(payload.get("id") or payload.get("prediction_id") or "").strip()
        if not prediction_id:
            raise ProviderRequestError(resp.status_code, "上游未返回任务 ID（SUBMIT_RESULT_UNKNOWN 需人工对账）")
        return prediction_id


async def poll_prediction(
    prediction_id: str, *, base_url: str, api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderTaskResult:
    url = f"{base_url}/api/v1/model/prediction/{prediction_id}"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0), transport=transport,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        resp = await client.get(url)
        if resp.status_code >= 400:
            raise ProviderRequestError(resp.status_code, resp.text[:500])
        return map_prediction(resp.json())
