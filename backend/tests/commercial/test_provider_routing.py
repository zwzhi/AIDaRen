# -*- coding: utf-8 -*-
"""T01｜商业域 Atlas 通道隔离回归。

锁定三条边界：
1. Atlas 配置独立命名空间，保存/重启后不被 TokenFree overlay 或渠道归一覆盖；
2. 商业任务只解析到 Atlas，旧业务（openai_*/ark_*）继续走 TokenFree；
3. 密钥永不回传客户端；模型能力未验证时拒绝付费提交。
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import config
from app.schemas_settings import AdminModelSettingsPatch
from app.services import model_settings
from app.services.providers.atlas.client import (
    AtlasProviderConfig,
    ProviderNotConfigured,
    resolve_provider_for_commercial_task,
)
from tests.conftest import make_user

ATLAS_KEY = "atlas-test-key-do-not-leak"


@pytest.fixture(autouse=True)
def _isolate_overlay():
    """用例后还原全局 overlay 与 settings 缓存，避免污染其他测试。"""
    saved_overlay = dict(model_settings._overlay)
    saved_snapshot = model_settings._routing_snapshot
    yield
    model_settings._routing_snapshot = saved_snapshot
    model_settings._refresh_overlay({"flat": saved_overlay})
    config.get_settings.cache_clear()


def _atlas_patch_body() -> AdminModelSettingsPatch:
    """保存一份完整的 Atlas 商业配置。"""
    return AdminModelSettingsPatch(
        commercial_enabled=True,
        commercial_paid_execution_enabled=True,
        atlas_api_key=ATLAS_KEY,
        gemini_analysis_model_id="gemini-3-flash-preview",
        h3_developer_reference_model_id="minimax-h3-developer-reference",
    )


async def _save_atlas_config(db) -> None:
    await model_settings.patch_admin_model_settings(db, _atlas_patch_body())


async def _simulate_restart(db) -> None:
    """模拟进程重启：清缓存后重新从 DB 加载模型配置（含渠道归一与 overlay）。"""
    config.get_settings.cache_clear()
    await model_settings.load_model_settings_cache(db)


# ---------------------------------------------------------------- 1. 保存与重启
@pytest.mark.asyncio
async def test_atlas_config_survives_save_and_restart(db_session) -> None:
    """保存 Atlas 配置 → 模拟重启（重加载）→ 配置仍在且未被 TokenFree 归一覆盖。"""
    await _save_atlas_config(db_session)

    settings = config.get_settings()
    assert settings.atlas_api_key == ATLAS_KEY
    assert settings.commercial_enabled is True

    await _simulate_restart(db_session)

    settings = config.get_settings()
    # Atlas 配置未被启动归一/overlay 清除
    assert settings.atlas_api_key == ATLAS_KEY
    assert settings.commercial_enabled is True
    assert settings.gemini_analysis_model_id == "gemini-3-flash-preview"
    assert settings.h3_developer_reference_model_id == "minimax-h3-developer-reference"
    # Atlas base_url 仍是 Atlas，没有被刷成 TokenFree
    assert "atlascloud.ai" in settings.atlas_base_url
    assert "tokenfree.com" not in settings.atlas_base_url
    # 渠道归一后商业配置依然可解析
    provider = resolve_provider_for_commercial_task()
    assert provider.provider_id == "atlas"


# ---------------------------------------------------------------- 2. 通道隔离
@pytest.mark.asyncio
async def test_commercial_does_not_route_to_tokenfree(db_session) -> None:
    """商业任务解析到 Atlas；同环境下旧业务字段仍指向 TokenFree。"""
    await _save_atlas_config(db_session)

    provider = resolve_provider_for_commercial_task()
    assert isinstance(provider, AtlasProviderConfig)
    assert provider.provider_id == "atlas"
    assert "atlascloud.ai" in provider.base_url
    assert "tokenfree.com" not in provider.base_url
    assert provider.api_key == ATLAS_KEY
    assert provider.api_key != model_settings.get_settings().openai_api_key or provider.api_key == ""

    # 旧业务通道未被改写：openai/ark 仍为 TokenFree 锁定值
    legacy = config.get_settings()
    assert legacy.openai_base_url == "https://www.tokenfree.com/v1"
    assert legacy.ark_base_url == "https://www.tokenfree.com/v1"
    # TokenFree 渠道仍是唯一启用渠道行
    channels = model_settings.get_routing_snapshot().channels
    assert [c.id for c in channels if c.enabled] == ["tokenfree"]


@pytest.mark.asyncio
async def test_unconfigured_atlas_raises_clear_error(db_session) -> None:
    """未配置密钥时给出明确错误，而不是静默回退 TokenFree。"""
    model_settings._refresh_overlay({"flat": {"atlas_api_key": "", "commercial_enabled": True}})
    config.get_settings.cache_clear()
    with pytest.raises(ProviderNotConfigured):
        resolve_provider_for_commercial_task()


# ---------------------------------------------------------------- 3. 密钥脱敏
@pytest.mark.asyncio
async def test_secret_never_returned_to_client(db_session) -> None:
    """管理端模型设置响应中 atlas_api_key 恒为空串，仅返回 has_* 标志。"""
    await _save_atlas_config(db_session)

    out = await model_settings.get_admin_model_settings(db_session)
    assert out.atlas_api_key == ""
    assert out.has_atlas_api_key is True
    # 序列化后的完整载荷不包含明文密钥
    dumped = out.model_dump()
    assert ATLAS_KEY not in str(dumped)
    # provider 逻辑配置同样提供脱敏视图
    provider = resolve_provider_for_commercial_task()
    masked = provider.masked()
    assert masked["api_key"] == ""
    assert masked["has_api_key"] is True
    assert ATLAS_KEY not in str(masked)


# ---------------------------------------------------------------- 4. 未验证能力阻断付费
@pytest.mark.asyncio
async def test_unverified_model_blocks_paid_submit(db_session) -> None:
    """能力未验证（未登记 verified 清单）时，付费提交被拒绝。"""
    await _save_atlas_config(db_session)  # 已开 paid_execution，但未验证契约

    with pytest.raises(Exception) as exc_info:
        resolve_provider_for_commercial_task(require_verified=True)
    assert "MODEL_CAPABILITY_UNVERIFIED" in str(exc_info.value) or \
        exc_info.type.__name__ == "CapabilityUnverified"

    # 管理员验证契约后放行
    await model_settings.patch_admin_model_settings(
        db_session,
        AdminModelSettingsPatch(
            commercial_verified_models="gemini-3-flash-preview,minimax-h3-developer-reference",
        ),
    )
    provider = resolve_provider_for_commercial_task(require_verified=True)
    assert provider.provider_id == "atlas"


@pytest.mark.asyncio
async def test_paid_execution_disabled_by_default(db_session) -> None:
    """默认关闭付费执行：即使配置齐全，未显式开启时拒绝付费提交。"""
    await model_settings.patch_admin_model_settings(
        db_session,
        AdminModelSettingsPatch(
            commercial_enabled=True,
            commercial_paid_execution_enabled=False,
            atlas_api_key=ATLAS_KEY,
            commercial_verified_models="minimax-h3-developer-reference",
        ),
    )
    with pytest.raises(ProviderNotConfigured):
        resolve_provider_for_commercial_task(require_verified=True)
    # 非付费路径（离线/报价读取）不受此限
    provider = resolve_provider_for_commercial_task()
    assert provider.provider_id == "atlas"
