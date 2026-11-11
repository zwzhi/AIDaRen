"""Deterministic frame extraction, anchor sampling, and revision invalidation."""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

from app.config import get_settings
from app.models_commercial import (
    CvAnchorFrame,
    CvAnchorSet,
    CvCostQuote,
    CvMediaAsset,
    CvScriptVersion,
    CvShotGraph,
    CvSubtitleVersion,
    CvVoiceRender,
)
from app.services.commercial.storage import asset_disk_path, new_object_key, persist_asset_bytes


@dataclass(frozen=True)
class AnchorCandidate:
    """A deterministic source-frame candidate selected for one shot."""

    shot_key: str
    time_ms: int
    score: float = 0.0
    reason: str = ""


def _shot_rows(shot_graph: Any) -> list[dict[str, Any]]:
    if isinstance(shot_graph, dict):
        rows = shot_graph.get("shots") or []
    else:
        rows = getattr(shot_graph, "shots", shot_graph)
    normalised: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            value = row
        else:
            value = {
                "shot_key": getattr(row, "shot_key", getattr(row, "shot_id", "")),
                "start_ms": getattr(row, "start_ms", 0),
                "end_ms": getattr(row, "end_ms", 0),
                "complexity": getattr(row, "complexity", "simple"),
                "product_presence": getattr(row, "product_presence", "unknown"),
                "motion_score": getattr(row, "motion_score", 0),
                "sharpness_score": getattr(row, "sharpness_score", 0),
            }
        start = max(0, int(value.get("start_ms") or 0))
        end = max(start, int(value.get("end_ms") or start))
        if not value.get("shot_key") or end <= start:
            continue
        normalised.append({**value, "start_ms": start, "end_ms": end})
    return normalised


def _target_count(shots: list[dict[str, Any]], max_frames: int) -> int:
    """Choose the contract's 3/5/7 tiers, bounded by H3's nine-image limit."""
    max_frames = max(1, min(int(max_frames), 9))
    if any(
        str(s.get("complexity", "")).lower() in {"high", "very_high", "complex"}
        or float(s.get("complexity_score") or 0) >= 0.7
        or float(s.get("motion_score") or 0) >= 0.7
        or float(s.get("motion_change") or 0) >= 0.7
        or float(s.get("sharpness_score") or 0) >= 0.7
        for s in shots
    ):
        requested = 7
    elif any(str(s.get("product_presence", "")).lower() in {"required", "optional", "present"} for s in shots):
        requested = 5
    else:
        requested = 3
    return min(requested, max_frames)


def sample_anchor_candidates(shot_graph: Any, *, max_frames: int = 9) -> list[AnchorCandidate]:
    """Select 3, 5, or 7 deterministic candidates from shot boundaries.

    The caller owns shot ordering.  This function never sorts by a model score
    or delegates ordering to a provider.  Each selected shot receives at least
    one frame when the requested tier permits it.
    """
    shots = _shot_rows(shot_graph)
    if not shots:
        return []
    target = _target_count(shots, max_frames)
    slots = [1] * min(len(shots), target)
    remaining = target - sum(slots)
    ranked = sorted(
        range(len(shots)),
        key=lambda i: (shots[i]["end_ms"] - shots[i]["start_ms"], i),
        reverse=True,
    )
    rank_position = 0
    while remaining > 0:
        index = ranked[rank_position % len(ranked)]
        slots[index] += 1
        remaining -= 1
        rank_position += 1

    candidates: list[AnchorCandidate] = []
    for shot, count in zip(shots, slots):
        start, end = shot["start_ms"], shot["end_ms"]
        if count == 1:
            times = [start]
        else:
            step = (end - start) / (count - 1)
            times = [int(round(start + step * i)) for i in range(count)]
        for sequence, time_ms in enumerate(times):
            position = (time_ms - start) / max(1, end - start)
            boundary_bonus = 1.0 if sequence in {0, len(times) - 1} else 0.5
            candidates.append(
                AnchorCandidate(
                    shot_key=str(shot["shot_key"]),
                    time_ms=time_ms,
                    score=round(boundary_bonus + position, 6),
                    reason="shot_boundary" if boundary_bonus == 1.0 else "shot_complexity",
                )
            )
    return candidates[:9]


def source_frame_asset(
    parent: CvMediaAsset,
    *,
    time_ms: int,
    object_key: str,
    sha256: str,
    size_bytes: int,
) -> CvMediaAsset:
    """Build the private immutable asset row for an extracted source frame."""
    if parent.kind != "video":
        raise ValueError("source frame parent must be a video asset")
    if time_ms < 0 or (parent.duration_ms is not None and time_ms > parent.duration_ms):
        raise ValueError("source frame time is outside the source video")
    return CvMediaAsset(
        team_id=parent.team_id,
        kind="image",
        object_key=object_key,
        sha256=sha256,
        mime="image/jpeg",
        size_bytes=size_bytes,
        width=None,
        height=None,
        duration_ms=None,
        has_audio=None,
        source_role="reference_source_frame",
        derived_from_asset_id=parent.id,
        source_time_ms=time_ms,
        source_metadata={"time_ms": time_ms, "parent_sha256": parent.sha256},
        rights_status=parent.rights_status or "authorized",
        rights_declaration=parent.rights_declaration or "",
        authorized_until=parent.authorized_until,
        uploaded_by=parent.uploaded_by,
    )


async def _extract_jpeg(source_path: Path, time_ms: int) -> bytes:
    cmd = [
        get_settings().ffmpeg_path or "ffmpeg",
        "-hide_banner", "-loglevel", "error", "-ss", f"{time_ms / 1000:.3f}",
        "-i", str(source_path), "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0 or not stdout:
        detail = stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"source frame extraction failed: {detail}")
    return stdout


