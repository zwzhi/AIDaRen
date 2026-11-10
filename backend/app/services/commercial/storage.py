"""商业域私有媒体存储与探测。

- 文件保存到 COMMERCIAL_STORAGE_ROOT 下的随机对象键，绝不写入 /static；
- 上传时计算 sha256，用 ffprobe（视频/音频）或 Pillow（图片）验证真实
  媒体属性，伪装 MIME 在此被拒绝；
- FFmpeg/FFprobe 以参数数组执行，不拼接 shell 命令。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class MediaValidationError(Exception):
    """上传媒体无法通过真实格式探测或超出限制。"""


@dataclass(frozen=True)
class MediaProbe:
    """探测结果：kind 与真实 MIME 由探测器给出，不信任上传声明。"""

    kind: str  # image | video | audio
    mime: str
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    has_audio: bool | None = None


def commercial_storage_root() -> Path:
    raw = get_settings().commercial_storage_root
    root = Path(raw)
    if not root.is_absolute():
        root = _BACKEND_DIR / raw
    root.mkdir(parents=True, exist_ok=True)
    return root


def asset_disk_path(object_key: str) -> Path:
    """对象键 → 私有目录内路径；拒绝路径穿越。"""
    root = commercial_storage_root()
    path = (root / object_key).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise MediaValidationError("非法对象键")
    return path


def new_object_key(role: str, ext: str) -> str:
    """随机对象键：role/日期/随机串，不可猜测、不含用户输入。"""
    day = datetime.now(UTC).strftime("%Y%m%d")
    token = secrets.token_hex(16)
    clean_ext = ext.lower().lstrip(".").replace("/", "")[:8] or "bin"
    return f"{role}/{day}/{token}.{clean_ext}"


async def _run_ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        get_settings().ffprobe_path or "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise MediaValidationError("无法识别的媒体格式（ffprobe 解析失败）")
    try:
        return json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:  # pragma: no cover - 防御
        raise MediaValidationError("媒体探测输出异常") from exc


def _probe_image(path: Path, size: int, sha: str) -> MediaProbe:
    from PIL import Image

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
    except Exception as exc:
        raise MediaValidationError("无法识别的图片格式") from exc
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(fmt)
    if mime is None:
        raise MediaValidationError(f"不支持的图片格式：{fmt}")
    return MediaProbe(kind="image", mime=mime, size_bytes=size, sha256=sha, width=width, height=height)


def _probe_av(path: Path, size: int, sha: str) -> MediaProbe:  # pragma: no cover - 保留占位
    raise NotImplementedError


async def probe_media_bytes(raw: bytes, filename: str, *, role_is_video: bool) -> MediaProbe:
    """字节落盘到临时文件并做真实探测；不信任扩展名与 Content-Type。"""
    import tempfile

    sha = hashlib.sha256(raw).hexdigest()
    suffix = Path(filename or "").suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        head = raw[:16]
        is_png = head.startswith(b"\x89PNG\r\n\x1a\n")
        is_jpg = head.startswith(b"\xff\xd8\xff")
        is_webp = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
        if is_png or is_jpg or is_webp:
            return _probe_image(tmp_path, len(raw), sha)
        data = await _run_ffprobe(tmp_path)
        streams = data.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None and audio is None:
            raise MediaValidationError("媒体中不含可用的视频或音频轨")
        if video is not None:
            duration_s = float(
                (data.get("format") or {}).get("duration")
                or video.get("duration")
                or 0
            )
            return MediaProbe(
                kind="video",
                mime="video/mp4",
                size_bytes=len(raw),
                sha256=sha,
                width=int(video.get("width") or 0) or None,
                height=int(video.get("height") or 0) or None,
                duration_ms=int(duration_s * 1000) if duration_s else None,
                has_audio=audio is not None,
            )
        duration_s = float((data.get("format") or {}).get("duration") or 0)
        return MediaProbe(
            kind="audio",
            mime="audio/mpeg",
            size_bytes=len(raw),
            sha256=sha,
            duration_ms=int(duration_s * 1000) if duration_s else None,
            has_audio=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def persist_asset_bytes(raw: bytes, object_key: str) -> None:
    """写入私有存储目录（父目录自动创建）。"""
    path = asset_disk_path(object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
