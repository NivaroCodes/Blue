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
    """Saves an uploaded image to MEDIA_DIR and returns an API-servable reference '/api/media/<file>'."""
    data, mime = decode_base64_image(image_base64)
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}[mime]
    safe_stem = "".join(ch for ch in message_pk if ch.isalnum() or ch in ("_", "-"))[:64] or "img"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    path = MEDIA_DIR / f"{safe_stem}.{ext}"
    path.write_bytes(data)
    return f"/api/media/{path.name}"


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
        path = resolve_local_media_path(image_url)
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES:
            raise MediaError("Изображение превышает допустимый размер.")
        mime = sniff_mime(data)

    return base64.b64encode(data).decode("ascii"), mime
