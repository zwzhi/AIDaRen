"""Minimal deterministic timeline compiler.

The compiler deliberately preserves the sequence supplied by the caller.  A
shot graph or editor decides order, while this service only validates and
normalises the segments consumed by preview/final composition.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass
class PreviewExport:
    """纯时间轴预览快照，可在持久化层创建 CvExport。"""

    kind: str
    segments: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    total_adopt_ms: int
    frozen_version_hash: str
    output_keys: tuple[str, ...] = ()


class TimelineCompiler:
    """Validate a caller-owned ordered sequence of timeline segments."""

    def compile(self, segments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        compiled: list[dict[str, Any]] = []
        for index, segment in enumerate(segments):
            row = dict(segment)
            shot_key = str(row.get("shot_key") or "")
            if not shot_key:
                raise ValueError(f"timeline segment {index} is missing shot_key")
            start_ms = int(row.get("start_ms") or 0)
            end_ms = int(row.get("end_ms") or 0)
            if start_ms < 0 or end_ms <= start_ms:
                raise ValueError(f"timeline segment {shot_key} has invalid bounds")
            row["shot_key"] = shot_key
            row["start_ms"] = start_ms
            row["end_ms"] = end_ms
            compiled.append(row)
        return compiled

    def compose_preview(
        self,
        segment_outputs: Iterable[Mapping[str, Any]],
        timeline: Iterable[Mapping[str, Any]],
        *,
        frozen_version_hash: str = "",
    ) -> PreviewExport:
        """按外部时间轴顺序组装 Mock/沙箱片段预览。

        片段输出可以乱序到达，合成顺序始终由 timeline 决定。缺失片段
        明确报错，避免生成一个看似完整但缺镜头的预览。
        """
        compiled_timeline = self.compile(timeline)
        outputs = [dict(item) for item in segment_outputs]
        by_shot = {str(item.get("shot_key") or ""): item for item in outputs}
        segments: list[dict[str, Any]] = []
        output_keys: list[str] = []
        for row in compiled_timeline:
            shot_key = row["shot_key"]
            output = by_shot.get(shot_key)
            if output is None:
                raise ValueError(f"preview segment output missing shot_key {shot_key}")
            merged = dict(row)
            merged.update({key: value for key, value in output.items() if key != "shot_key"})
            segments.append(merged)
            if merged.get("output_key"):
                output_keys.append(str(merged["output_key"]))
        total = sum(int(item["end_ms"]) - int(item["start_ms"]) for item in compiled_timeline)
        return PreviewExport(
            kind="partial_preview",
            segments=segments,
            timeline=compiled_timeline,
            total_adopt_ms=total,
            frozen_version_hash=str(frozen_version_hash or ""),
            output_keys=tuple(output_keys),
        )


def compile_timeline(segments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Functional convenience wrapper for callers that do not retain a compiler."""
    return TimelineCompiler().compile(segments)

