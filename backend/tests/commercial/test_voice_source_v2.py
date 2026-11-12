from app.services.commercial.voice_source import evaluate_voice_source


def test_clean_mono_voice_sample_can_be_approved():
    result = evaluate_voice_source(
        duration_ms=30_000,
        sample_rate=24_000,
        channels=1,
        noise_score=0.1,
        single_speaker_score=0.98,
    )
    assert result.status == "approved"
    assert result.reasons == ()


def test_music_or_uncertain_speaker_requires_review():
    result = evaluate_voice_source(
        duration_ms=30_000,
        sample_rate=24_000,
        channels=1,
        has_music=True,
        noise_score=0.6,
        single_speaker_score=0.5,
    )
    assert result.status == "needs_review"
    assert {"background_music_detected", "noise_high", "single_speaker_uncertain"} <= set(result.reasons)

