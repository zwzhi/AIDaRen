"""解析任务：缓存键隔离、结果校验与持久化（任务书 §4.1/§5.4）。"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sqlalchemy import select

from app.models_commercial import CvAnalysisRun, CvMediaAsset, CvReferenceSource
from app.schemas_commercial import AnalysisSchemaInvalid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "1"


def analysis_cache_key(
    *, team_id: int | None, source_sha256: str, model_id: str,
    prompt_version: str = PROMPT_VERSION, settings_hash: str = "", requested_by: int | None = None,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """缓存键至少含 team+源哈希+模型+提示词版本+设置+Schema 版本（§5.4）。"""
    raw = "|".join([
        f"team={team_id if team_id is not None else 'user:' + str(requested_by or '')}",
        f"sha={source_sha256}", f"model={model_id}",
        f"prompt={prompt_version}", f"settings={settings_hash}",
        f"schema={schema_version}",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_or_create_analysis_run(
    db: AsyncSession, *, source: CvReferenceSource, model_id: str,
    requested_by: int, settings_hash: str = "",
) -> CvAnalysisRun:
    """同团队同输入命中既有解析（不重复计费）；跨团队/不同输入新建。"""
    asset = await db.get(CvMediaAsset, source.media_asset_id)
    sha = asset.sha256 if asset else ""
    key = analysis_cache_key(
        team_id=source.team_id, source_sha256=sha, model_id=model_id,
        settings_hash=settings_hash, requested_by=requested_by,
    )
    existing = (await db.execute(
        select(CvAnalysisRun).where(CvAnalysisRun.cache_key == key)
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    run = CvAnalysisRun(
        team_id=source.team_id, source_id=source.id, model_id=model_id,
        source_sha256=sha, cache_key=key,
        prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
        status="pending", requested_by=requested_by,
    )
    db.add(run)
    await db.flush()
    return run


def _coerce_analysis_payload(raw: dict[str, Any], duration_ms: int) -> dict[str, Any]:
    """把解析输出收整为可存库结构；时间轴按原片时长校验。"""
    from app.schemas_commercial import AnalysisResult, AnalysisShot

    shots = [
        AnalysisShot(
            shot_id=str(shot["shot_id"]),
            start_ms=int(shot["start_ms"]),
            end_ms=int(shot["end_ms"]),
            keyframe_hints_ms=[int(t) for t in shot.get("keyframe_hints_ms") or []],
            observation=str(shot.get("observation") or ""),
            inference=str(shot.get("inference") or ""),
            uncertainty=str(shot.get("uncertainty") or ""),
        )
        for shot in raw.get("shots") or []
    ]
    result = AnalysisResult(
        source_id=0, duration_ms=duration_ms or 30_000, shots=shots,
        transcript=list(raw.get("transcript") or []),
        uncertainties=list(raw.get("uncertainties") or []),
    )
    result.validate()
    return {
        "duration_ms": result.duration_ms,
        "shots": [
            {
                "shot_id": s.shot_id, "start_ms": s.start_ms, "end_ms": s.end_ms,
                "keyframe_hints_ms": s.keyframe_hints_ms,
                "observation": s.observation, "inference": s.inference,
                "uncertainty": s.uncertainty,
            }
            for s in result.shots
        ],
        "transcript": result.transcript,
        "uncertainties": result.uncertainties,
        "schema_version": SCHEMA_VERSION,
    }


async def run_analysis(
    db: AsyncSession, *, run: CvAnalysisRun,
    analyzer: Callable[..., Awaitable[dict[str, Any]]],
) -> CvAnalysisRun:
    """执行解析（analyzer 可注入替身）：成功→校验+存档；失败→记录错误。"""
    source = await db.get(CvReferenceSource, run.source_id)
    duration_ms = (source.duration_ms if source else None) or 0
    try:
        raw = await analyzer(run)
        payload = _coerce_analysis_payload(raw, duration_ms)
    except AnalysisSchemaInvalid as exc:
        run.status = "failed"
        run.error = f"ANALYSIS_SCHEMA_INVALID: {exc}"
        await db.commit()
        return run
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error = f"ANALYSIS_FAILED: {exc}"
        await db.commit()
        return run
    run.status = "completed"
    run.result = payload
    await db.commit()
    return run
