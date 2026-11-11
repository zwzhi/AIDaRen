"""Gemini-backed replication analysis and script endpoints.

The first vertical slice is fixture/mock-only. It persists immutable Shot Graph
and Script Version revisions and never falls back to a paid provider call.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_commercial import (
    CvProduction,
    CvProductVersion,
    CvReplicationProject,
    CvScriptVersion,
    CvShotGraph,
)
from app.schemas_commercial import ScriptBatchPayload, ScriptVersionPayload, ShotGraphPayload
from app.services.commercial.replication import (
    catalog_claim_ids,
    script_payload_to_json,
    shot_graph_payload_to_records,
    validate_script_contract,
)
from app.services.providers.atlas.gemini import GeminiAdapter

router = APIRouter()


class ReplicationCreateBody(BaseModel):
    production_id: int = Field(gt=0)
    mode: str = Field(default="structural_rewrite", pattern="^(structural_rewrite|high_fidelity)$")
    route_reason: str = ""


@router.post("/replications", summary="创建复刻项目")
async def create_replication(
    body: ReplicationCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    production = await db.get(CvProduction, body.production_id)
    if production is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    if (user.role or "user") != "admin" and production.created_by != user.id:
        raise HTTPException(status_code=403, detail="无权创建该复刻项目")
    existing = await db.scalar(
        select(CvReplicationProject).where(CvReplicationProject.production_id == production.id)
    )
    if existing is not None:
        return {"id": existing.id, "production_id": existing.production_id,
                "mode": existing.mode, "status": existing.status, "reused": True}
    project = CvReplicationProject(
        production_id=production.id,
        mode=body.mode,
        route_reason=body.route_reason,
        created_by=user.id,
    )
    db.add(project)
    await db.commit()
    return {"id": project.id, "production_id": project.production_id,
            "mode": project.mode, "status": project.status, "reused": False}


class AnalyzeBody(BaseModel):
    fixture: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, gt=0)


class ScriptBody(ScriptBatchPayload):
    fixture: dict[str, Any] | None = None
    scripts: list[ScriptVersionPayload] = Field(default_factory=list)


async def _get_project(db: AsyncSession, project_id: int, user: User) -> CvReplicationProject:
    project = await db.get(CvReplicationProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="复刻项目不存在")
    if (user.role or "user") != "admin" and project.created_by != user.id:
        raise HTTPException(status_code=403, detail="无权访问该复刻项目")
    return project


async def _catalog_for_project(db: AsyncSession, project: CvReplicationProject) -> list[dict[str, Any]]:
    production = await db.get(CvProduction, project.production_id)
    if production is None:
        return []
    version = await db.get(CvProductVersion, production.product_version_id)
    claims = version.claims if version is not None and isinstance(version.claims, list) else []
    return [dict(item) for item in claims if isinstance(item, dict)]


def _graph_response(rows: list[CvShotGraph], revision: int | None = None) -> dict[str, Any]:
    return {
        "revision": revision,
        "shots": [
            {
                "id": row.id,
                "shot_key": row.shot_key,
                "start": row.start_ms,
                "end": row.end_ms,
                "purpose": row.purpose,
                "camera": row.camera_json or {},
                "composition": row.composition_json or {},
                "action": row.action_json or {},
                "emotion": row.emotion_json or {},
                "product_presence": row.product_presence,
                "product_confidence": float(row.product_confidence or 0),
                "product_evidence": row.product_evidence_json or [],
                "anchor_candidates": row.anchor_candidates_json or [],
                "source_span": row.source_span_json or {},
                "status": row.status,
            }
            for row in rows
        ],
    }


@router.post("/replications/{project_id}/analyze", summary="生成复刻 Shot Graph（fixture/mock）")
async def analyze_replication(
    project_id: int,
    body: AnalyzeBody | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _get_project(db, project_id, user)
    body = body or AnalyzeBody()
    duration = body.duration_ms or 30_000
    adapter = GeminiAdapter.from_fixture(body.fixture or {
        "duration_ms": duration,
        "shots": [{
            "shot_key": "shot-1", "start": 0, "end": duration,
            "purpose": "main", "product_presence": "unknown",
            "product_confidence": 0.0, "product_evidence": [],
            "anchor_candidates": [], "source_span": {"start": 0, "end": duration},
        }],
    })
    payload: ShotGraphPayload = adapter.analyze_video({"duration_ms": duration})
    current = await db.scalar(
        select(func.max(CvShotGraph.revision)).where(CvShotGraph.replication_project_id == project.id)
    )
    revision = int(current or 0) + 1
    for record in shot_graph_payload_to_records(payload):
        db.add(CvShotGraph(
            replication_project_id=project.id,
            revision=revision,
            **record,
        ))
    project.status = "analyzed"
    await db.commit()
    rows = list((await db.execute(select(CvShotGraph).where(
        CvShotGraph.replication_project_id == project.id,
        CvShotGraph.revision == revision,
    ).order_by(CvShotGraph.start_ms))).scalars().all())
    response = _graph_response(rows, revision)
    response["needs_human_review"] = any(row.status == "needs_human_review" for row in rows)
    return response


@router.get("/replications/{project_id}/shot-graph", summary="读取最新 Shot Graph")
async def get_shot_graph(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _get_project(db, project_id, user)
    revision = await db.scalar(
        select(func.max(CvShotGraph.revision)).where(CvShotGraph.replication_project_id == project.id)
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="尚未生成 Shot Graph")
    rows = list((await db.execute(select(CvShotGraph).where(
        CvShotGraph.replication_project_id == project.id,
        CvShotGraph.revision == revision,
    ).order_by(CvShotGraph.start_ms))).scalars().all())
    return _graph_response(rows, int(revision))


@router.post("/replications/{project_id}/scripts", summary="生成结构化复刻脚本")
async def create_scripts(
    project_id: int,
    body: ScriptBody | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _get_project(db, project_id, user)
    body = body or ScriptBody()
    revision = await db.scalar(select(func.max(CvShotGraph.revision)).where(
        CvShotGraph.replication_project_id == project.id
    ))
    if revision is None:
        raise HTTPException(status_code=409, detail="请先完成视频分析")
    rows = list((await db.execute(select(CvShotGraph).where(
        CvShotGraph.replication_project_id == project.id,
        CvShotGraph.revision == revision,
    ).order_by(CvShotGraph.start_ms))).scalars().all())
    claims = await _catalog_for_project(db, project)
    claim_ids = catalog_claim_ids(claims)
    locked = {row.shot_key: row.end_ms - row.start_ms for row in rows}
    scripts = list(body.scripts)
    if not scripts:
        fixture = body.fixture or {}
        adapter = GeminiAdapter.from_fixture(fixture)
        for row in rows:
            scripts.extend(adapter.adapt_scripts({
                "mode": body.mode,
                "shot": {
                    "shot_key": row.shot_key,
                    "start": row.start_ms,
                    "end": row.end_ms,
                    "purpose": row.purpose,
                    "product_presence": row.product_presence,
                },
                "catalog_claims": claims,
                "locked_duration_ms": locked[row.shot_key] if body.mode == "high_fidelity" else None,
            }))
    normalized_scripts: list[ScriptVersionPayload] = []
    for script in scripts:
        if body.mode != "structural_rewrite" and script.mode == "structural_rewrite":
            script = script.model_copy(update={"mode": body.mode})
        validate_script_contract(script, catalog_claim_ids=claim_ids, locked_durations=locked)
        normalized_scripts.append(script)
    scripts = normalized_scripts
    version = int(await db.scalar(select(func.max(CvScriptVersion.version)).where(
        CvScriptVersion.replication_project_id == project.id
    )) or 0) + 1
    script_json = [script_payload_to_json(item) for item in scripts]
    all_claim_ids = sorted({claim_id for item in scripts for claim_id in item.claim_ids})
    db_script = CvScriptVersion(
        replication_project_id=project.id,
        version=version,
        shot_graph_revision=int(revision),
        mode=body.mode,
        script_json={"scripts": script_json},
        claim_ids_json=all_claim_ids,
        model_id="fixture-gemini",
        model_version="fixture-1",
        status="draft",
    )
    db.add(db_script)
    await db.flush()
    project.current_script_version_id = db_script.id
    project.status = "script_review"
    await db.commit()
    return {"id": db_script.id, "version": version, "status": db_script.status,
            "mode": db_script.mode, "scripts": script_json,
            "needs_human_review": any(row.status == "needs_human_review" for row in rows)}


async def _approve_script(
    version_id: int,
    db: AsyncSession,
    user: User,
    project_id: int | None = None,
) -> dict[str, Any]:
    script = await db.get(CvScriptVersion, version_id)
    if script is None:
        raise HTTPException(status_code=404, detail="脚本版本不存在")
    project = await _get_project(db, script.replication_project_id, user)
    if project_id is not None and project.id != project_id:
        raise HTTPException(status_code=404, detail="脚本版本不存在")
    if script.status not in {"draft", "review", "script_review"}:
        raise HTTPException(status_code=409, detail="脚本当前状态不可批准")
    script.status = "approved"
    script.approved_by = user.id
    script.approved_at = datetime.now(UTC)
    project.current_script_version_id = script.id
    project.status = "anchor_review"
    await db.commit()
    return {"id": script.id, "version": script.version, "status": script.status,
            "approved_at": script.approved_at.isoformat()}


@router.post("/scripts/{version_id}/approve", summary="批准脚本版本")
async def approve_script(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _approve_script(version_id, db, user)


@router.post("/replications/{project_id}/scripts/{version_id}/approve", include_in_schema=False)
async def approve_replication_script(
    project_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _approve_script(version_id, db, user, project_id)


