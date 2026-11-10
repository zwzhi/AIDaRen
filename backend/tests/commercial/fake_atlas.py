# -*- coding: utf-8 -*-
"""本地 Fake Atlas HTTP 服务（离线测试专用）。

用真实 uvicorn 监听 127.0.0.1 随机端口，替代外部 Atlas 接口：
calculate / generateVideo / prediction/{id} / uploadMedia / 成片下载。
所有外部 HTTP 都落在本机回环，零真实付费调用。
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def make_test_clip(path: Path, seconds: float = 2.0, with_audio: bool = True) -> Path:
    """生成带音轨的本地测试片段（testsrc + 正弦音；ffmpeg 参数数组执行）。"""
    import subprocess

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    cmd += ["-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x180:rate=12"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def build_fake_atlas_app(*, clip_path: Path | None = None) -> FastAPI:
    """构造 Fake Atlas 应用；状态存 app.state，测试线程可直接读写。"""
    app = FastAPI()
    app.state.requests: list[tuple[str, dict]] = []
    app.state.next_prediction_id = [1000]
    app.state.predictions: dict[str, dict] = {}
    # 每个预测的状态序列：测试可覆写；默认 processing → completed(带输出与费用)
    app.state.prediction_script: dict[str, list[dict]] = {}
    app.state.quote_response = {"amount": 0.135, "currency": "USD", "quote_id": "fq-1"}
    app.state.generate_response: dict | None = None  # None=正常返回 id
    app.state.prediction_status = 200  # 非 200 时模拟上游限流等错误状态
    app.state.files: dict[str, bytes] = {}

    @app.post("/api/v1/model/calculate")
    async def calculate(request: Request):
        app.state.requests.append(("calculate", await request.json()))
        body = dict(app.state.quote_response)
        # 报价号必须每次唯一（落库有唯一约束；固定值会在重跑时撞键）
        body["quote_id"] = f"fq-{app.state.next_prediction_id[0]}"
        app.state.next_prediction_id[0] += 1
        return JSONResponse(body)

    @app.post("/api/v1/model/generateVideo")
    async def generate_video(request: Request):
        app.state.requests.append(("generateVideo", await request.json()))
        if app.state.generate_response is not None:
            return JSONResponse(app.state.generate_response)
        pid = f"pred-{app.state.next_prediction_id[0]}"
        app.state.next_prediction_id[0] += 1
        return JSONResponse({"data": {"id": pid}})

    @app.post("/api/v1/model/uploadMedia")
    async def upload_media(request: Request):
        app.state.requests.append(("uploadMedia", {"bytes": len(await request.body())}))
        return JSONResponse({"id": f"media-{app.state.next_prediction_id[0]}",
                             "url": "", "expires_at": None})

    @app.get("/api/v1/model/prediction/{prediction_id}")
    async def prediction(prediction_id: str):
        app.state.requests.append(("prediction", {"id": prediction_id}))
        if app.state.prediction_status != 200:
            return JSONResponse({"error": {"message": "rate limited"}},
                                status_code=app.state.prediction_status)
        script = app.state.prediction_script.get(prediction_id)
        if script:
            body = script.pop(0)
        else:
            body = app.state.predictions.get(prediction_id) or {"status": "processing"}
        app.state.predictions[prediction_id] = body
        return JSONResponse({"data": {"id": prediction_id, **body}})

    @app.get("/files/{name}")
    async def files(name: str):
        data = app.state.files.get(name)
        if data is None and clip_path is not None and name == clip_path.name \
                and clip_path.is_file():
            data = clip_path.read_bytes()
        if data is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return Response(content=data, media_type="video/mp4")

    return app


@pytest.fixture
async def fake_atlas(tmp_path):
    """启动本地 Fake Atlas（随机端口），yield (app, base_url)。"""
    clip = make_test_clip(tmp_path / "fake-output.mp4", seconds=2.0, with_audio=True)
    app = build_fake_atlas_app(clip_path=clip)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.02)
    if not server.started:  # pragma: no cover - 启动失败兜底
        raise RuntimeError("Fake Atlas 未能在 10s 内启动")
    port = server.servers[0].sockets[0].getsockname()[1]
    app.state.base_url = f"http://127.0.0.1:{port}"
    try:
        yield app
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def complete_prediction_body(name: str = "fake-output.mp4",
                             *, amount: float | None = 0.14) -> dict:
    """构造一次“已完成”的 prediction 响应体（含输出 URL 与可核实费用）。

    输出地址使用 https 形态（与真实上游一致；适配器只接受 https）。
    测试注入的下载垫片会把该地址映射回本地 Fake Atlas。
    """
    body: dict = {"status": "completed", "outputs": [f"https://fake-atlas.invalid/files/{name}"]}
    if amount is not None:
        body["cost"] = {"amount": amount, "currency": "USD"}
    return body
