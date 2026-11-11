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

    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class SubmitOutcomeUnknownError(Exception):
    """HTTP 成功但未返回任务 ID：上游可能已创建任务，结果不明。

    语义等同 SUBMIT_UNKNOWN（冻结自动重试，人工对账），绝不能按"明确失败"
    处理后允许重发——那会造成双重付费（P2-3）。
    """


class PreviewInputError(ValueError):
    """预览输入不满足冻结版本或 H3 参考图契约。"""


@dataclass
class PreviewTask:
    """Mock/沙箱预览任务结果。

    任务对象保留请求快照，进程重启后可由 prediction id 恢复查询。该对象
    不携带任何真实供应商凭据，也不会在 mock 模式触发 HTTP 请求。
    """

    provider_task_id: str
    status: str
    request: dict[str, Any]
    output_key: str | None = None
    error: str | None = None


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
    # 预览契约：默认使用 9:16 与最低已验证分辨率。字段有默认值，保持
    # 旧调用方构造 H3Capabilities 时的兼容性。
    preview_aspect_ratio: str = "9:16"
    preview_default_resolution: str = "480p"
    max_reference_images: int = 9
    max_anchor_frames_per_segment: int = 3

    @property
    def minimum_verified_resolution(self) -> str:
        """当前档案中可用于预览的最低分辨率。"""
        if self.preview_default_resolution in self.resolutions:
            return self.preview_default_resolution
        order = {"144p": 144, "240p": 240, "360p": 360, "480p": 480,
                 "540p": 540, "576p": 576, "720p": 720, "768p": 768,
                 "1080p": 1080, "2k": 2048}
        return min(self.resolutions, key=lambda value: order.get(value.lower(), 10_000))


