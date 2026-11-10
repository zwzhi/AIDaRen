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


async def _probe_clip(path: Path) -> dict:
    """ffprobe 片段：返回 {"has_audio", "duration_ms"}；探测失败按缺文件处理。"""
    import json as _json

    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise ComposeError("OUTPUT_MISSING", f"生成输出缺失或不可读：{path.name}")
    data = _json.loads(stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams") or []
    has_audio = any(st.get("codec_type") == "audio" for st in streams)
    duration_s = float((data.get("format") or {}).get("duration") or 0)
    return {"has_audio": has_audio, "duration_ms": int(duration_s * 1000)}


async def compose_production(
    db: AsyncSession,
    *,
    selections: list[tuple["CvGenerationAttempt", list[tuple[str, int, int]]]],
) -> ComposeResult:
    """仅合成 REVIEW_APPROVED 的 attempt 采用区间；全程无生成调用（R03）。

    P1-7：音轨全程保留（分段重编码 -c:a aac；拼接 -c copy）；
    audio_required 的片段缺音轨 → 明确阻断（不填充静音冒充）。
    P2-2：采用区间不得超出实际媒体时长（不静默截短掩盖问题）。
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

    # 预检：实际媒体属性（音轨/时长）
    probe_cache: dict[str, dict] = {}
    any_audio = False
    for attempt, ranges in selections:
        required = bool(((attempt.params_json or {}).get("audio_required")))
        for output_key, _start, _end in ranges:
            if output_key in probe_cache:
                continue
            src = _output_clip_path(output_key)
            probe_cache[output_key] = await _probe_clip(src)
        for output_key, start_ms, end_ms in ranges:
            info = probe_cache[output_key]
            if required and not info["has_audio"]:
                raise ComposeError(
                    "AUDIO_MISSING",
                    f"attempt {attempt.id} 要求口播音频，但其生成输出 {output_key} 无音轨；"
                    "请重做该镜头（不会填充静音冒充通过）",
                )
            if end_ms > info["duration_ms"] + 50:  # 50ms 容差（容器时长取整）
                raise ComposeError(
                    "ADOPT_RANGE_EXCEEDS_MEDIA",
                    f"attempt {attempt.id} 采用区间 [{start_ms},{end_ms}]ms 超出输出实际时长 "
                    f"{info['duration_ms']}ms；请重做或调整采用区间（不自动截短）",
                )
            any_audio = any_audio or info["has_audio"]

    export_key = f"export-{uuid.uuid4().hex[:12]}"
    export_dir = _output_clip_path("").parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    master_path = export_dir / f"{export_key}.mp4"

    # 逐段裁剪（ffmpeg 参数数组执行，不拼 shell）；
    # 统一重编码为 H264 + AAC 44.1k 立体声以保证 concat 一致性；
    # 片段本身无音轨且未要求口播时，用 anullsrc 补静音轨维持流一致。
    seg_paths: list[Path] = []
    total_ms = 0
    for index, (attempt, ranges) in enumerate(selections):
        for sub, (output_key, start_ms, end_ms) in enumerate(ranges):
            src = _output_clip_path(output_key)
            info = probe_cache[output_key]
            seg = export_dir / f"{export_key}-seg{index:02d}{sub:02d}.mp4"
            cmd = ["ffmpeg", "-y", "-loglevel", "error",
                   "-ss", f"{start_ms / 1000:.3f}", "-to", f"{end_ms / 1000:.3f}",
                   "-i", str(src)]
            need_pad = any_audio and not info["has_audio"]
            if need_pad:
                seg_seconds = max(0.05, (end_ms - start_ms) / 1000)
                cmd += ["-f", "lavfi", "-t", f"{seg_seconds:.3f}",
                        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
            if info["has_audio"] or need_pad:
                aindex = 1 if need_pad else 0
                cmd += ["-map", "0:v"]
                if need_pad:
                    cmd += ["-map", "1:a"]
                else:
                    cmd += ["-map", "0:a?"]
                cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2",
                        "-af", "aresample=async=1:first_pts=0"]
            else:
                cmd += ["-an"]
            cmd.append(str(seg))
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise ComposeError("COMPOSE_FAILED", stderr.decode("utf-8", "replace")[:300])
            seg_paths.append(seg)
            total_ms += end_ms - start_ms

    if not any_audio:
        # 全部片段均无音轨且均未要求口播：无声模板按计划合法，输出无声母版
        pass

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


def _ffmpeg_subtitle_arg(srt_path: str) -> str:
    """subtitles 滤镜路径转义：Windows 盘符冒号与反斜杠按滤镜语法处理。"""
    posix = str(srt_path).replace("\\", "/")
    escaped = posix.replace(":", "\:")
    return f"subtitles='{escaped}'"


def burn_subtitles(master_path: str, srt_path: str) -> str:
    """烧录字幕：生成独立副本，母版保持不变（SUBTITLE_POLICY）。"""
    target = str(Path(master_path).with_name(Path(master_path).stem + "-subtitled.mp4"))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", master_path, "-vf", _ffmpeg_subtitle_arg(srt_path), "-c:a", "copy", target,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise ComposeError("BURN_FAILED", result.stderr.decode("utf-8", "replace")[:300])
    return target
