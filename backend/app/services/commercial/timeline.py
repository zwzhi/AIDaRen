"""Minimal deterministic timeline compiler.

The compiler deliberately preserves the sequence supplied by the caller.  A
shot graph or editor decides order, while this service only validates and
normalises the segments consumed by preview/final composition.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


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


def compile_timeline(segments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Functional convenience wrapper for callers that do not retain a compiler."""
    return TimelineCompiler().compile(segments)

