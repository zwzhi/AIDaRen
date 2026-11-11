"""Authorized mock TTS and subtitle revision contracts for replication projects.

The first commercial replication slice deliberately keeps synthesis local and
deterministic.  The service records the exact script hash, voice version and
rights evidence alongside the generated media asset so a later provider can be
introduced without changing the persistence contract.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_commercial import (
    CvActor,
    CvMediaAsset,
    CvReplicationProject,
    CvRightsEvidence,
    CvScriptVersion,
    CvSubtitleVersion,
    CvVoiceProfile,
    CvVoiceRender,
)
from app.services.commercial.rights import RightsEvidence, evaluate_rights_gate


class VoiceRenderError(ValueError):
    """A voice render request failed an explicit commercial gate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VoiceFixtureRequest:
    script_version_id: int
    script_hash: str
    voice_profile_id: int
    dialogue: str
    rights_verified: bool


@dataclass(frozen=True)
class FixtureVoiceRenderResult:
    status: str
    duration_ms: int
    script_hash: str
    audio_asset_payload: dict[str, Any]


@dataclass(frozen=True)
class SubtitleRevision:
    version: int
    script_hash: str
    status: str
    invalidation_reason: str | None = None


def render_voice_fixture(request: VoiceFixtureRequest) -> FixtureVoiceRenderResult:
    """Offline contract for the first voice vertical slice."""
    if not request.rights_verified:
        raise VoiceRenderError("VOICE_RIGHTS_REQUIRED", "声音权利证据未确认")
    synthesis = MockTTSAdapter().synthesize(request.dialogue)
    return FixtureVoiceRenderResult(
        status="pending_review",
        duration_ms=synthesis.duration_ms,
        script_hash=request.script_hash,
        audio_asset_payload={
            "source_role": "owned_generated_audio",
            "script_version_id": request.script_version_id,
            "voice_profile_id": request.voice_profile_id,
            "script_hash": request.script_hash,
            "duration_ms": synthesis.duration_ms,
        },
    )


def invalidate_subtitle_revision(revision: SubtitleRevision, *, reason: str) -> SubtitleRevision:
    if not reason:
        raise ValueError("reason is required")
    return SubtitleRevision(
        version=revision.version,
        script_hash=revision.script_hash,
        status="invalidated",
        invalidation_reason=reason,
    )


@dataclass(frozen=True)
class VoiceRenderRequest:
    """Inputs that must be frozen before synthesis begins."""

    script_version_id: int
    voice_profile_id: int
    rights_evidence_id: int | None = None
    replication_project_id: int | None = None
    created_by: int | None = None
    voice_version: str = "mock-voice-v1"
    rights_evidence: Any | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.script_version_id <= 0 or self.voice_profile_id <= 0:
            raise ValueError("script_version_id and voice_profile_id must be positive")
        if self.rights_evidence_id is None and self.rights_evidence is None:
            raise ValueError("rights evidence is required")
        if not self.voice_version.strip():
            raise ValueError("voice_version is required")


@dataclass(frozen=True)
class MockSynthesisResult:
    script_hash: str
    duration_ms: int
    voice_version: str
    payload: dict[str, Any]
    audio_bytes: bytes


@dataclass
class VoiceRenderResult:
    """Stable response object that delegates model fields for compatibility."""

    voice_render: CvVoiceRender
    audio_asset: CvMediaAsset

    def __getattr__(self, name: str) -> Any:
        return getattr(self.voice_render, name)

    @property
    def id(self) -> int | None:
        return self.voice_render.id

    @property
    def audio_asset_id(self) -> int | None:
        return self.voice_render.audio_asset_id


class MockTTSAdapter:
    """Deterministic offline TTS substitute used by the MVP and tests."""

    def synthesize(self, text: str, *, voice_version: str = "mock-voice-v1") -> MockSynthesisResult:
        normalized = " ".join(str(text or "").split())
        script_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        # A stable duration estimate acts as the measured duration in the mock.
        duration_ms = max(800, len(normalized) * 85 + 350)
        payload = {
            "provider": "mock",
            "voice_version": voice_version,
            "script_hash": script_hash,
            "duration_ms": duration_ms,
        }
        audio_bytes = (
            f"MOCK-TTS|{voice_version}|{script_hash}|{duration_ms}".encode("utf-8")
        )
        return MockSynthesisResult(script_hash, duration_ms, voice_version, payload, audio_bytes)


