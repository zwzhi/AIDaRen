"""达人-音色绑定校验（§6.1 / INV-02 / G01）。"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models_commercial import CvActorVersion, CvVoiceProfile


class VoiceBindingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def validate_voice_binding(
    actor_version: CvActorVersion,
    voice: CvVoiceProfile,
    *,
    allow_cross_actor: bool = False,
) -> None:
    """音色必须归属同一达人，或经明确批准的特殊绑定；授权必须有效。"""
    if voice.status == "revoked":
        raise VoiceBindingError("VOICE_BINDING_INVALID", "音色授权已撤销")
    until = voice.authorized_until
    if until is not None:
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if until <= datetime.now(UTC):
            raise VoiceBindingError("VOICE_AUTHORIZATION_EXPIRED", "音色授权已过期")
    if voice.actor_id != actor_version.actor_id and not allow_cross_actor:
        raise VoiceBindingError(
            "VOICE_BINDING_INVALID",
            "音色归属其他达人，需显式批准特殊声音绑定后才能使用",
        )
