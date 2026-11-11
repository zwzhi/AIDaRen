# -*- coding: utf-8 -*-
"""体验环境播种（走真实 REST；隔离 demo 库；零真实外部调用）。"""
import asyncio
import sys

import httpx

BASE = "http://127.0.0.1:8000"
MEDIA = r"D:\AI Project\AIDaRen\artifacts\demo_env\media"
EMAIL = "demo@printfilm-demo.com"
PASSWORD = "（演示口令A·本地开发库专用）"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as c:
        # 注册/登录（demo 库为空库；已注册则直接登录）
        r = await c.post("/api/auth/register", json={
            "email": EMAIL, "password": PASSWORD, "nickname": "体验管理员"})
        if r.status_code >= 400:
            print("register:", r.status_code, r.text[:120])
        r = await c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        r.raise_for_status()
        token = r.json().get("access_token") or r.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}
        print("login ok")

        async def upload(path: str, role: str, rights: str) -> int:
            with open(path, "rb") as f:
                resp = await c.post(
                    "/api/commercial/sources", headers=headers,
                    files={"file": (path.split("\\")[-1], f)},
                    data={"source_role": role, "rights_declaration": rights})
            resp.raise_for_status()
            return resp.json()["id"]

        # 演示预算（mock 池 $50）
        r = await c.post("/api/commercial/budget", headers=headers,
                         json={"total_usd": "50.00", "scope": "mock"})
        r.raise_for_status()
        print("budget:", r.json())

        # 参考视频 → 登记 → Mock 解析 → 发布模板
        vid = await upload(f"{MEDIA}\\demo-ref-30s.mp4", "reference_source_video", "演示参考视频·确认有权使用")
        r = await c.post(f"/api/commercial/sources/by-asset/{vid}", headers=headers)
        r.raise_for_status()
        source_id = r.json()["source_id"]
        r = await c.post(f"/api/commercial/sources/{source_id}/analyze", headers=headers)
        r.raise_for_status()
        run_id = r.json()["analysis_run_id"]
        r = await c.get(f"/api/commercial/analyses/{run_id}", headers=headers)
        shots = r.json()["result"]["shots"]
        print(f"analysis shots: {len(shots)}")
        r = await c.post("/api/commercial/templates", headers=headers, json={
            "name": "体验模板（30秒·三镜头）", "analysis_run_id": run_id, "shots": shots})
        r.raise_for_status()
        print("template:", r.json())

        # 两套达人 + 授权音色
        for tag in ("A", "B"):
            img = await upload(f"{MEDIA}\\demo-actor{tag}.png", "owned_actor_image", "演示达人形象图")
            voice = await upload(f"{MEDIA}\\demo-voice{tag}.mp3", "owned_voice_reference", "演示达人授权音色样本")
            r = await c.post("/api/commercial/actors", headers=headers, json={
                "name": f"演示达人{tag}", "image_asset_ids": [img],
                "appearance_desc": f"演示达人{tag}形象"})
            r.raise_for_status()
            actor_id = r.json()["actor_id"]
            r = await c.post(f"/api/commercial/actors/{actor_id}/voices", headers=headers,
                             json={"audio_asset_id": voice})
            r.raise_for_status()
            print(f"actor {tag}: id={actor_id} voice={r.json()['voice_profile_id']}")

        # 两款商品（卖点不同）
        for tag, claim, action in (
            ("A", "清凉贴敷八小时持久降温", "撕开贴片贴于手臂展示贴合"),
            ("B", "温和配方敏感肌也能安心用", "手持盒装正面旋转展示"),
        ):
            img = await upload(f"{MEDIA}\\demo-product{tag}.png", "owned_product_image", "演示商品图")
            r = await c.post("/api/commercial/products", headers=headers, json={
                "name": f"演示商品{tag}", "form": "贴片", "image_asset_ids": [img],
                "claims": [{"claim_id": f"c-{tag}", "text": claim, "approved": True,
                            "source": "演示资料"}],
                "forbidden_phrases": [], "allowed_actions": [action]})
            r.raise_for_status()
            print(f"product {tag}:", r.json())

        print("\nSEED OK")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
