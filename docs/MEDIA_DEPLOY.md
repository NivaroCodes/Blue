# Telegram/WhatsApp images: deployment checklist

The media fix is in branch `codex/r2-media-ingestion`. It uses the existing private R2 bucket for images on both the API and worker machines. The API serves images only after dashboard authentication; the browser fetches them with the signed-in user's Bearer token. Local development still uses `MEDIA_DIR` when `MEDIA_STORAGE` is unset.

## Fly deploy (app owner)

1. Merge `codex/r2-media-ingestion` into the repository's `frontend` branch. Deploy from that resulting `frontend` commit (not an older Fly image).
2. Confirm Fly has these **names** in Secrets: `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `GREEN_API_WEBHOOK_TOKEN`, `GREEN_API_ALLOWED_CHAT_ID`. Keep their values private. `MEDIA_STORAGE=r2` is also set in `fly.toml`.
3. `GREEN_API_WEBHOOK_TOKEN` on the running Fly machine was verified to match the GREEN-API instance's `webhookUrlToken` **after removing its `Bearer ` prefix**. The same raw token was restaged in Fly, so no token change is needed. Do not copy the `Bearer ` prefix into the Fly secret.
4. From the repository root, run `flyctl deploy -a blue-omnis-demo --config fly.toml --strategy rolling`. Check `flyctl status -a blue-omnis-demo`: the API and worker should be started and the API health check passing. `https://blue-omnis-demo.fly.dev/health` should return `{"status":"ok"}`.
5. In the allowed Telegram group, send a **new** photo with a caption. Confirm a new alert appears. Open it and check the image displays and the risk score appears. Telegram updates that were previously failing may be retried, but send a new photo even if they arrive.
6. In the allowed WhatsApp group, have **another group member** send a new text and then a photo with a caption. Check both appear as WhatsApp alerts. A message sent from the connected GREEN-API account itself is outgoing and is not covered by the `incomingMessageReceived` handler. If either fails, inspect Fly API logs and GREEN-API webhook delivery; do not paste tokens into an issue.

## Cloudflare Pages (site owner)

This Pages project uses Direct Upload. A GitHub merge or Fly deploy does not update the site. Build the frontend from the same merged commit as Fly and upload `frontend/dist` using the commands in `docs/DEPLOY_AUTH.md`. The build requires `VITE_DATA_MODE=api`, `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, and the public `VITE_SUPABASE_PUBLISHABLE_KEY`. After uploading, sign in and confirm the alert detail shows the image. Do not put the database password, R2 secret, or server tokens in `VITE_*` values.

## What was verified before deployment

- Existing Fly API and worker are running; Telegram text reaches the database.
- The configured R2 credentials and bucket completed a write/read/delete round trip from the Fly API machine.
- Telegram photos currently fail with `/app/media` permission denied; Telegram reports queued updates and webhook HTTP 500.
- GREEN-API instance is authorized; incoming webhooks are on, the URL points to Fly, and the allowed group exists on the account.
- GREEN-API's webhook token matches the running Fly secret when its `Bearer ` prefix is removed. The existing WhatsApp database row is from a different chat, so live WhatsApp delivery is not yet proven.
