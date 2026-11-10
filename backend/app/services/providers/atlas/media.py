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
