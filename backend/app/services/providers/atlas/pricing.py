"""Atlas 报价（/api/v1/model/calculate）：报价不创建任务、不二次打折。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.schemas_commercial import CostQuote

DEFAULT_QUOTE_TTL_SECONDS = 600  # 应用策略；服务商更短则以更短为准（T06 接入）


class ProviderRequestError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ProviderRequestError(200, f"报价金额无法解析：{value!r}") from exc


def parse_calculate_response(
    payload: dict[str, Any], *, request_fingerprint: str, model_id: str,
    requested_duration_ms: int, resolution_id: str,
) -> CostQuote:
    """解析 /calculate 响应为 CostQuote；错误体/缺金额一律失败。"""
    if isinstance(payload.get("error"), (dict, str)):
        message = payload["error"]
        if isinstance(message, dict):
            message = str(message.get("message") or message)
        raise ProviderRequestError(200, f"报价接口返回错误：{message}")
    amount = payload.get("amount", payload.get("total", payload.get("cost")))
    if amount is None:
        raise ProviderRequestError(200, "报价响应缺少金额字段")
    now = datetime.now(UTC)
    return CostQuote(
        quote_id=str(payload.get("quote_id") or f"q-{int(now.timestamp())}-{request_fingerprint[:12]}"),
        provider_id="atlas",
        model_id=model_id,
        request_fingerprint=request_fingerprint,
        requested_duration_ms=requested_duration_ms,
        resolution_id=resolution_id,
        currency=str(payload.get("currency") or "USD").upper(),
        estimated_amount=_decimal(amount),
        is_estimated=bool(payload.get("is_estimate", payload.get("estimated", True))),
        price_source="atlas:/api/v1/model/calculate",
        created_at=now,
        expires_at=now + timedelta(seconds=DEFAULT_QUOTE_TTL_SECONDS),
        provider_payload_redacted={
            k: v for k, v in payload.items()
            if k.lower() not in {"token", "api_key", "authorization"}
        },
    )


async def quote_generation(
    body: dict[str, Any], *, base_url: str, api_key: str,
    request_fingerprint: str, model_id: str,
    requested_duration_ms: int, resolution_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CostQuote:
    url = f"{base_url}/api/v1/model/calculate"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0), transport=transport,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            raise ProviderRequestError(resp.status_code, resp.text[:500])
        return parse_calculate_response(
            resp.json(),
            request_fingerprint=request_fingerprint,
            model_id=model_id,
            requested_duration_ms=requested_duration_ms,
            resolution_id=resolution_id,
        )
