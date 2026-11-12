"""Deterministic checks for authorized voice-reference samples."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceQualityReport:
    duration_ms: int
    sample_rate: int
    channels: int
    has_music: bool = False
    noise_score: float | None = None
    single_speaker_score: float | None = None
    status: str = "candidate"
    reasons: tuple[str, ...] = ()


def evaluate_voice_source(
    *,
    duration_ms: int,
    sample_rate: int,
    channels: int,
    has_music: bool = False,
    noise_score: float | None = None,
    single_speaker_score: float | None = None,
    min_duration_ms: int = 5_000,
    max_duration_ms: int = 60_000,
) -> VoiceQualityReport:
    reasons: list[str] = []
    if duration_ms < min_duration_ms:
        reasons.append("sample_too_short")
    if duration_ms > max_duration_ms:
        reasons.append("sample_too_long")
    if sample_rate < 16_000:
        reasons.append("sample_rate_low")
    if channels != 1:
        reasons.append("mono_recommended")
    if has_music:
        reasons.append("background_music_detected")
    if noise_score is not None and noise_score > 0.45:
        reasons.append("noise_high")
    if single_speaker_score is not None and single_speaker_score < 0.8:
        reasons.append("single_speaker_uncertain")
    status = "approved" if not reasons else "needs_review"
    return VoiceQualityReport(
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        channels=channels,
        has_music=has_music,
        noise_score=noise_score,
        single_speaker_score=single_speaker_score,
        status=status,
        reasons=tuple(reasons),
    )

