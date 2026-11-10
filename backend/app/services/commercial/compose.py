"""成片合成与字幕策略（§7.3/§7.4/§15）：只剪不生成，母版不可改写。"""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models_commercial import CvGenerationAttempt

# 字幕策略（§7.4）：原片字幕时间不套用；草稿标未对齐；母版与烧录版分离
SUBTITLE_POLICY = {
    "reuse_source_timing": False,
    "draft_requires_alignment": True,
    "burn_creates_copy": True,
    "master_immutable": True,
}


class ComposeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ComposeResult:
    master_path: str
    total_adopt_ms: int
    clips: int


def build_subtitle_draft(
    *, shots: list[dict], source_transcript: list[dict] | None = None,
) -> list[dict]:
    """按计划采用区间生成“待校对”字幕草稿；绝不复用原片转写时间。"""
    draft: list[dict] = []
    cursor = 0
    for shot in shots:
        start, end = shot.get("adopt", (cursor, cursor + 2000))
        draft.append({
            "shot_key": shot.get("shot_key"),
            "text": shot.get("dialogue") or "",
            "start_ms": int(start),
            "end_ms": int(end),
            "aligned": False,  # 草稿默认未对齐，必须人工校对
            "source": "plan_timing",  # 时间来自计划，不来自原片
        })
        cursor = int(end)
    return draft


def _output_clip_path(output_key: str) -> Path:
    from app.services.commercial.storage import commercial_storage_root

    root = commercial_storage_root() / "outputs"
    return root / output_key


async def compose_production(
    db: AsyncSession,
    *,
    selections: list[tuple["CvGenerationAttempt", list[tuple[str, int, int]]]],
) -> ComposeResult:
    """仅合成 REVIEW_APPROVED 的 attempt 采用区间；全程无生成调用（R03）。

    selections: [(attempt, [(output_key, start_ms, end_ms), ...]), ...]
    """
    for attempt, ranges in selections:
        if attempt.status != "REVIEW_APPROVED":
            raise ComposeError(
                "REVIEW_REQUIRED",
                f"attempt {attempt.id} 未通过人工审核（当前 {attempt.status}），不能进入合成",
            )
        if not ranges:
            raise ComposeError("EMPTY_SELECTION", f"attempt {attempt.id} 缺少采用区间")

    export_key = f"export-{uuid.uuid4().hex[:12]}"
    export_dir = _output_clip_path("").parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    master_path = export_dir / f"{export_key}.mp4"

    # 逐段裁剪（ffmpeg 参数数组执行，不拼 shell）
    seg_paths: list[Path] = []
    total_ms = 0
    for index, (attempt, ranges) in enumerate(selections):
        for sub, (output_key, start_ms, end_ms) in enumerate(ranges):
            src = _output_clip_path(output_key)
            if not src.is_file():
                raise ComposeError("OUTPUT_MISSING", f"生成输出缺失：{src.name}")
            seg = export_dir / f"{export_key}-seg{index:02d}{sub:02d}.mp4"
            # 重编码保证帧级精确裁剪（-c copy 会吸附关键帧，采用区间会漂移）
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{start_ms / 1000:.3f}", "-to", f"{end_ms / 1000:.3f}",
                "-i", str(src), "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-an", str(seg),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise ComposeError("COMPOSE_FAILED", stderr.decode("utf-8", "replace")[:300])
            seg_paths.append(seg)
            total_ms += end_ms - start_ms

    # 顺序拼接
    concat_list = export_dir / f"{export_key}-list.txt"
    concat_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in seg_paths), encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(master_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ComposeError("COMPOSE_FAILED", stderr.decode("utf-8", "replace")[:300])
    for seg in seg_paths:
        seg.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)

    return ComposeResult(master_path=str(master_path), total_adopt_ms=total_ms, clips=len(selections))


def burn_subtitles(master_path: str, srt_path: str) -> str:
    """烧录字幕：生成独立副本，母版保持不变（SUBTITLE_POLICY）。"""
    target = str(Path(master_path).with_name(Path(master_path).stem + "-subtitled.mp4"))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", master_path, "-vf", f"subtitles={srt_path}", "-c:a", "copy", target,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise ComposeError("BURN_FAILED", result.stderr.decode("utf-8", "replace")[:300])
    return target
