"""Whitelist submitted reference media and enrich identities within one workspace."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlsplit

from sqlalchemy import String, cast, or_, select

from app.models_drama import DramaAsset, DramaProject

_MAX_REFERENCES = 80
_DEFAULT_ROLES = {"image": "reference_image", "video": "reference_video", "audio": "reference_audio"}
_MEDIA_TYPES = {"image_url": "image", "input_image": "image", "video_url": "video", "audio_url": "audio"}
_SECRET_QUERY_KEYS = frozenset({
    "authorization", "auth", "apikey", "key", "token", "accesstoken", "refreshtoken",
    "securitytoken", "password", "passwd", "secret", "clientsecret", "credential",
    "credentials", "signature", "sign", "sig", "authkey", "ossaccesskeyid", "awsaccesskeyid",
    "googleaccessid", "keypairid", "accesskey", "accesskeyid", "secretaccesskey", "jwt", "policy",
})
_TAIL_MARKERS = (
    ("画风参考图（只借色调、笔触、光影，禁止抄主体与构图）：", "画风参考图"),
    ("构图与主体参考：", None),
)


def _positive_id(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _public_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 8192:
        return None
    decoded = value
    for _ in range(2):
        decoded = unquote(decoded)
    if (any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
            or any(ord(character) < 32 or ord(character) == 127 for character in decoded)
            or any(character in decoded for character in ('\\', '<', '>', '"', '…'))
            or any(marker in decoded.casefold() for marker in ("[redacted]", "[invalid url]", "[truncated", "[data:"))):
        return None
    try:
        parts = urlsplit(value)
        if parts.fragment or parts.username or parts.password:
            return None
        if parts.scheme:
            if parts.scheme not in {"http", "https"} or not parts.hostname or "%" in parts.netloc:
                return None
            _ = parts.port
        elif parts.netloc or not parts.path.startswith(("/static/", "/media/", "/uploads/")):
            return None
        if ".." in unquote(unquote(parts.path)).split("/"):
            return None
        for key, _ in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=80):
            normalized = re.sub(r"[^a-z0-9]", "", unquote(unquote(key)).casefold())
            if (normalized in _SECRET_QUERY_KEYS or normalized.startswith(("xamz", "xgoog"))
                    or normalized.endswith(("apikey", "token", "signature", "credential", "secret", "password", "authorization"))):
                return None
    except (ValueError, UnicodeError):
        return None
    return value


def _public_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > 200 or any(ord(character) < 32 for character in value)
            or "[redacted]" in value.casefold()
            or re.search(r"\bBearer\s|\bsk-[A-Za-z0-9_-]{12,}", value, re.I)):
        return None
    return value


def _role(kind: str, value) -> str:
    if kind == "image" and isinstance(value, str) and value in {"reference_image", "first_frame", "last_frame"}:
        return value
    return _DEFAULT_ROLES[kind]


def _media_value(value):
    if isinstance(value, dict):
        return value.get("url")
    return value


def _tail_references(text) -> list[dict]:
    """Read only complete URL-only suffixes emitted by the image request builder."""
    if not isinstance(text, str) or len(text) > 32000:
        return []
    groups = []
    remainder = text.rstrip()
    for _ in range(len(_TAIL_MARKERS)):
        candidates = [(remainder.rfind(marker), marker, name) for marker, name in _TAIL_MARKERS]
        index, marker, name = max(candidates, key=lambda item: item[0])
        if index < 0 or (index > 0 and remainder[index - 1] != "。"):
            break
        values = remainder[index + len(marker):].split()
        if not values or len(values) > _MAX_REFERENCES or not all(_public_url(value) for value in values):
            break
        groups.append([{"kind": "image", "url": value, **({"name": name} if name else {})} for value in values])
        remainder = remainder[:index].removesuffix("。").rstrip()
    return [reference for group in reversed(groups) for reference in group]


def public_references(data) -> list[dict]:
    """Copy known reference fields; never traverse arbitrary requests or responses."""
    references: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    content_image_urls: set[str] = set()
    content_media: set[tuple[str, str]] = set()
    prepared_media: set[tuple[str, str]] = set()

    def add(kind, value, *, role=None, metadata=None, content=False, fallback=False):
        if not isinstance(kind, str) or kind not in _DEFAULT_ROLES or len(references) >= _MAX_REFERENCES:
            return
        url = _public_url(_media_value(value))
        if not url:
            return
        if fallback and (kind, url) in content_media | prepared_media:
            return
        resolved_role = _role(kind, role)
        identity = (kind, url, resolved_role)
        if content and kind == "image":
            content_image_urls.add(url)
        if content:
            content_media.add((kind, url))
        if identity in seen:
            return
        seen.add(identity)
        reference = {"kind": kind, "url": url, "role": resolved_role}
        metadata = metadata if isinstance(metadata, dict) else {}
        if (name := _public_name(metadata.get("name"))) is not None:
            reference["name"] = name
        if (asset_id := _positive_id(metadata.get("asset_id"))) is not None:
            reference["asset_id"] = asset_id
        cover = url if kind == "image" else _public_url(metadata.get("cover"))
        if cover:
            reference["cover"] = cover
        references.append(reference)

    def saved(items):
        if not isinstance(items, list):
            return
        for item in items[:_MAX_REFERENCES]:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            media_type = item.get("type")
            if isinstance(kind, str) and kind in _DEFAULT_ROLES:
                add(kind, item.get("url"), role=item.get("role"), metadata=item)
            elif isinstance(media_type, str) and media_type in _MEDIA_TYPES:
                kind = _MEDIA_TYPES[media_type]
                field = "image_url" if media_type == "input_image" else media_type
                add(kind, item.get(field), role=item.get("role"), content=True)

    if isinstance(data, list):
        saved(data)
        return references
    if not isinstance(data, dict):
        return []
    body = data.get("seedance_body")
    if isinstance(body, dict):
        # Only this named preparation field is a request body; do not recurse into traces.
        body = {key: value for key, value in body.items() if key != "seedance_body"}
        for reference in public_references(body):
            add(reference["kind"], reference["url"], role=reference["role"], metadata=reference)
            prepared_media.add((reference["kind"], reference["url"]))
    if isinstance(data.get("kind"), str) and data["kind"] in _DEFAULT_ROLES:
        saved([data])
    saved(data.get("references"))
    saved(data.get("content"))
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        saved(metadata.get("content"))
    if isinstance(data.get("input"), list):
        for message in data["input"][:_MAX_REFERENCES]:
            if isinstance(message, dict):
                saved(message.get("content"))
    for field, kind in (("reference_images", "image"), ("reference_videos", "video"),
                        ("reference_audios", "audio"), ("reference_image_urls", "image"),
                        ("reference_audio_urls", "audio"), ("ref_urls", "image"), ("style_ref_urls", "image")):
        values = data.get(field)
        if not isinstance(values, list):
            continue
        for item in values[:_MAX_REFERENCES]:
            info = item if isinstance(item, dict) else {}
            if field == "style_ref_urls":
                info = {"name": "画风参考图", **info}
            add(kind, item, role=info.get("role"), metadata=info, fallback=True)
    add("image", data.get("image_url"),
        metadata=data.get("image_url") if isinstance(data.get("image_url"), dict) else None, fallback=True)
    for field in ("first_frame", "last_frame"):
        add("image", data.get(field), role=field,
            metadata=data.get(field) if isinstance(data.get(field), dict) else None)
    image = _public_url(_media_value(data.get("image")))
    if image and image not in content_image_urls and ("image", image) not in prepared_media:
        add("image", image, role="first_frame")
    for field in ("input", "prompt"):
        saved(_tail_references(data.get(field)))
    return references


def _asset_urls(asset) -> set[str]:
    urls = {url for value in (asset.url, asset.cover) if (url := _public_url(value))}
    params = asset.params if isinstance(asset.params, dict) else {}
    canvas = params.get("canvas") if isinstance(params.get("canvas"), dict) else {}
    for binding in (params.get("voiceAudio"), canvas.get("voiceAudio")):
        if isinstance(binding, dict):
            urls.update(url for field in ("url", "previewUrl") if (url := _public_url(binding.get(field))))
        elif url := _public_url(binding):
            urls.add(url)
    versions = params.get("image_versions")
    if isinstance(versions, list):
        for version in versions[:_MAX_REFERENCES]:
            if isinstance(version, dict):
                urls.update(url for field in ("url", "cover") if (url := _public_url(version.get(field))))
    return urls


async def enrich_references(db, refs, *, user_id: int, team_id: int | None,
                            project_id: int | None = None) -> list[dict]:
    """Enrich an already authorized task's workspace, retaining its historical URLs."""
    originals = public_references(refs)
    references = [dict(reference) for reference in originals]
    for reference in references:
        reference.pop("name", None)
        reference.pop("asset_id", None)
    if (not references or not _positive_id(user_id)
            or (team_id is not None and not _positive_id(team_id))
            or (project_id is not None and not _positive_id(project_id))):
        return references
    asset_ids = {reference["asset_id"] for reference in originals if "asset_id" in reference}
    urls = {reference["url"] for reference in references}
    scope = [DramaProject.team_id == team_id] if team_id is not None else [
        DramaProject.user_id == user_id, DramaProject.team_id.is_(None),
    ]
    if project_id is not None:
        scope.append(DramaProject.id == project_id)
    candidates = [DramaAsset.url.in_(urls), DramaAsset.cover.in_(urls)]
    if asset_ids:
        candidates.append(DramaAsset.id.in_(asset_ids))
    candidates.extend(cast(DramaAsset.params, String).contains(url, autoescape=True) for url in urls)
    assets = list((await db.execute(select(DramaAsset).join(
        DramaProject, DramaProject.id == DramaAsset.project_id,
    ).where(*scope, or_(*candidates)))).scalars().all())
    assets_by_id = {asset.id: asset for asset in assets}
    assets_by_url: dict[str, list] = {}
    for asset in assets:
        for url in _asset_urls(asset) & urls:
            assets_by_url.setdefault(url, []).append(asset)
    authorized: list[dict] = []
    for reference, original in zip(references, originals):
        asset = assets_by_id.get(original.get("asset_id"))
        explicit_asset = asset is not None
        if asset is None:
            matches = assets_by_url.get(reference["url"], [])
            asset = matches[0] if len(matches) == 1 else None
        if asset is None:
            # 历史请求里的原始 URL 不是访问授权。只有能映射到当前用户/团队
            # 可读的媒体资产时，才返回受控资产标识和预览地址。
            continue
        reference["asset_id"] = asset.id
        name = (_public_name(original.get("name")) if explicit_asset else None) or _public_name(asset.name)
        if name:
            reference["name"] = name
        authorized.append(reference)
    return authorized