def _script_text(script_json: Any) -> str:
    """Flatten dialogue lines while keeping the hash based on full JSON below."""
    if isinstance(script_json, dict):
        scripts = script_json.get("scripts")
        if isinstance(scripts, list):
            lines = [str(item.get("dialogue", "")) for item in scripts if isinstance(item, dict)]
            return " ".join(line for line in lines if line)
        return str(script_json.get("dialogue", ""))
    if isinstance(script_json, list):
        return " ".join(str(item.get("dialogue", "")) for item in script_json if isinstance(item, dict))
    return str(script_json or "")


def _script_hash(script_json: Any) -> str:
    encoded = json.dumps(script_json or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _rights_evidence_from_row(row: Any) -> RightsEvidence:
    if isinstance(row, dict):
        get = row.get
    else:
        get = lambda key, default=None: getattr(row, key, default)
    channels = get("channels", ()) or ()
    if isinstance(channels, dict):
        channels = channels.get("channels", ())
    if isinstance(channels, str):
        channels = (channels,)
    return RightsEvidence(
        subject_type=str(get("subject_type", "voice")),
        subject_id=int(get("subject_id", 0) or 0),
        scope=str(get("scope", "commercial_voice")),
        territory=str(get("territory", "")),
        channels=tuple(str(item) for item in channels),
        valid_until=get("valid_until"),
        revoked_at=get("revoked_at"),
        verified=bool(get("verified", False)),
    )


class VoiceStrategy:
    """Persist an authorized, deterministic voice render."""

    def __init__(self, db: AsyncSession, *, tts: MockTTSAdapter | None = None) -> None:
        self.db = db
        self.tts = tts or MockTTSAdapter()

    async def render(
        self,
        request: VoiceRenderRequest | int,
        voice_profile_id: int | None = None,
        rights_evidence_id: int | None = None,
    ) -> VoiceRenderResult:
        if not isinstance(request, VoiceRenderRequest):
            request = VoiceRenderRequest(
                script_version_id=int(request),
                voice_profile_id=int(voice_profile_id or 0),
                rights_evidence_id=rights_evidence_id,
            )
        script = await self.db.get(CvScriptVersion, request.script_version_id)
        voice = await self.db.get(CvVoiceProfile, request.voice_profile_id)
        if script is None:
            raise VoiceRenderError("SCRIPT_NOT_FOUND", "脚本版本不存在")
        if voice is None:
            raise VoiceRenderError("VOICE_PROFILE_NOT_FOUND", "授权音色不存在")
        if voice.status != "active":
            raise VoiceRenderError("VOICE_UNAUTHORIZED", "音色授权已撤销")
        if voice.authorized_until is not None:
            expiry = voice.authorized_until
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= datetime.now(UTC):
                raise VoiceRenderError("VOICE_AUTH_EXPIRED", "音色授权已过期")

        evidence = request.rights_evidence
        if evidence is None and request.rights_evidence_id is not None:
            evidence = await self.db.get(CvRightsEvidence, request.rights_evidence_id)
        if evidence is None:
            raise VoiceRenderError("RIGHTS_MISSING", "缺少声音权利证据")
        decision = evaluate_rights_gate((_rights_evidence_from_row(evidence),))
        if not decision.allowed:
            raise VoiceRenderError(decision.reason_code, "; ".join(decision.reasons))

        project_id = request.replication_project_id or script.replication_project_id
        full_hash = _script_hash(script.script_json)
        text = _script_text(script.script_json)
        synthesis = self.tts.synthesize(text, voice_version=request.voice_version)
        # The hash is over the immutable JSON revision, rather than only dialogue.
        synthesis = MockSynthesisResult(
            script_hash=full_hash,
            duration_ms=synthesis.duration_ms,
            voice_version=synthesis.voice_version,
            payload={**synthesis.payload, "script_hash": full_hash},
            audio_bytes=synthesis.audio_bytes,
        )

        previous = (await self.db.execute(select(CvVoiceRender).where(
            CvVoiceRender.replication_project_id == project_id,
        ))).scalars().all()
        for item in previous:
            if item.script_hash != full_hash and item.status not in {"invalidated", "superseded"}:
                item.status = "invalidated"
                item.invalidation_reason = "script_version_changed"

        actor = await self.db.get(CvActor, voice.actor_id)
        uploaded_by = request.created_by or (actor.created_by if actor is not None else 1)
        audio_sha = hashlib.sha256(synthesis.audio_bytes).hexdigest()
        asset = CvMediaAsset(
            team_id=getattr(actor, "team_id", None),
            kind="audio",
            object_key=f"commercial/voice/{project_id}/{full_hash[:24]}-{voice.id}.mock",
            sha256=audio_sha,
            mime="audio/wav",
            size_bytes=len(synthesis.audio_bytes),
            duration_ms=synthesis.duration_ms,
            has_audio=True,
            source_role="generated_voice",
            rights_status="authorized",
            rights_declaration="mock_tts_authorized",
            uploaded_by=uploaded_by,
            source_metadata={
                "provider": "mock",
                "script_hash": full_hash,
                "duration_ms": synthesis.duration_ms,
                "voice_version": synthesis.voice_version,
                "rights_evidence_id": getattr(evidence, "id", request.rights_evidence_id),
                "payload": synthesis.payload,
            },
        )
        self.db.add(asset)
        await self.db.flush()
        render = CvVoiceRender(
            replication_project_id=project_id,
            script_version_id=script.id,
            voice_profile_id=voice.id,
            model_id="mock-tts",
            model_version=synthesis.voice_version,
            voice_version=synthesis.voice_version,
            audio_asset_id=asset.id,
            duration_ms=synthesis.duration_ms,
            script_hash=full_hash,
            rights_evidence_id=getattr(evidence, "id", request.rights_evidence_id),
            status="rendered",
        )
        self.db.add(render)
        await self.db.flush()
        project = await self.db.get(CvReplicationProject, project_id)
        if project is not None:
            project.current_voice_render_id = render.id
        return VoiceRenderResult(render, asset)


async def create_subtitle_version(
    db: AsyncSession,
    *,
    replication_project_id: int,
    script_version_id: int,
    voice_render_id: int,
    language: str = "zh-CN",
    style_json: dict[str, Any] | None = None,
) -> CvSubtitleVersion:
    """Build a draft subtitle revision tied to one script and voice render."""
    script = await db.get(CvScriptVersion, script_version_id)
    voice = await db.get(CvVoiceRender, voice_render_id)
    if script is None or script.replication_project_id != replication_project_id:
        raise VoiceRenderError("SCRIPT_NOT_FOUND", "字幕脚本版本不存在")
    if voice is None or voice.replication_project_id != replication_project_id:
        raise VoiceRenderError("VOICE_RENDER_NOT_FOUND", "字幕声音版本不存在")
    if voice.script_version_id != script_version_id:
        raise VoiceRenderError("SUBTITLE_INPUT_MISMATCH", "字幕必须引用同一脚本和声音版本")
    payload = script.script_json or {}
    rows = payload.get("scripts", []) if isinstance(payload, dict) else payload
    subtitles: list[dict[str, Any]] = []
    cursor = 0
    for index, item in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("dialogue", "")).strip()
        if not text:
            continue
        duration = max(300, min(voice.duration_ms or 1_000, len(text) * 85 + 350))
        subtitles.append({"index": index, "start_ms": cursor, "end_ms": cursor + duration, "text": text})
        cursor += duration
    current = await db.scalar(select(func.max(CvSubtitleVersion.version)).where(
        CvSubtitleVersion.replication_project_id == replication_project_id,
    ))
    row = CvSubtitleVersion(
        replication_project_id=replication_project_id,
        script_version_id=script_version_id,
        voice_render_id=voice_render_id,
        version=int(current or 0) + 1,
        subtitles_json=subtitles,
        style_json=style_json or {},
        language=language,
        status="draft",
    )
    db.add(row)
    await db.flush()
    return row


