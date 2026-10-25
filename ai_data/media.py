"""
Media helper — turns a stored image reference into base64 for the multimodal model,
and persists uploaded images so the worker can analyse them like any other message.

Supported image_url forms:
- data:image/png;base64,....                      (inline)
- http(s)://...                                   (downloaded with size/time limits)
- /api/media/<file>                             (local MEDIA_DIR or private R2)
"""
import base64
import binascii
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media")).resolve()
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class MediaError(Exception):
    pass


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
    """Persists an upload in configured storage and returns '/api/media/<file>'."""
    data, mime = decode_base64_image(image_base64)
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}[mime]
    safe_stem = "".join(ch for ch in message_pk if ch.isalnum() or ch in ("_", "-"))[:64] or "img"
    filename = f"{safe_stem}.{ext}"
    if storage_backend() == "r2":
        try:
            _r2_client().put_object(Bucket=_r2_bucket(), Key=f"blue-media/{filename}", Body=data, ContentType=mime)
        except Exception:
            raise MediaError("Shared media upload failed.") from None
        return f"/api/media/{filename}"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    path = MEDIA_DIR / f"{safe_stem}.{ext}"
    path.write_bytes(data)
    return f"/api/media/{path.name}"


def storage_backend() -> str:
    backend = os.getenv("MEDIA_STORAGE", "local").lower()
    if backend not in {"local", "r2"}:
        raise MediaError("MEDIA_STORAGE must be local or r2.")
    if backend == "local" and (os.getenv("FLY_APP_NAME") or os.getenv("RAILWAY_ENVIRONMENT")):
        raise MediaError("Separate cloud API and worker require shared MEDIA_STORAGE=r2.")
    return backend


def _r2_bucket() -> str:
    bucket = os.getenv("R2_BUCKET_NAME", "").strip()
    if not bucket:
        raise MediaError("R2_BUCKET_NAME is required.")
    return bucket


def _r2_client():
    import boto3
    from botocore.config import Config
    names = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    if any(not os.getenv(name, "").strip() for name in names):
        raise MediaError("R2 endpoint and credentials are required.")
    endpoint = os.environ["R2_ENDPOINT_URL"]
    if not endpoint.startswith("https://"):
        raise MediaError("R2 endpoint must use HTTPS.")
    return boto3.client(
        "s3", endpoint_url=endpoint, region_name="auto",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15,
                      retries={"max_attempts": 2}, s3={"addressing_style": "path"}),
    )


def read_stored_image(ref: str) -> Tuple[bytes, str]:
    """Both API and worker read private objects through the same storage adapter."""
    if storage_backend() == "r2":
        filename = ref.removeprefix("/api/media/")
        if not re.fullmatch(r"[\w-]{1,64}\.(png|jpg|webp|gif)", filename):
            raise MediaError("Invalid media reference.")
        try:
            body = _r2_client().get_object(Bucket=_r2_bucket(), Key=f"blue-media/{filename}")["Body"]
            try:
                data = body.read(MAX_IMAGE_BYTES + 1)
            finally:
                body.close()
        except Exception:
            raise MediaError("Shared media read failed.") from None
    else:
        data = resolve_local_media_path(ref).read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaError("Image exceeds maximum size.")
    return data, sniff_mime(data)


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
        data, mime = read_stored_image(image_url)

    return base64.b64encode(data).decode("ascii"), mime
