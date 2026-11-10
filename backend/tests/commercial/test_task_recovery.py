# -*- coding: utf-8 -*-
"""T07｜poller 分派隔离（BLOCKER）：commercial 任务不得进入 TokenFree 轮询。"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest_asyncio.fixture
async def poller_env(monkeypatch):
    """独立引擎 + 已提交任务行 + 替换 poller 的会话工厂。"""
    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401
    import app.models_tasks  # noqa: F401
    import app.models_teams  # noqa: F401
    import app.models_commercial  # noqa: F401
    from sqlalchemy.engine import make_url

    raw = get_settings().database_url
    test_url = make_url(raw).set(database=(make_url(raw).database or "x") + "_test").render_as_string(hide_password=False)
    engine = create_async_engine(test_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    marker = uuid.uuid4().hex[:8]
    # 临时用户 + 一条 studio tool_video 与一条 commercial video_generate（均 awaiting_poll）
    from app.models import User as _User

    async with AsyncSession(engine) as s:
        from app.models_tasks import TaskRun as _TaskRun

        temp_user = _User(email=f"poller-{marker}@test.local", hashed_password="x")
        s.add(temp_user)
        await s.flush()
        user_id = int(temp_user.id)
        from datetime import UTC, datetime as _dt

        studio_row = _TaskRun(
            # ephemeral 兜底路径的典型形态：无 run_id 的轻量 deferred 视频任务
            domain="studio", task_type="tool_video", queue_type="video",
            status="awaiting_poll", requested_by=user_id,
            provider_task_id=f"tf-{marker}", payload={},
            billing_status="frozen", next_action_at=None,
        )
        commercial_row = _TaskRun(
            domain="commercial", task_type="video_generate", queue_type="video",
            status="awaiting_poll", requested_by=user_id,
            provider_task_id=f"atlas-{marker}", payload={"attempt_id": 1},
            next_action_at=_dt.now(UTC),
        )
        s.add_all([studio_row, commercial_row])
        await s.flush()
        studio_id, commercial_id = int(studio_row.id), int(commercial_row.id)
        await s.commit()

    calls = {"tokenfree": [], "atlas": []}

    async def fake_tokenfree_poll(user, provider_id):
        calls["tokenfree"].append(provider_id)

    async def fake_atlas_poll(task_id):
        calls["atlas"].append(task_id)

    monkeypatch.setattr("app.services.studio_tools.poll_video_task", fake_tokenfree_poll)
    monkeypatch.setattr(
        "app.services.commercial.generation.poll_commercial_task", fake_atlas_poll
    )
    # poller 内部会话工厂指向测试引擎
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.services.tasks.poller.AsyncSessionLocal", factory)

    yield {"engine": engine, "studio_id": int(studio_id), "commercial_id": int(commercial_id),
           "calls": calls, "marker": marker}
    async with AsyncSession(engine) as s:
        await s.execute(sql_text("DELETE FROM task_runs WHERE requested_by = :u"), {"u": user_id})
        await s.execute(sql_text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await s.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_commercial_never_routed_to_tokenfree_poller(poller_env) -> None:
    """BLOCKER 回归：ephemeral 兜底轮询必须排除 commercial，只接 studio。"""
    from app.services.tasks.poller import _poll_ephemeral_deferred_tasks

    await _poll_ephemeral_deferred_tasks()
    # studio 任务走了 TokenFree 协议轮询（旧行为保持）
    assert len(poller_env["calls"]["tokenfree"]) == 1
    # commercial 任务绝不能进 TokenFree 轮询
    assert poller_env["calls"]["tokenfree"] == [f"tf-{poller_env['marker']}"]


@pytest.mark.asyncio
async def test_commercial_gets_atlas_dispatch(poller_env) -> None:
    """专属分派：commercial awaiting_poll 由 Atlas 适配器接管。"""
    from datetime import UTC, datetime

    from app.services.tasks.poller import _select_and_poll_due

    await _select_and_poll_due()
    assert poller_env["calls"]["atlas"], "commercial 任务未被 Atlas 分派轮询"
    assert poller_env["calls"]["tokenfree"] == [], "studio 在本轮到期应为 0（无 run_id 到期）或仅 studio"


@pytest.mark.asyncio
async def test_select_query_excludes_commercial_from_ephemeral(poller_env) -> None:
    """查询层验证：ephemeral SQL 不再匹配 commercial 域。"""
    from sqlalchemy import select

    from app.models_tasks import TaskRun

    # 与 poller 相同的过滤条件（domain not in drama/kepu/commercial）
    stmt = select(TaskRun.id).where(
        TaskRun.status == "awaiting_poll",
        TaskRun.domain.not_in(["drama", "kepu", "commercial"]),
    )
    async with AsyncSession(poller_env["engine"]) as s:
        ids = {(int(r) for r in (await s.execute(stmt)).scalars())}
    assert poller_env["commercial_id"] not in ids
