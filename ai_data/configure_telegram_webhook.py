"""Register this backend's public URL as a Telegram Bot API webhook."""

import os
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv(".env.local", override=True)
load_dotenv(".env", override=False)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if not webhook_url:
        base_url = os.getenv("TELEGRAM_PUBLIC_BASE_URL", "").rstrip("/")
        webhook_url = f"{base_url}/webhooks/telegram" if base_url else ""
    parsed = urlparse(webhook_url)
    if (
        not token
        or not secret
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path.rstrip("/") != "/webhooks/telegram"
    ):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and a public HTTPS TELEGRAM_WEBHOOK_URL.")

    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": secret,
                "allowed_updates": ["message"],
            },
            timeout=20.0,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise SystemExit("Telegram rejected webhook configuration.")
    except httpx.HTTPError as exc:
        raise SystemExit(f"Telegram webhook setup failed ({type(exc).__name__}); request details hidden.") from None
    print("Telegram webhook configured.")


if __name__ == "__main__":
    main()
