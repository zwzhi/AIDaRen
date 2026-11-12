import httpx
import pytest

from app.services.commercial.gemini_product_research import research_product_with_gemini


@pytest.mark.asyncio
async def test_gemini_product_research_maps_json_and_usage():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={
            "model": "google/gemini-3-flash-preview",
            "choices": [{"message": {"content": '{"product":{"category":"serum"},"claims":[],"states":[],"capabilities":[],"sources":[]}'}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        })

    result = await research_product_with_gemini(
        page_url="https://example.test/product",
        page_text="official product page",
        image_urls=["https://cdn.example.test/product.png"],
        api_key="k",
        transport=httpx.MockTransport(handler),
    )
    assert result.payload["product"]["category"] == "serum"
    assert result.input_tokens == 1000
    assert result.output_tokens == 200
    assert result.estimated_amount_usd == 0.0011
