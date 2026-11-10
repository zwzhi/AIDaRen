"""生成单元规划（§7.1/§7.2）：三种时长分开、能力档案驱动、台词不截断。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 中文口播自然语速估算（字/秒）：保守取值，宁可提示调整也不加速配音
_ZH_CHARS_PER_SECOND = 4.0


class PlanningError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class DialoguePacingError(PlanningError):
    """台词在采用区间内说不完：要求缩短文案/延长采用/合并镜头，不自动加速。"""

    def __init__(self, message: str) -> None:
        super().__init__("DIALOGUE_PACING", message)


def estimate_dialogue_ms(dialogue: str, *, chars_per_second: float = _ZH_CHARS_PER_SECOND) -> int:
    """台词自然口播时长估算（毫秒）。"""
    text = (dialogue or "").strip()
    if not text:
        return 0
    return int(len(text) / chars_per_second * 1000)


@dataclass
class GenerationUnitDraft:
    """一个生成单元：request_duration_ms 实际生成（计费），adopt_ranges 最终采用。"""

    unit_key: str
    request_duration_ms: int
    covered_shot_keys: list[str]
    adopt_ranges: list[tuple[str, int, int]]  # (shot_key, start_ms, end_ms) 相对单元起点
    params_version: int = 1
    notes: list[str] = field(default_factory=list)

    def as_plan_dict(self) -> dict[str, Any]:
        return {
            "unit_key": self.unit_key,
            "request_duration_ms": self.request_duration_ms,
            "covered_shot_keys": list(self.covered_shot_keys),
            "adopt_ranges": [list(r) for r in self.adopt_ranges],
            "params_version": self.params_version,
            "notes": list(self.notes),
        }


def _align_duration(target_ms: int, caps: Any) -> int:
    """把时长对齐到能力档案的 [min, max, step]。"""
    import math

    step = max(1, int(caps.duration_step_ms))
    minimum = int(caps.duration_min_ms)
    maximum = int(caps.duration_max_ms)
    aligned = int(math.ceil(target_ms / step) * step)
    if aligned < minimum:
        aligned = minimum
    if aligned > maximum:
        aligned = maximum
    # 对齐可能跌破下限（step > min 的极端档案）：抬回最小并再对齐
    if aligned % step and aligned == maximum:
        aligned = int(math.floor(maximum / step) * step)
    return aligned


def compile_generation_units(shots: list[dict[str, Any]], caps: Any) -> list[GenerationUnitDraft]:
    """把目标镜头序列编译为合法生成单元。

    规则（§7.2）：
    - 相邻短镜头优先合并（合并目标仍在档案例内则同单元，多镜头共享一次生成）；
    - 单镜头目标小于最小生成时长：生成 min、采用目标区间（生成5秒采用2秒）；
    - 镜头目标超过最大时长：按最大值拆分为多单元，采用区间衔接；
    - 台词估算时长必须 ≤ 该镜头采用区间，否则 DialoguePacingError。
    """
    if not shots:
        raise PlanningError("PLAN_EMPTY", "没有可规划的镜头")
    units: list[GenerationUnitDraft] = []
    index = 0
    counter = 0

    def _new_unit(pending: list[dict[str, Any]]) -> GenerationUnitDraft:
        nonlocal counter
        counter += 1
        return GenerationUnitDraft(
            unit_key=f"U{counter:03d}",
            request_duration_ms=0,
            covered_shot_keys=[],
            adopt_ranges=[],
        )

    while index < len(shots):
        shot = shots[index]
        target = int(shot.get("target_duration_ms") or 0)
        dialogue = str(shot.get("dialogue") or "")
        pacing_ms = estimate_dialogue_ms(dialogue)
        if pacing_ms > target:
            raise DialoguePacingError(
                f"镜头 {shot.get('shot_key')} 台词约需 {pacing_ms}ms，超过采用区间 {target}ms；"
                "请缩短文案、延长镜头时长或合并相邻镜头后重新规划（不会自动加速配音）"
            )

        if target <= caps.duration_max_ms:
            # 尝试与后续相邻短镜头合并成一个合法单元
            merged: list[dict[str, Any]] = [shot]
            merged_target = target
            nxt = index + 1
            while nxt < len(shots):
                next_shot = shots[nxt]
                next_target = int(next_shot.get("target_duration_ms") or 0)
                next_pacing = estimate_dialogue_ms(str(next_shot.get("dialogue") or ""))
                if next_pacing > next_target:
                    raise DialoguePacingError(
                        f"镜头 {next_shot.get('shot_key')} 台词约需 {next_pacing}ms，"
                        f"超过采用区间 {next_target}ms；请缩短文案或调整镜头"
                    )
                if merged_target + next_target <= caps.duration_max_ms:
                    merged.append(next_shot)
                    merged_target += next_target
                    nxt += 1
                else:
                    break
            unit = _new_unit(merged)
            unit.covered_shot_keys = [str(s.get("shot_key")) for s in merged]
            offset = 0
            for s in merged:
                dur = int(s.get("target_duration_ms") or 0)
                unit.adopt_ranges.append((str(s.get("shot_key")), offset, offset + dur))
                offset += dur
            unit.request_duration_ms = _align_duration(merged_target, caps)
            if unit.request_duration_ms < merged_target:
                # 对齐后仍不足（理论上 _align 已保证 ≥ min，但合并目标可能 > max 已被拆分）
                unit.request_duration_ms = _align_duration(merged_target, caps)
            units.append(unit)
            index = nxt
        else:
            # 单镜头目标超过最大时长：按最大值顺序拆分为多单元（G07）
            remaining = target
            seg_start = 0
            while remaining > 0:
                seg_ms = min(remaining, caps.duration_max_ms)
                unit = _new_unit([shot])
                suffix = f"{unit.unit_key}"
                unit.covered_shot_keys = [str(shot.get("shot_key"))]
                unit.request_duration_ms = _align_duration(seg_ms, caps)
                unit.adopt_ranges = [(str(shot.get("shot_key")), 0, seg_ms)]
                unit.notes.append(f"超长镜头拆分：原目标 {target}ms，本段 {seg_ms}ms，原片内区间起点 {seg_start}ms")
                units.append(unit)
                seg_start += seg_ms
                remaining -= seg_ms
            index += 1
    return units
