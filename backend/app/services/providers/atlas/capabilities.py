"""Atlas 商业域能力档案骨架。

任务书 §8.1：能力核实先于字段编码。每个能力条目带 capability_verified
标志；T03 的真实契约联调通过后，由管理员把对应 model_id 写入
``commercial_verified_models`` 清单，付费提交才会放行。
本文件在 T01 只提供结构与其后的扩展点，不做任何网络请求。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.services.providers.atlas.client import ATLAS_PROVIDER_ID


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """单个商业模型角色的能力描述（含验证状态）。"""

    role: str
    label: str
    configured_model: str
    capability_verified: bool
    probe_status: str = "unverified"
    probe_error: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def _verified_set() -> frozenset[str]:
    raw = get_settings().commercial_verified_models or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def commercial_capability_profiles() -> list[ModelCapabilityProfile]:
    """当前商业域两个指定模型角色的能力档案（脱敏，无密钥）。"""
    settings = get_settings()
    verified = _verified_set()
    profiles: list[ModelCapabilityProfile] = []
    for role, label, model in (
        ("analysis", "视频解析（Gemini）", (settings.gemini_analysis_model_id or "").strip()),
        ("video_reference", "参考生成视频（H3 Developer Reference）", (settings.h3_developer_reference_model_id or "").strip()),
    ):
        profiles.append(
            ModelCapabilityProfile(
                role=role,
                label=label,
                configured_model=model,
                capability_verified=bool(model) and model in verified,
                probe_status="verified" if bool(model) and model in verified else "unverified",
            )
        )
    return profiles


def provider_ready_for_commercial() -> bool:
    """商业域通道是否完成最小配置（启用 + 密钥）；不代表能力已验证。"""
    settings = get_settings()
    return bool(settings.commercial_enabled) and bool((settings.atlas_api_key or "").strip())


PROVIDER_ID = ATLAS_PROVIDER_ID