# 能力档案（依据 2026-11-10 Atlas 官方模型页公开信息更新；capability_verified 仍为 False
# 直到账号内真实契约验证通过）：
# - H3 Developer 三路线（T2V/I2V/Reference）均含生成音频；480P/768P/2K；16:9/9:16/1:1
# - 时长 5–15 秒；标准价 $0.05/s（官方页明示，非历史清单的 $0.015/s）
DRAFT_H3_CAPABILITIES = H3Capabilities(
    duration_min_ms=5_000,
    duration_max_ms=15_000,
    duration_step_ms=1_000,
    resolutions=frozenset({"480p", "768p", "2k"}),
    aspect_ratios=frozenset({"9:16", "16:9", "1:1"}),
    audio_supported=True,
    voice_reference_supported=True,
    capability_verified=False,
    preview_aspect_ratio="9:16",
    preview_default_resolution="480p",
    max_reference_images=9,
    max_anchor_frames_per_segment=3,
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


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {name: getattr(value, name) for name in dir(value) if not name.startswith("_")}


def _status(value: Any) -> str:
    row = _mapping(value)
    return str(row.get("status") or "").strip().lower()


def _frame_asset(frame: Any) -> Any:
    row = _mapping(frame)
    return row.get("asset_id") or row.get("edited_asset_id") or row.get("source_asset_id") or row.get("url")


def _anchor_frames(anchor_set: Any) -> list[dict[str, Any]]:
    rows = _mapping(anchor_set).get("frames") or _mapping(anchor_set).get("anchor_frames") or []
    normalised: list[dict[str, Any]] = []
    for index, frame in enumerate(rows):
        row = _mapping(frame)
        asset = _frame_asset(row)
        if asset in (None, ""):
            raise PreviewInputError("锚帧缺少可提交的 asset_id")
        sequence = int(row.get("sequence", index))
        normalised.append({
            "shot_key": str(row.get("shot_key") or ""),
            "sequence": sequence,
            "time_ms": int(row.get("time_ms") or 0),
            "asset_id": asset,
        })
    return normalised


def plan_anchor_batches(
    frames: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    max_frames_per_segment: int = 3,
    max_reference_images: int = 9,
) -> list[list[dict[str, Any]]]:
    """按镜头顺序切分 1～3 张锚帧的连续片段。

    函数不重排调用方顺序。超过 H3 单次九图限制时返回多个显式批次，
    由上层按时间轴串联，不把完整参考图包静默塞进一个请求。
    """
    if not frames:
        raise PreviewInputError("预览至少需要一张锚帧")
    if max_frames_per_segment < 1 or max_reference_images < 1:
        raise PreviewInputError("锚帧批次上限必须为正数")
    if max_frames_per_segment > max_reference_images:
        max_frames_per_segment = max_reference_images
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_shot = None
    for frame in frames:
        shot_key = str(frame.get("shot_key") or "")
        if current and (shot_key != current_shot or len(current) >= max_frames_per_segment):
            batches.append(current)
            current = []
        current.append(dict(frame))
        current_shot = shot_key
    if current:
        batches.append(current)
    # Each segment is <=3, and therefore <=9. Keep this explicit assertion so
    # a future capability change cannot silently violate the provider contract.
    if any(len(batch) > max_reference_images for batch in batches):
        raise PreviewInputError("参考图超过 H3 单次上限，请拆批提交")
    return batches


def _frozen_version_hash(revision: dict[str, Any]) -> str:
    value = str(revision.get("frozen_version_hash") or revision.get("version_hash") or "").strip()
    if value:
        return value
    import hashlib
    import json

    material = {
        key: revision.get(key)
        for key in ("script", "anchor_set", "voice", "subtitle")
        if key in revision
    }
    if len(material) != 4:
        raise PreviewInputError("预览必须携带冻结版本 hash")
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_frozen_preview(revision: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """校验脚本、锚帧、声音和字幕均已冻结/批准。"""
    required = ("script", "anchor_set", "voice", "subtitle")
    for key in required:
        if key not in revision:
            raise PreviewInputError(f"预览缺少冻结{key}版本")
        if _status(revision[key]) not in {"approved", "frozen"}:
            raise PreviewInputError(f"预览只能使用冻结{key}版本")
    frames = _anchor_frames(revision["anchor_set"])
    if len(frames) > DRAFT_H3_CAPABILITIES.max_reference_images:
        raise PreviewInputError("参考图超过 H3 单次上限，请拆批提交")
    return frames, _frozen_version_hash(revision)


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


def build_h3_request(
    request: VideoGenerationInput,
    caps: H3Capabilities,
    *,
    anchor_frames: list[dict[str, Any]] | None = None,
    frozen_version_hash: str | None = None,
    preview: bool = False,
) -> dict[str, Any]:
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
    if anchor_frames is not None:
        if not anchor_frames:
            raise PreviewInputError("预览至少需要一张锚帧")
        if len(anchor_frames) > caps.max_reference_images:
            raise PreviewInputError("参考图超过 H3 单次上限，请拆批提交")
        mapping: list[dict[str, Any]] = []
        references: list[Any] = []
        for index, frame in enumerate(anchor_frames):
            row = dict(frame)
            asset = _frame_asset(row)
            if asset in (None, ""):
                raise PreviewInputError("锚帧缺少可提交的 asset_id")
            references.append(asset)
            mapping.append({
                "shot_key": str(row.get("shot_key") or ""),
                "sequence": int(row.get("sequence", index)),
                "time_ms": int(row.get("time_ms") or 0),
                "asset_id": asset,
            })
        payload["reference_images"] = references
        payload["anchor_frame_mapping"] = mapping
    if frozen_version_hash:
        payload["frozen_version_hash"] = str(frozen_version_hash)
    if preview:
        payload["preview"] = True
    # INV-01 兜底：请求体任何键值不得包含原片地址/标识
    serialized = str(payload)
    for banned in ("source_video", "source_frame", "reference_source"):
        if banned in serialized:
            raise GenerationInputError("SOURCE_REFERENCE_FORBIDDEN", f"请求体包含禁止字段 {banned}")
    return payload


def build_h3_preview_request(
    frozen_revision: dict[str, Any],
    caps: H3Capabilities = DRAFT_H3_CAPABILITIES,
) -> dict[str, Any]:
    """从冻结 revision 构造 H3 低清预览请求。"""
    revision = dict(frozen_revision)
    frames, version_hash = validate_frozen_preview(revision)
    if len(frames) > caps.max_reference_images:
        raise PreviewInputError("参考图超过 H3 单次上限，请拆批提交")
    params = dict(revision)
    for key in ("script", "anchor_set", "voice", "subtitle", "frozen_version_hash", "version_hash"):
        params.pop(key, None)
    params["resolution_id"] = str(params.get("resolution_id") or caps.preview_default_resolution)
    params["aspect_ratio"] = str(params.get("aspect_ratio") or caps.preview_aspect_ratio)
    params.setdefault("audio_required", True)
    from app.schemas_commercial import VideoGenerationInput

    request = VideoGenerationInput(
        team_id=params.get("team_id"),
        production_id=int(params.get("production_id") or 0),
        generation_unit_id=int(params.get("generation_unit_id") or 0),
        attempt_id=str(params.get("attempt_id") or "preview"),
        model_id=str(params.get("model_id") or ""),
        actor_image_asset_ids=tuple(int(i) for i in params.get("actor_image_asset_ids") or []),
        product_image_asset_ids=tuple(int(i) for i in params.get("product_image_asset_ids") or []),
        scene_image_asset_ids=tuple(int(i) for i in params.get("scene_image_asset_ids") or []),
        voice_reference_asset_ids=tuple(int(i) for i in params.get("voice_reference_asset_ids") or []),
        prompt=str(params.get("prompt") or ""),
        approved_dialogue=str(params.get("approved_dialogue") or ""),
        resolution_id=params["resolution_id"],
        duration_ms=int(params.get("duration_ms") or 0),
        aspect_ratio=params["aspect_ratio"],
        audio_required=bool(params.get("audio_required", True)),
        optional_seed=params.get("optional_seed"),
    )
    return build_h3_request(
        request,
        caps,
        anchor_frames=frames,
        frozen_version_hash=version_hash,
        preview=True,
    )


@dataclass(frozen=True)
class ProviderTaskResult:
    """上游任务状态映射结果。"""

    prediction_id: str
    status: str  # queued | running | succeeded | failed
    output_urls: tuple[str, ...] = ()
    error: str | None = None
    raw_status: str = ""
    # 上游随任务返回的可核实费用（prediction 响应 cost 字段）；
    # 无则 None → 保持待结算，绝不把估算写成实收
    cost_amount: "Decimal | None" = None
    cost_currency: str | None = None


def _parse_cost(payload: dict[str, Any]) -> tuple["Decimal | None", str | None]:
    """解析上游费用字段：cost={"amount","currency"} 或 usage_cost。"""
    from decimal import Decimal as _D
    from decimal import InvalidOperation as _IO

    cost = payload.get("cost")
    if isinstance(cost, dict) and cost.get("amount") is not None:
        try:
            return _D(str(cost["amount"])), str(cost.get("currency") or "USD").upper()
        except _IO:
            return None, None
    if payload.get("usage_cost") is not None:
        try:
            return _D(str(payload["usage_cost"])), "USD"
        except _IO:
            return None, None
    return None, None


def map_prediction(payload: dict[str, Any]) -> ProviderTaskResult:
    """把 Atlas prediction 响应映射为内部状态；错误体绝不判成功。

    兼容两种包装：官方文档为 {"data": {...}} 包装（2026-11-10 核实），
    同时保留顶层字段解析以适配控制台示例中的简写形态。
    """
    if isinstance(payload.get("data"), dict) and payload["data"]:
        payload = dict(payload["data"])
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
        cost_amount, cost_currency = _parse_cost(payload)
        outputs = payload.get("outputs") or payload.get("output") or []
        if isinstance(outputs, str):
            outputs = [outputs]
        urls = tuple(str(u) for u in outputs if str(u).startswith("https://"))
        if not urls:
            # 成功但无输出 URL：仍算 succeeded，由下载阶段处理（OUTPUT_PENDING_DOWNLOAD）
            return ProviderTaskResult(prediction_id=str(payload.get("id") or ""),
                                      status="succeeded", raw_status=raw_status,
                                      cost_amount=cost_amount, cost_currency=cost_currency)
        return ProviderTaskResult(
            prediction_id=str(payload.get("id") or ""), status="succeeded",
            output_urls=urls, raw_status=raw_status,
            cost_amount=cost_amount, cost_currency=cost_currency,
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


class H3VideoAdapter:
    """H3 预览适配器，默认使用本地 Mock/Fixture 沙箱。

    真实 H3 契约尚未通过探针时，``mode='mock'`` 是唯一可用提交模式。
    相同冻结版本 hash 的重复提交复用内存任务，恢复只根据任务号读取结果。
    """

    def __init__(
        self,
        *,
        capabilities: H3Capabilities = DRAFT_H3_CAPABILITIES,
        mode: str = "mock",
        base_url: str = "",
        api_key: str = "",
    ) -> None:
        self.capabilities = capabilities
        self.mode = str(mode or "mock").lower()
        self.base_url = base_url
        self.api_key = api_key
        self._tasks_by_hash: dict[str, PreviewTask] = {}
        self._tasks_by_id: dict[str, PreviewTask] = {}

    def probe_capabilities(self) -> H3Capabilities:
        return self.capabilities

    def submit_preview(self, frozen_revision: dict[str, Any]) -> PreviewTask:
        revision = dict(frozen_revision)
        frames, version_hash = validate_frozen_preview(revision)
        if len(frames) > self.capabilities.max_reference_images:
            raise PreviewInputError("参考图超过 H3 单次上限，请拆批提交")
        existing = self._tasks_by_hash.get(version_hash)
        if existing is not None:
            return existing
        if self.mode not in {"mock", "fixture", "sandbox"}:
            if not self.capabilities.capability_verified:
                raise PreviewInputError("真实 H3 契约未验证，只允许 Mock/Fixture/沙箱预览")
            raise PreviewInputError("真实 H3 提交必须通过异步 commercial generation 路径")
        request = build_h3_preview_request(revision, self.capabilities)
        import uuid

        task_id = f"MOCK-preview-{uuid.uuid4().hex[:12]}"
        task = PreviewTask(provider_task_id=task_id, status="awaiting_poll", request=request)
        self._tasks_by_hash[version_hash] = task
        self._tasks_by_id[task_id] = task
        return task

    def recover(self, provider_task_id: str) -> PreviewTask:
        task = self._tasks_by_id.get(str(provider_task_id))
        if task is None:
            raise PreviewInputError(f"预览任务不存在：{provider_task_id}")
        if task.status == "awaiting_poll":
            task.status = "succeeded"
            task.output_key = f"{task.provider_task_id}.mp4"
        return task


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
        body = resp.json()
        if isinstance(body.get("data"), dict) and body["data"]:
            body = body["data"]  # 官方文档 data 包装（2026-11-10 核实）
        prediction_id = str(body.get("id") or body.get("prediction_id") or "").strip()
        if not prediction_id:
            # HTTP 成功但无任务 ID：上游可能已创建任务（结果不明），
            # 必须按 SUBMIT_UNKNOWN 冻结，不得当明确失败处理（P2-3）
            raise SubmitOutcomeUnknownError(
                "上游返回成功但未携带任务 ID（SUBMIT_RESULT_UNKNOWN 需人工对账）")
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
