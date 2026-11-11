"""商业域 Pydantic/数据类契约（任务书 §5/§8/§14.3）。

金额一律 Decimal；时间单位以 _ms 明示；VideoGenerationInput 在构造层
强制 INV-01：原参考视频及其地址、关键帧、原音色一律不得出现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------- 解析域（T03/T04 用）


class AnalysisSchemaInvalid(Exception):
    """解析输出不满足结构化 Schema（截断、时间越界、缺字段）。"""

    code = "ANALYSIS_SCHEMA_INVALID"


@dataclass(frozen=True)
class AnalysisShot:
    """原片一个镜头的时间码记录（事实，非模板）。"""

    shot_id: str
    start_ms: int
    end_ms: int
    keyframe_hints_ms: list[int] = field(default_factory=list)
    observation: str = ""
    inference: str = ""
    uncertainty: str = ""


@dataclass(frozen=True)
class AnalysisResult:
    """Gemini 解析的结构化输出（schema_version 1.0 子集）。"""

    source_id: int
    duration_ms: int
    shots: list[AnalysisShot]
    transcript: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[dict[str, Any]] = field(default_factory=list)
    raw_model_id: str = ""

    def validate(self) -> None:
        if self.duration_ms <= 0:
            raise AnalysisSchemaInvalid("duration_ms 必须为正")
        for shot in self.shots:
            if shot.start_ms < 0 or shot.end_ms <= shot.start_ms:
                raise AnalysisSchemaInvalid(f"镜头 {shot.shot_id} 时间区间非法")
            if shot.end_ms > self.duration_ms:
                raise AnalysisSchemaInvalid(f"镜头 {shot.shot_id} 越出原片时长")
            for ts in shot.keyframe_hints_ms:
                if ts < shot.start_ms or ts > shot.end_ms:
                    raise AnalysisSchemaInvalid(f"镜头 {shot.shot_id} 关键帧时间越界")
        # 主序列不允许倒序（按 start 排序后应与原顺序一致）
        starts = [s.start_ms for s in self.shots]
        if starts != sorted(starts):
            raise AnalysisSchemaInvalid("镜头序列存在倒序")


# ---------------------------------------------------------------- 生成域（T03/T07 用）

# INV-01：生成输入禁止出现原片身份字段
FORBIDDEN_GENERATION_FIELDS: frozenset[str] = frozenset({
    "source_video_url", "source_video_id", "source_video_asset_id",
    "source_frame_url", "source_frame_asset_id", "reference_source_audio_url",
    "original_actor_voice_url",
})


class GenerationInputError(Exception):
    """生成输入违反不变量（含原片字段/未映射声音/非法分辨率）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VideoGenerationInput:
    """单次 H3 生成请求的内部输入（任务书 §8.4 字段集）。"""

    team_id: int | None
    production_id: int
    generation_unit_id: int
    attempt_id: str
    model_id: str
    actor_image_asset_ids: tuple[int, ...] = ()
    product_image_asset_ids: tuple[int, ...] = ()
    scene_image_asset_ids: tuple[int, ...] = ()
    voice_reference_asset_ids: tuple[int, ...] = ()
    prompt: str = ""
    approved_dialogue: str = ""
    resolution_id: str = ""
    duration_ms: int = 0
    aspect_ratio: str = "9:16"
    audio_required: bool = True
    optional_seed: int | None = None

    def __post_init__(self) -> None:
        # INV-01：任何原片字段试图进入生成输入都在构造层失败
        present = FORBIDDEN_GENERATION_FIELDS & set(self.__dict__.keys())
        if present:  # pragma: no cover - frozen dataclass 正常不会带入
            raise GenerationInputError(
                "SOURCE_REFERENCE_FORBIDDEN", f"生成输入包含禁止字段：{sorted(present)}"
            )
        if self.audio_required and not self.voice_reference_asset_ids:
            raise GenerationInputError(
                "VOICE_BINDING_INVALID", "要求口播音频但未绑定我方授权音色参考"
            )
        if not self.prompt.strip():
            raise GenerationInputError("PROMPT_EMPTY", "生成提示词为空")


