"""商业域 Mock 供应商层（开发/测试专用，显著标记，绝不冒充真实联调）。

- 所有返回值带 mock 标记（prediction 以 MOCK- 开头、价目源标 mock）；
- 生产开关 COMMERCIAL_MOCK_MODE=true 时才可走此路径；关闭后仅真实适配器；
- Mock 报价使用 H3 Developer 历史展示价 $0.015/s 作为【模拟价】，仅用于
  开发流程演示，不代表真实报价（真实报价必须走 /calculate）。
"""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

MOCK_LABEL = "MOCK"
MOCK_USD_PER_SEC = Decimal("0.015")  # 历史展示价，仅作开发模拟


def mock_enabled() -> bool:
    from app.config import get_settings

    return bool(get_settings().commercial_mock_mode)


def mock_analyze_payload(duration_ms: int) -> dict[str, Any]:
    """确定性三镜头解析（问题引入—商品展示—总结引导），标注 mock。"""
    d = max(1, int(duration_ms))
    s1_end, s2_end = int(d * 0.3), int(d * 0.8)
    return {
        "duration_ms": d,
        "shots": [
            {"shot_id": "S01", "start_ms": 0, "end_ms": s1_end, "keyframe_hints_ms": [0],
             "observation": "[MOCK] 单人面向镜头提问", "inference": "问题引入", "uncertainty": ""},
            {"shot_id": "S02", "start_ms": s1_end, "end_ms": s2_end, "keyframe_hints_ms": [s1_end + 500],
             "observation": "[MOCK] 手持商品展示", "inference": "卖点表达", "uncertainty": ""},
            {"shot_id": "S03", "start_ms": s2_end, "end_ms": d, "keyframe_hints_ms": [],
             "observation": "[MOCK] 面向镜头总结", "inference": "行动引导", "uncertainty": ""},
        ],
        "transcript": [],
        "uncertainties": [],
    }


def mock_quote_amount(body: dict[str, Any]) -> Decimal:
    duration_ms = int(body.get("duration_ms") or 0)
    seconds = Decimal(duration_ms) / Decimal(1000)
    return (seconds * MOCK_USD_PER_SEC).quantize(Decimal("0.0001"))


def new_mock_prediction() -> str:
    return f"{MOCK_LABEL}-pred-{uuid.uuid4().hex[:12]}"


def mock_clip_path(prediction_id: str, duration_ms: int | None = None) -> Path:
    """为 MOCK 预测生成本地测试片段（真实 FFmpeg testsrc，非云产物）。

    duration_ms 来自该单元已确认计划（request_duration_ms）；缺省回退 5s，
    避免采用区间被 Mock 素材截短（成片时长必须等于计划采用区间之和）。
    """
    from app.services.commercial.storage import commercial_storage_root

    root = commercial_storage_root() / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{prediction_id}.mp4"
    if not path.is_file() or duration_ms:
        seconds = max(1, round((duration_ms or 5_000) / 1000))
        # 带音轨（P1-7）：合成链路必须能携带/校验声音；无声 Mock 素材会掩盖
        # 裁剪丢音轨一类缺陷。testsrc=画面 + sine=正弦音轨。
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x180:rate=12",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-map", "0:v", "-map", "1:a",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            check=True, capture_output=True,
        )
    return path


async def mock_submit(body: dict[str, Any]) -> str:
    await asyncio.sleep(0)  # 模拟网络延迟位
    return new_mock_prediction()


async def mock_poll(prediction_id: str) -> dict[str, Any]:
    """MOCK 预测恒为成功；输出为本机测试片段（不走网络下载）。"""
    path = mock_clip_path(prediction_id)
    return {
        "id": prediction_id,
        "status": "succeeded",
        "output_local": str(path),
        "mock": True,
    }