async def extract_source_frame(
    db_or_source_asset_id: Any = None,
    source_asset_id: int | None = None,
    time_ms: int | None = None,
    *,
    db: Any = None,
) -> CvMediaAsset:
    """Extract one frame into private storage and persist its lineage.

    Both ``extract_source_frame(db, asset_id, time_ms)`` and
    ``extract_source_frame(asset_id, time_ms, db=db)`` are accepted so callers
    can use the service with their existing dependency-injection style.
    """
    if hasattr(db_or_source_asset_id, "get"):
        db = db_or_source_asset_id
        asset_id = source_asset_id
        timestamp = time_ms
    elif db_or_source_asset_id is None:
        asset_id = source_asset_id
        timestamp = time_ms
    else:
        asset_id = int(db_or_source_asset_id)
        timestamp = source_asset_id if time_ms is None else time_ms
    if db is None:
        raise TypeError("extract_source_frame requires an AsyncSession")
    if asset_id is None or timestamp is None:
        raise TypeError("source_asset_id and time_ms are required")
    parent = await db.get(CvMediaAsset, int(asset_id))
    if parent is None:
        raise ValueError("source asset not found")
    source_path = asset_disk_path(parent.object_key)
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))
    jpeg = await _extract_jpeg(source_path, int(timestamp))
    object_key = new_object_key("reference_source_frame", "jpg")
    persist_asset_bytes(jpeg, object_key)
    frame = source_frame_asset(
        parent,
        time_ms=int(timestamp),
        object_key=object_key,
        sha256=hashlib.sha256(jpeg).hexdigest(),
        size_bytes=len(jpeg),
    )
    db.add(frame)
    await db.flush()
    return frame


def invalidation_statuses(*, changed_shot_keys: Iterable[str], reason: str) -> dict[str, str]:
    """Return the persisted statuses used by downstream revision invalidation."""
    if not reason or not set(changed_shot_keys):
        raise ValueError("changed_shot_keys and reason are required")
    return {
        "shot_graph": "superseded",
        "script": "invalidated",
        "anchor_set": "invalidated",
        "voice_render": "invalidated",
        "quote": "invalidated",
    }


async def invalidate_downstream_revisions(
    db_or_project_id: Any = None,
    project_id: int | None = None,
    *,
    changed_shot_keys: Iterable[str],
    reason: str,
    db: Any = None,
) -> None:
    """Invalidate shot graph descendants after product or script input changes."""
    if hasattr(db_or_project_id, "execute"):
        db = db_or_project_id
        actual_project_id = project_id
    elif db_or_project_id is None:
        actual_project_id = project_id
    else:
        actual_project_id = int(db_or_project_id)
    if db is None or actual_project_id is None:
        raise TypeError("invalidate_downstream_revisions requires an AsyncSession")
    changed = {str(key) for key in changed_shot_keys}
    if not changed or not reason:
        raise ValueError("changed_shot_keys and reason are required")

    graphs = (await db.execute(select(CvShotGraph).where(CvShotGraph.replication_project_id == actual_project_id))).scalars().all()
    impacted_shot_keys: set[str] = set()
    for graph in graphs:
        if graph.shot_key in changed and graph.status not in {"superseded", "invalidated"}:
            graph.status = "superseded"
            graph.invalidation_reason = reason
            impacted_shot_keys.add(graph.shot_key)
    if not impacted_shot_keys:
        impacted_shot_keys = changed

    scripts = (await db.execute(select(CvScriptVersion).where(CvScriptVersion.replication_project_id == actual_project_id))).scalars().all()
    invalid_script_ids: set[int] = set()
    for script in scripts:
        payload = script.script_json or {}
        encoded = str(payload)
        if any(key in encoded for key in impacted_shot_keys) or not encoded:
            script.status = "invalidated"
            script.invalidation_reason = reason
            invalid_script_ids.add(script.id)

    anchor_sets = (await db.execute(select(CvAnchorSet).where(CvAnchorSet.replication_project_id == actual_project_id))).scalars().all()
    invalid_anchor_ids: set[int] = set()
    for anchor_set in anchor_sets:
        frames = (await db.execute(select(CvAnchorFrame).where(CvAnchorFrame.anchor_set_id == anchor_set.id))).scalars().all()
        if not frames or any(frame.shot_key in impacted_shot_keys for frame in frames):
            anchor_set.status = "invalidated"
            anchor_set.invalidation_reason = reason
            invalid_anchor_ids.add(anchor_set.id)

    voices = (await db.execute(select(CvVoiceRender).where(CvVoiceRender.replication_project_id == actual_project_id))).scalars().all()
    for voice in voices:
        if voice.script_version_id in invalid_script_ids or invalid_script_ids or invalid_anchor_ids:
            voice.status = "invalidated"
            voice.invalidation_reason = reason

    subtitles = (await db.execute(
        select(CvSubtitleVersion).where(CvSubtitleVersion.replication_project_id == actual_project_id)
    )).scalars().all()
    for subtitle in subtitles:
        if subtitle.script_version_id in invalid_script_ids or invalid_script_ids:
            subtitle.status = "invalidated"
            subtitle.invalidation_reason = reason

    quotes = (await db.execute(select(CvCostQuote).where(CvCostQuote.replication_project_id == actual_project_id))).scalars().all()
    for quote in quotes:
        if quote.status not in {"settled", "expired"}:
            quote.status = "invalidated"
            quote.invalidation_reason = reason
    await db.flush()