@dataclass(frozen=True)
class CostQuote:
    """报价快照（任务书 §10.2 字段子集；金额 Decimal 原币）。"""

    quote_id: str
    provider_id: str
    model_id: str
    request_fingerprint: str
    requested_duration_ms: int
    resolution_id: str
    currency: str = "USD"
    estimated_amount: Decimal = Decimal("0")
    is_estimated: bool = True
    price_source: str = "unknown"
    created_at: datetime | None = None
    expires_at: datetime | None = None
    provider_payload_redacted: dict[str, Any] = field(default_factory=dict)

# ---------------------------------------------------------------------------
# 复刻分析与脚本契约（Gemini fixture / API 共用）
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ProductPresence(str, Enum):
    required = "required"
    optional = "optional"
    absent = "absent"
    unknown = "unknown"


class ShotGraphShot(BaseModel):
    """一个可核对的 Shot Graph 节点。

    ``start``/``end`` 是对外契约字段，兼容数据库及旧 Gemini 输出的
    ``start_ms``/``end_ms`` 输入。所有时间均为毫秒。
    """

    model_config = ConfigDict(extra="allow")

    shot_key: str = Field(min_length=1, max_length=96)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    purpose: str = ""
    camera: Any = Field(default_factory=dict)
    composition: Any = Field(default_factory=dict)
    action: Any = Field(default_factory=dict)
    emotion: Any = Field(default_factory=dict)
    product_presence: ProductPresence = ProductPresence.unknown
    product_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    product_evidence: list[Any] = Field(default_factory=list)
    anchor_candidates: list[Any] = Field(default_factory=list)
    source_span: Any = Field(default_factory=dict)
    review_status: str = "approved"

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_time_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if "start" not in value and "start_ms" in value:
            value["start"] = value["start_ms"]
        if "end" not in value and "end_ms" in value:
            value["end"] = value["end_ms"]
        for target, legacy in (
            ("camera", "camera_json"),
            ("composition", "composition_json"),
            ("action", "action_json"),
            ("emotion", "emotion_json"),
            ("product_evidence", "product_evidence_json"),
            ("anchor_candidates", "anchor_candidates_json"),
            ("source_span", "source_span_json"),
        ):
            if target not in value and legacy in value:
                value[target] = value[legacy]
        return value

    @model_validator(mode="after")
    def _validate_time_and_review(self) -> "ShotGraphShot":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.product_confidence < 0.7 or self.product_presence is ProductPresence.unknown:
            self.review_status = "needs_human_review"
        return self

    @property
    def start_ms(self) -> int:
        return self.start

    @property
    def end_ms(self) -> int:
        return self.end


class ShotGraphPayload(BaseModel):
    """Gemini 输出的版本化 Shot Graph。"""

    model_config = ConfigDict(extra="allow")

    shots: list[ShotGraphShot] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)
    source_id: int | None = None
    schema_version: str = "1.0"
    uncertainties: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ShotGraphPayload":
        if self.shots:
            maximum = max(shot.end for shot in self.shots)
            if self.duration_ms <= 0:
                self.duration_ms = maximum
            if maximum > self.duration_ms:
                raise ValueError("shot end exceeds duration_ms")
            starts = [shot.start for shot in self.shots]
            if starts != sorted(starts):
                raise ValueError("shots must be ordered by start")
        elif self.duration_ms <= 0:
            raise ValueError("duration_ms must be positive when shots are empty")
        return self


class ScriptVersionPayload(BaseModel):
    """单镜脚本版本契约，写入 ``CvScriptVersion.script_json``。"""

    model_config = ConfigDict(extra="allow")

    mode: str = Field(default="structural_rewrite", pattern="^(structural_rewrite|high_fidelity)$")
    dialogue: str = ""
    visual_prompt: str = ""
    action_prompt: str = ""
    product_presence: ProductPresence = ProductPresence.unknown
    claim_ids: list[str] = Field(default_factory=list)
    duration_ms: int = Field(gt=0)
    CTA: str = Field(default="", validation_alias=AliasChoices("CTA", "cta"))
    shot_key: str = ""

    @property
    def cta(self) -> str:
        return self.CTA


class ScriptBatchPayload(BaseModel):
    """脚本 API 可一次提交多个镜头版本。"""

    mode: str = Field(default="structural_rewrite", pattern="^(structural_rewrite|high_fidelity)$")
    scripts: list[ScriptVersionPayload] = Field(default_factory=list)