async def approve_subtitle_version(db: AsyncSession, subtitle_version_id: int, approved_by: int) -> CvSubtitleVersion:
    row = await db.get(CvSubtitleVersion, subtitle_version_id)
    if row is None:
        raise VoiceRenderError("SUBTITLE_NOT_FOUND", "字幕版本不存在")
    if row.status not in {"draft", "review"}:
        raise VoiceRenderError("SUBTITLE_STATE_INVALID", "字幕当前状态不可批准")
    row.status = "approved"
    row.approved_by = approved_by
    row.approved_at = datetime.now(UTC)
    await db.flush()
    return row


def subtitle_reference(subtitle: CvSubtitleVersion, stage: str) -> dict[str, Any]:
    """Return the frozen revision pointer shared by preview and final export."""
    if stage not in {"preview", "final"}:
        raise ValueError("stage must be preview or final")
    if subtitle.status != "approved":
        raise VoiceRenderError("SUBTITLE_NOT_APPROVED", "预览和正式导出只能引用已批准字幕")
    return {
        "subtitle_version_id": subtitle.id,
        "subtitle_revision": subtitle.version,
        "stage": stage,
    }


# Alias names used by callers that prefer a strategy-oriented API.
SubtitleStrategy = type("SubtitleStrategy", (), {
    "create": staticmethod(create_subtitle_version),
    "approve": staticmethod(approve_subtitle_version),
})

