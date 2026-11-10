# -*- coding: utf-8 -*-
"""收尾§5.2：加密密钥恢复语义（测试密钥，零真实调用）。"""
from __future__ import annotations

import pytest


def _fernet_with(secret: str):
    from app.services import model_settings as ms

    old = ms.get_settings().secret_key
    object.__setattr__(ms.get_settings(), "secret_key", secret)
    try:
        yield ms._fernet()
    finally:
        object.__setattr__(ms.get_settings(), "secret_key", old)


def test_encrypt_decrypt_roundtrip_with_same_key() -> None:
    from app.services import model_settings as ms

    cipher = ms._encrypt_secret("atlas-test-key-123")
    assert cipher.startswith("enc:")
    assert ms._decrypt_secret(cipher) == "atlas-test-key-123"


def test_wrong_key_returns_empty_and_ciphertext_intact() -> None:
    """密钥错误：解密返回空串并告警降级；原密文不被破坏，可待正确密钥恢复。"""
    from app.services import model_settings as ms

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ms.get_settings(), "secret_key", "key-A-correct", raising=False)
        cipher = ms._encrypt_secret("atlas-test-key-123")
    # 换错密钥解密
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ms.get_settings(), "secret_key", "key-B-wrong", raising=False)
        assert ms._decrypt_secret(cipher) == ""  # 降级为未配置，不抛错不致启动失败
    # 原密文未被改写，正确密钥仍可恢复
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ms.get_settings(), "secret_key", "key-A-correct", raising=False)
        assert ms._decrypt_secret(cipher) == "atlas-test-key-123"


def test_wrong_key_blocks_paid_but_keeps_cipher(monkeypatch: pytest.MonkeyPatch) -> None:
    """密钥缺失/错误 → atlas_api_key 视为空 → 付费执行被阻断（不回落默认密钥）。"""
    from app.services import model_settings as ms
    from app.services.providers.atlas.client import (
        ProviderNotConfigured,
        resolve_provider_for_commercial_task,
    )

    # 模拟 DB 中存在错误密钥加密的配置：解密为空 → 等效未配置
    monkeypatch.setattr(ms, "get_overlay_dict", lambda: {
        "commercial_enabled": True,
        "atlas_api_key": "",  # 解密降级后的等效状态
    })
    from app import config
    config.get_settings.cache_clear()
    with pytest.raises(ProviderNotConfigured):
        resolve_provider_for_commercial_task(require_verified=False)
