"""
Media helper — turns a stored image reference into base64 for the multimodal model,
and persists uploaded images so the worker can analyse them like any other message.

Supported image_url forms:
- data:image/png;base64,....                      (inline)
- http(s)://...                                   (downloaded with size/time limits)
- /api/media/<file>, media/<file> or <file>       (files saved in MEDIA_DIR)
"""
import base64
import binascii
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media")).resolve()
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class MediaError(Exception):
    pass


class MediaStorageError(MediaError):
    """The configured media store is unavailable; callers should retry."""


def _storage_mode() -> str:
    mode = os.getenv("MEDIA_STORAGE", "local").strip().lower()
    if mode not in {"local", "r2"}:
        raise MediaStorageError("MEDIA_STORAGE must be 'local' or 'r2'.")
    return mode


def _r2_client():
    endpoint = os.getenv("R2_ENDPOINT_URL", "").strip().rstrip("/")
    parsed = urlparse(endpoint)
    key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.getenv("R2_BUCKET_NAME", "").strip()
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not all((key_id, secret, bucket)):
        raise MediaStorageError("R2 media storage is not fully configured.")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}),
    ), bucket


def _media_filename(ref: str) -> str:
    name = ref.strip()
    for prefix in ("/api/media/", "api/media/", "media/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if len(name) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+\.(?:png|jpg|webp|gif)", name):
        raise MediaError("Некорректное имя файла изображения.")
    return name


def read_media(ref: str) -> Tuple[bytes, str]:
    """Read private media from the configured store, with a hard size limit."""
    if _storage_mode() == "r2":
        name = _media_filename(ref)
        client, bucket = _r2_client()
        try:
            response = client.get_object(Bucket=bucket, Key=f"media/{name}")
            body = response["Body"]
            try:
                data = body.read(MAX_IMAGE_BYTES + 1)
            finally:
                body.close()
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning("R2 media read failed (%s)", type(exc).__name__)
            raise MediaStorageError("R2 media is temporarily unavailable.") from exc
    else:
        try:
            data = resolve_local_media_path(ref).read_bytes()
        except OSError as exc:
            raise MediaStorageError("Local media is temporarily unavailable.") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError("Изображение превышает допустимый размер.")
    return data, sniff_mime(data)


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise MediaError("Неподдерживаемый формат изображения (ожидается JPEG/PNG/WEBP/GIF).")


def decode_base64_image(image_base64: str) -> Tuple[bytes, str]:
    """Accepts raw base64 or a data: URL. Returns (bytes, mime)."""
    payload = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
    try:
        data = base64.b64decode(payload.strip(), validate=False)
    except (binascii.Error, ValueError) as e:
        raise MediaError(f"Некорректный base64: {e}")
    if not data:
        raise MediaError("Пустое изображение.")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError(f"Изображение больше {MAX_IMAGE_BYTES // (1024 * 1024)} МБ.")
    return data, sniff_mime(data)


def save_image(message_pk: str, image_base64: str) -> str:
    """Save image in shared R2 storage or the local development directory."""
    data, mime = decode_base64_image(image_base64)
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}[mime]
    safe_stem = "".join(ch for ch in message_pk if ch.isalnum() or ch in ("_", "-"))[:64] or "img"
    filename = f"{safe_stem}.{ext}"
    if _storage_mode() == "r2":
        client, bucket = _r2_client()
        try:
            client.put_object(Bucket=bucket, Key=f"media/{filename}", Body=data, ContentType=mime)
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning("R2 media write failed (%s)", type(exc).__name__)
            raise MediaStorageError("R2 media is temporarily unavailable.") from exc
    else:
        try:
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            (MEDIA_DIR / filename).write_bytes(data)
        except OSError as exc:
            raise MediaStorageError("Local media is temporarily unavailable.") from exc
    return f"/api/media/{filename}"


def resolve_local_media_path(ref: str) -> Path:
    """Resolves a local media reference strictly inside MEDIA_DIR (prevents path traversal)."""
    cleaned = ref.strip()
    for prefix in ("/api/media/", "api/media/", "media/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    candidate = (Path(cleaned) if Path(cleaned).is_absolute() else (MEDIA_DIR / cleaned)).resolve()
    if MEDIA_DIR not in candidate.parents:
        raise MediaError("Локальный путь к изображению вне MEDIA_DIR запрещён.")
    if not candidate.is_file():
        raise MediaError(f"Файл изображения не найден: {candidate.name}")
    return candidate


def load_image(image_url: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Resolves image_url to (base64_string, mime). Returns None if image_url is empty.
    Raises MediaError if the image cannot be loaded.
    """
    if not image_url:
        return None

    if image_url.startswith("data:"):
        data, mime = decode_base64_image(image_url)

    elif image_url.startswith(("http://", "https://")):
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                with client.stream("GET", image_url) as resp:
                    if resp.status_code != 200:
                        raise MediaError(f"HTTP {resp.status_code} при загрузке изображения.")
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise MediaError("Изображение превышает допустимый размер.")
                        chunks.append(chunk)
            data = b"".join(chunks)
        except httpx.RequestError as e:
            raise MediaError(f"Сетевая ошибка при загрузке изображения: {e}")
        mime = sniff_mime(data)

    else:
        data, mime = read_media(image_url)

    return base64.b64encode(data).decode("ascii"), mime
