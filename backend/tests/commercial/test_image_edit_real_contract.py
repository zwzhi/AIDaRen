import httpx
import pytest
import json

from app.services.providers.atlas.image_edit import generate_image_edit_real


@pytest.mark.asyncio
async def test_real_image_edit_uses_images_contract_and_maps_async_task():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"data": {"id": "img-task-1", "status": "processing"}})

    result = await generate_image_edit_real(
        images=["https://cdn.example.test/actor.jpg"],
        prompt="preserve identity",
        api_key="k",
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "processing"
    assert result.prediction_id == "img-task-1"
    assert captured["images"] == ["https://cdn.example.test/actor.jpg"]
    assert captured["quality"] == "low"
    assert captured["complexity"] == "low"

