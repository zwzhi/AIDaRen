"""Atlas 服务商媒体安全：受控下载与 SSRF 防护（任务书 §12 网络安全）。

- 只接受 HTTPS 公网地址；
- 域名解析结果中的私网/回环/链路本地/云元数据地址全部拒绝；
- 重定向手动逐跳校验，禁止跟随到内网目标（防 DNS rebinding 的第一道防线）。
"""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

_MAX_REDIRECTS = 5
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "instance-data"}


class SsrfBlockedError(Exception):
    """目标地址违反外网下载策略。"""


def _is_blocked_ip(ip_text: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return not addr.is_global


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SsrfBlockedError("仅允许 HTTPS 下载地址")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SsrfBlockedError("下载地址缺少主机名")
    if host in _BLOCKED_HOSTNAMES:
        raise SsrfBlockedError(f"下载地址主机被禁止：{host}")
    # 字面量 IP 直接判断；域名走 DNS 解析后再判断全部结果
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(host):
            raise SsrfBlockedError(f"下载地址指向内网/保留地址：{host}")
        return
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SsrfBlockedError(f"下载地址域名无法解析：{host}") from exc
    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise SsrfBlockedError(f"下载地址解析到内网/保留地址：{host} -> {ip}")


def assert_public_https_url(url: str) -> None:
    """校验单个 URL；不通过抛 SsrfBlockedError。"""
    _validate_url(url)


async def fetch_url_to_file(
    url: str, dest: Path, *, transport: httpx.AsyncBaseTransport | None = None
) -> Path:
    """受控下载：逐跳校验重定向，内容写目标文件。

    transport 参数供测试注入 MockTransport；生产为 None（真实网络）。
    """
    current = url
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=False, transport=transport
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            _validate_url(current)
            resp = await client.get(current)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    raise SsrfBlockedError("重定向缺少 Location")
                current = str(httpx.URL(current).join(location))
                continue
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return dest
    raise SsrfBlockedError("重定向次数超限")


# ---------------------------------------------------------------- 素材上传（§8.6）

class UploadFailedError(Exception):
    """服务商素材上传失败。"""


async def upload_media(
    raw: bytes, mime: str, *, base_url: str, api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """上传素材到 Atlas（DRAFT 契约：/api/v1/model/uploadMedia）。

    返回 {"handle", "url", "expires_at"(可选)}；错误状态/错误体一律失败，
    绝不把本机路径或内部地址当作外部可读素材地址。
    """
    url = f"{base_url}/api/v1/model/uploadMedia"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=15.0), transport=transport,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        files = {"file": (f"asset.{mime.split('/')[-1]}", raw, mime)}
        resp = await client.post(url, files=files)
        if resp.status_code >= 400:
            raise UploadFailedError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        upstream_url = str(
            data.get("download_url") or data.get("url") or data.get("public_url") or ""
        ).strip()
        handle = str(data.get("id") or data.get("handle") or data.get("filename") or upstream_url).strip()
        if not handle and not upstream_url:
            raise UploadFailedError("上传响应缺少素材句柄或下载地址")
        return {
            "handle": handle,
            "url": upstream_url,
            "expires_at": data.get("expires_at"),
        }


def handle_expired(handle_row, now=None) -> bool:
    """句柄是否过期（无 expires_at 视为长期有效，待联调核实保留期）。"""
    from datetime import UTC, datetime as _dt

    expires = handle_row.expires_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= (now or _dt.now(UTC))
