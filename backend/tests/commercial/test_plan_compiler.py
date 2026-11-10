# -*- coding: utf-8 -*-
"""T05｜生成单元规划：三种时长分开、能力档案驱动、台词不截断（G06/G07）。"""
from __future__ import annotations

import pytest

from app.services.commercial.planning import (
    DialoguePacingError,
    GenerationUnitDraft,
    compile_generation_units,
)


def _shot(key: str, dialogue: str, target_ms: int) -> dict:
    return {"shot_key": key, "dialogue": dialogue, "target_duration_ms": target_ms}


def _caps(min_ms: int = 5_000, max_ms: int = 10_000, step_ms: int = 1_000):
    from app.services.providers.atlas.h3_reference import H3Capabilities

    return H3Capabilities(
        duration_min_ms=min_ms, duration_max_ms=max_ms, duration_step_ms=step_ms,
        resolutions=frozenset({"768p"}), aspect_ratios=frozenset({"9:16"}),
        audio_supported=True, voice_reference_supported=True,
    )


# ---------------------------------------------------------------- G06 生成5秒采用2秒
def test_generate_five_adopt_two() -> None:
    """2 秒目标镜头遇 5 秒最小生成限制：单元生成 5s、采用 2s，两种时长分开保存。"""
    units = compile_generation_units([_shot("S01", "你好呀", 2_000)], _caps())
    assert len(units) == 1
    unit = units[0]
    assert unit.request_duration_ms == 5_000       # 实际生成时长（计费口径）
    assert unit.adopt_ranges == [("S01", 0, 2_000)]  # 最终采用区间
    assert unit.covered_shot_keys == ["S01"]


def test_short_dialogue_not_truncated_in_adoption() -> None:
    """采用区间必须完整覆盖台词时长：台词说不完 → 报错要求调整，不自动加速。"""
    long_dialogue = "这是一段特别长的台词需要超过两秒才能自然说完不可以被截断"
    with pytest.raises(DialoguePacingError) as exc:
        compile_generation_units([_shot("S01", long_dialogue, 2_000)], _caps())
    assert "缩短" in str(exc.value) or "延长" in str(exc.value) or "调整" in str(exc.value)


def test_dialogue_fits_full_generation_when_target_equals_min() -> None:
    units = compile_generation_units([_shot("S01", "这款精华质地清爽好用", 5_000)], _caps())
    assert units[0].request_duration_ms == 5_000
    assert units[0].adopt_ranges == [("S01", 0, 5_000)]


# ---------------------------------------------------------------- 合并方案
def test_adjacent_short_shots_merged() -> None:
    """相邻短镜头优先合并成一个合法单元（2s+2s → 5s? 合并后 4s < min 仍需补齐到 5s）。"""
    units = compile_generation_units(
        [_shot("S01", "你好", 2_000), _shot("S02", "看这里", 2_000)], _caps()
    )
    assert len(units) == 1
    unit = units[0]
    assert unit.covered_shot_keys == ["S01", "S02"]
    assert unit.request_duration_ms == 5_000  # 4s 合并目标 → 抬到最小生成时长
    assert unit.adopt_ranges == [("S01", 0, 2_000), ("S02", 2_000, 4_000)]


# ---------------------------------------------------------------- G07 长视频拆分
def test_180s_split_into_legal_units() -> None:
    """180 秒目标拆成合法单元：单次请求不超上限（不发送非法单次时长）。"""
    shots = [_shot(f"S{i:02d}", "这一镜的台词长度适中", 18_000) for i in range(10)]
    units = compile_generation_units(shots, _caps())
    assert sum(u.request_duration_ms for u in units) >= 180_000
    for unit in units:
        assert 5_000 <= unit.request_duration_ms <= 10_000  # 全部合法
    # 每个镜头都被覆盖（超长镜头允许多单元分段），总采用时长守恒
    covered = [key for u in units for key in u.covered_shot_keys]
    assert set(covered) == {s["shot_key"] for s in shots}
    total_adopt = sum(end - start for u in units for _, start, end in u.adopt_ranges)
    assert total_adopt == 180_000  # 拆分不丢时长


# ---------------------------------------------------------------- 能力档案驱动（不写死）
def test_duration_limits_from_capability_profile() -> None:
    """同一组镜头在不同能力档案下产出不同单元时长：限制来自档案，非硬编码。"""
    shots = [_shot("S01", "台词适中就好", 3_000)]
    caps_a = _caps(min_ms=5_000, max_ms=10_000)
    caps_b = _caps(min_ms=3_000, max_ms=6_000)
    units_a = compile_generation_units(shots, caps_a)
    units_b = compile_generation_units(shots, caps_b)
    assert units_a[0].request_duration_ms == 5_000
    assert units_b[0].request_duration_ms == 3_000


def test_step_alignment_respected() -> None:
    units = compile_generation_units([_shot("S01", "短台词", 4_400)], _caps(step_ms=1_000))
    assert units[0].request_duration_ms % 1_000 == 0


# ---------------------------------------------------------------- 单元结构
def test_unit_draft_fields_complete() -> None:
    unit = GenerationUnitDraft(
        unit_key="U01", request_duration_ms=5_000, covered_shot_keys=["S01"],
        adopt_ranges=[("S01", 0, 2_000)],
    )
    data = unit.as_plan_dict()
    assert data["request_duration_ms"] == 5_000
    assert data["adopt_ranges"][0][2] == 2_000
    # 三种时长口径在结构中分别存在
    assert "request_duration_ms" in data and "adopt_ranges" in data
