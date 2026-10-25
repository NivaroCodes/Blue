"""Point a GREEN-API instance at the deployed Blue webhook endpoint."""

import os
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv(".env.local", override=True)
load_dotenv(".env", override=False)


def main() -> None:
    api_url = os.getenv("GREEN_API_API_URL", "").rstrip("/")
    instance_id = os.getenv("GREEN_API_ID_INSTANCE", "")
    instance_token = os.getenv("GREEN_API_TOKEN_INSTANCE", "")
    webhook_token = os.getenv("GREEN_API_WEBHOOK_TOKEN", "")
    public_url = os.getenv("TELEGRAM_PUBLIC_BASE_URL", "").rstrip("/")
    telegram_webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if not public_url and telegram_webhook_url.endswith("/webhooks/telegram"):
        public_url = telegram_webhook_url[: -len("/webhooks/telegram")].rstrip("/")
    if not all((api_url, instance_id, instance_token, webhook_token, public_url)):
        raise SystemExit(
            "Set GREEN_API_API_URL, GREEN_API_ID_INSTANCE, GREEN_API_TOKEN_INSTANCE, "
            "GREEN_API_WEBHOOK_TOKEN and TELEGRAM_PUBLIC_BASE_URL (or TELEGRAM_WEBHOOK_URL)."
        )

    parsed = urlparse(api_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ("green-api.com", "greenapi.com")
    ):
        raise SystemExit("GREEN_API_API_URL must be an official GREEN-API HTTPS endpoint.")
    if not instance_id.isdigit():
        raise SystemExit("GREEN_API_ID_INSTANCE must contain digits only.")

    endpoint = f"{api_url}/waInstance{instance_id}/setSettings/{instance_token}"
    payload = {
        "webhookUrl": f"{public_url}/webhooks/green-api",
        "webhookUrlToken": f"Bearer {webhook_token}",
        "incomingWebhook": "yes",
    }
    try:
        response = httpx.post(endpoint, json=payload, timeout=20.0)
        response.raise_for_status()
        result = response.json()
        if not result.get("saveSettings"):
            raise SystemExit("GREEN-API did not confirm the webhook settings.")
    except httpx.HTTPError as exc:
        raise SystemExit(f"GREEN-API webhook setup failed ({type(exc).__name__}); request details hidden.") from None
    print("GREEN-API webhook configured. Instance restart/settings propagation may take up to 5 minutes.")


if __name__ == "__main__":
    main()
