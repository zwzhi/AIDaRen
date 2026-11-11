"""报价与生成共用的一份请求构造（§10.2：报价与提交条件必须一致）。

从同一份已确认制作计划参数构造 VideoGenerationInput 与上游请求体：
任何影响能力或费用的条件（模型/提示词/台词/图片/音色/分辨率/画幅/
时长/音轨）都进入同一映射，报价与生成不各自拼装。
"""
from __future__ import annotations

from typing import Any

from app.schemas_commercial import VideoGenerationInput
from app.services.providers.atlas.h3_reference import (
    H3Capabilities,
    PreviewInputError,
    build_h3_preview_request,
    build_h3_request,
)


class RequestBuildError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def build_generation_input(params: dict[str, Any]) -> VideoGenerationInput:
    """已确认计划参数 → 内部生成输入（构造层强制 INV-01/音色/分辨率校验）。"""
    try:
        return VideoGenerationInput(
            team_id=params.get("team_id"),
            production_id=int(params.get("production_id") or 0),
            generation_unit_id=int(params.get("generation_unit_id") or 0),
            attempt_id=str(params.get("attempt_id") or ""),
            model_id=str(params["model_id"]),
            actor_image_asset_ids=tuple(int(i) for i in params.get("actor_image_asset_ids") or []),
            product_image_asset_ids=tuple(int(i) for i in params.get("product_image_asset_ids") or []),
            scene_image_asset_ids=tuple(int(i) for i in params.get("scene_image_asset_ids") or []),
            voice_reference_asset_ids=tuple(int(i) for i in params.get("voice_reference_asset_ids") or []),
            prompt=str(params.get("prompt") or ""),
            approved_dialogue=str(params.get("approved_dialogue") or ""),
            resolution_id=str(params.get("resolution_id") or ""),
            duration_ms=int(params.get("duration_ms") or 0),
            aspect_ratio=str(params.get("aspect_ratio") or "9:16"),
            audio_required=bool(params.get("audio_required", True)),
            optional_seed=params.get("optional_seed"),
        )
    except KeyError as exc:
        raise RequestBuildError("PLAN_PARAM_MISSING", f"计划缺少必需参数：{exc}") from exc


def build_request_body(params: dict[str, Any], caps: H3Capabilities) -> dict[str, Any]:
    """计划参数 → 上游请求体（含能力档案校验；报价与生成共用）。"""
    return build_h3_request(build_generation_input(params), caps)


def build_preview_request(params: dict[str, Any], caps: H3Capabilities) -> dict[str, Any]:
    """冻结脚本/锚帧/声音/字幕版本 → H3 低清预览请求。

    预览专用构造路径强制 9:16 与最低已验证分辨率默认值，并保留锚帧
    顺序映射及冻结版本 hash，避免报价或正式渲染路径静默改写输入。
    """
    try:
        return build_h3_preview_request(dict(params), caps)
    except PreviewInputError:
        raise
    except KeyError as exc:
        raise RequestBuildError("PREVIEW_PARAM_MISSING", f"预览缺少冻结版本参数：{exc}") from exc
