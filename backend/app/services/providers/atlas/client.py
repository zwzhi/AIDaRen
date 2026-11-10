"""Atlas 商业通道配置解析。

商业域任务通过 ``resolve_provider_for_commercial_task()`` 取得唯一的
Atlas 配置；该函数绝不返回 TokenFree 渠道，未配置/未验证时给出明确错误，
调用方（报价、提交、轮询）据此阻断而不是静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

ATLAS_PROVIDER_ID = "atlas"
ATLAS_DEFAULT_BASE_URL = "https://api.atlascloud.ai"


class ProviderNotConfigured(Exception):
    """Atlas 通道未启用或缺少必要配置；对应错误码 PROVIDER_NOT_CONFIGURED。"""

    code = "PROVIDER_NOT_CONFIGURED"


class CapabilityUnverified(Exception):
    """模型能力未经真实契约验证；付费提交被 INV 阻断（MODEL_CAPABILITY_UNVERIFIED）。"""

    code = "MODEL_CAPABILITY_UNVERIFIED"


@dataclass(frozen=True)
class AtlasProviderConfig:
    """商业域唯一的模型通道配置快照。"""

    provider_id: str = ATLAS_PROVIDER_ID
    base_url: str = ATLAS_DEFAULT_BASE_URL
    api_key: str = ""
    # 商业域使用的模型角色 → 模型 ID（空串表示未配置）
    models: dict[str, str] = field(default_factory=dict)
    paid_execution_enabled: bool = False
    mock_mode: bool = True
    verified_models: frozenset[str] = frozenset()

    # 供 API/日志使用的脱敏视图；绝不包含明文密钥
    def masked(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "base_url": self.base_url,
            "api_key": "",
            "has_api_key": bool(self.api_key),
            "models": dict(self.models),
            "paid_execution_enabled": self.paid_execution_enabled,
            "mock_mode": self.mock_mode,
            "verified_models": sorted(self.verified_models),
        }


def _verified_models(raw: str) -> frozenset[str]:
    return frozenset(
        item.strip() for item in (raw or "").split(",") if item.strip()
    )


def _configured_model_roles() -> dict[str, str]:
    """商业域当前配置的模型角色清单；角色名与任务书 §8 的两个适配器对应。"""
    settings = get_settings()
    roles = {
        "analysis": (settings.gemini_analysis_model_id or "").strip(),
        "video_reference": (settings.h3_developer_reference_model_id or "").strip(),
    }
    return {role: model for role, model in roles.items() if model}


def resolve_provider_for_commercial_task(*, require_verified: bool = False) -> AtlasProviderConfig:
    """解析商业任务的 Atlas 通道配置。

    - 商业域未启用或缺少密钥：抛 ProviderNotConfigured（不回落 TokenFree）；
    - require_verified=True（付费提交路径）：还要求付费开关已开、两个模型角色
      （解析/生成）的精确 ID 均已配置且都在管理员验证清单内，缺一即阻断——
      不允许"留空放行"或回落占位模型。
    """
    settings = get_settings()
    if not settings.commercial_enabled:
        raise ProviderNotConfigured("商业域未启用（commercial_enabled=false）")
    api_key = (settings.atlas_api_key or "").strip()
    if not api_key:
        raise ProviderNotConfigured("Atlas API 密钥未配置")

    config = AtlasProviderConfig(
        base_url=(settings.atlas_base_url or ATLAS_DEFAULT_BASE_URL).rstrip("/"),
        api_key=api_key,
        models=_configured_model_roles(),
        paid_execution_enabled=bool(settings.commercial_paid_execution_enabled),
        mock_mode=bool(settings.commercial_mock_mode),
        verified_models=_verified_models(settings.commercial_verified_models),
    )

    if require_verified:
        if not config.paid_execution_enabled:
            raise ProviderNotConfigured("商业域付费执行未开启（commercial_paid_execution_enabled=false）")
        required_roles = ("analysis", "video_reference")
        missing_roles = [role for role in required_roles if role not in config.models]
        if missing_roles:
            raise ProviderNotConfigured(
                "商业域模型 ID 未配置（禁止回落占位模型）: " + ", ".join(missing_roles)
            )
        unverified = [
            f"{role}:{model}"
            for role, model in config.models.items()
            if model not in config.verified_models
        ]
        if unverified:
            raise CapabilityUnverified(
                "模型能力未通过真实契约验证，禁止付费提交: " + ", ".join(unverified)
            )
    return config
