# Blue: synthetic demo on Railway + Cloudflare

Status: deployment is not verified. The dashboard is deliberately open for this MVP.
Use a dedicated database and bucket containing synthetic data only. This setup is not
suitable for sensitive submissions. Do not connect historical or real chat data.
`main` must remain unchanged until the deployed demo passes the checklist below.

## Services and configuration

Create the resources in the owner's existing account, without changing plans or accepting
new charges automatically. Railway CLI is not installed in the current local environment;
no Railway token or R2 credentials were found. Cloud resources require owner setup.

1. In Railway create/select a project, add PostgreSQL, and create two GitHub services from
   `NivaroCodes/Blue`, branch **pre-main**, repository root `/`.
2. For `blue-api` select custom config path `/railway.api.json`. For `blue-worker` select
   `/railway.worker.json`. API runs `python run.py api`; worker runs `python run.py worker`.
   If the account uses dashboard settings instead, copy the build/start/restart settings from
   those files. API healthcheck: `/health`, timeout 60 seconds. No worker HTTP healthcheck.
3. API binds `0.0.0.0` and reads Railway's automatically supplied `PORT`.
   Do not set a self-reference `PORT=${{PORT}}`. Do not enable `RELOAD`.
4. Generate an HTTPS domain for API only. Worker needs no public domain.
5. Keep PostgreSQL private: use its service reference `DATABASE_URL` only if its hostname
   is private (`*.railway.internal`). Otherwise construct the URL from PostgreSQL's user,
   password, database and **private** host variables. Never use `DATABASE_PUBLIC_URL` or
   create a public TCP proxy for this demo.

Shared API/worker secrets and settings:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Reference to the same private Railway PostgreSQL |
| `GEMINI_API_KEY` | Owner's Google AI Studio secret |
| `GEMINI_MODEL` | Model available to that key; default in `.env.example` |
| `ENTITY_HASH_SECRET` | Same random secret in both services |
| `MEDIA_STORAGE` | `r2` |
| `R2_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | Dedicated private demo bucket |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Bucket-scoped object read/write credentials |
| `CLAIM_TIMEOUT_MINUTES`, `MAX_ATTEMPTS` | `10`, `3` |
| `WORKER_THROTTLE_SECONDS` | `4.5` (worker only; adjust to account quota) |
| `TELEGRAM_RETENTION_DAYS`, `TELEGRAM_RETENTION_SWEEP_SECONDS` | `30`, `3600` |

API only: `PRODUCTION=1`, `INLINE_ANALYSIS=0`, random `INGEST_API_TOKEN`, and
`CORS_ORIGINS=https://<frontend>.pages.dev` (exact frontend origin).
Telegram variables are described below. Keep secrets out of logs and Git.
The worker does not require the ingestion token.

## Private Cloudflare R2

In the owner's Cloudflare account:

1. Create a dedicated R2 bucket, for example `blue-demo-private`. If enabling R2 requires
   billing acceptance, the owner must handle that separately. No paid resource was created here.
2. Keep public access and `r2.dev` disabled; do not add a public custom domain.
3. Create an R2 S3 API token scoped to this bucket with object read/write access. Save the
   Access Key ID and Secret Access Key directly into Railway variables for both services.
4. Set the endpoint, bucket and `MEDIA_STORAGE=r2` identically in API and worker.
5. API writes `blue-media/<filename>` privately. Worker reads the original object via the
   authenticated S3 API. Browser requests `/api/media/<filename>` from API; no public R2
   URL, bucket credential or presigned URL is embedded in frontend data.

Changing an existing environment from local to R2 does not migrate old uploads. Seed a
fresh dedicated synthetic database after configuring storage. Railway local-storage uploads
are rejected, so isolated filesystems cannot silently masquerade as shared storage.
If an image cannot be read, the existing text-only fallback stays honest with
`image_analyzed=false`. An image-only message fails. Successful multimodal analysis is
required before `image_analyzed=true` is persisted.

The worker interval is per process and within each batch, not a global rate limiter. Use one
worker replica for this demo; higher concurrency must be budgeted against the model quota.

Local S3-emulator integration tests exercise the adapter and PostgreSQL pipeline; they
are not proof of real R2 credentials, network connectivity or deployed image analysis.

## Frontend: Cloudflare Pages

Connect the same GitHub repository, branch `pre-main`:

- Root: `frontend`; build: `npm ci && npm run build`; output: `dist`.
- Use a Node version compatible with the installed Vite (Node 22.12+).
- `VITE_API_BASE_URL=https://<api-domain>` (without `/api`).
- `VITE_DATA_MODE=api`.

The API URL now selects API mode by default. Clear an existing browser's stored
`blue.settings.v1` or select working data in Settings if it previously used demo mode.
Client-side demo fixtures remain an explicit local preview mode, not evidence of a processed seed.
Never set `VITE_INGEST_API_TOKEN`, `VITE_GEMINI_API_KEY`, or `VITE_R2_*`.
Add the resulting Pages origin to API CORS and redeploy API. Verify direct SPA detail links.

## Seed real records through ingestion

On the operator's machine set `DEMO_API_URL` to the public API and `INGEST_API_TOKEN`
to the server secret, then run:

```bash
python run.py seed-demo
```

This sends **36** messages to `/api/messages` in `Blue Demo — Synthetic Chat`, including
three generated synthetic images. All messages have a visible synthetic label, fictional
senders and stable IDs. Reruns submit the same source IDs and do not clear or duplicate data.
Existing `python run.py seed` is a legacy direct database seeder which clears records;
**do not use it on the deployed demo**. The new command never writes analysis or reviews.
Worker processes the real queue, and API statistics and dashboard read PostgreSQL records.
A rerun does not retry records already in ERROR; inspect and resolve the cause before using
an explicit operator-controlled recovery procedure. No automatic paid AI retries are hidden in seed.

Generated assets and full generation prompts: `ai_data/demo_assets/README.md`.

## Telegram: voluntary private messages only

Keep the existing connector behavior: ignore groups/channels; require an allowlisted user,
consent notice + `/agree`, and explicit `/analyze`. A community group/channel can announce
the test but is not ingested. For this open dashboard test, testers must submit synthetic
material only. `/revoke`, `/delete_my_data` and worker retention remain enabled.

Configure API secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
`TELEGRAM_HASH_SECRET`, `TELEGRAM_ALLOWED_USER_IDS` (comma-separated numeric IDs),
`TELEGRAM_WEBHOOK_URL=https://<api-domain>/webhooks/telegram`.
Empty allowlist denies submissions. Set bot description/privacy notice in BotFather.
After API `/health` succeeds, in an operator environment with those secrets:

```bash
python -m ai_data.telegram_connector set-webhook
```

Verify `getWebhookInfo` using an authenticated Bot API client without printing the token
or a token-containing URL in shared terminal history/logs. Check correct webhook URL and
absence of delivery errors. Test `/start`, `/consent`, `/agree`, `/analyze` with synthetic
text, `/revoke`, and `/delete_my_data` in a private chat. Confirm non-allowlisted requests
and group updates are rejected/ignored. No real Telegram round trip is claimed locally.

## Verification and release gate

```bash
python -m pip install -r requirements-dev.txt
git diff --check
python -m pytest ai_data/tests/test_telegram_connector.py -q
python run.py test
python -m pytest ai_data/tests -q
python test_e2e_full.py
cd frontend
npm ci
npm run build
npm test
```

Backend tests must target an isolated database with a strict test name, for example
`safenet_test`, through `TEST_DATABASE_URL`. Never point cleanup scripts at a demo or
production database. S3 tests use Moto and AI doubles; their names/docstrings identify that.
Default browser tests use routed fixtures. The separate existing live suite is explicitly
opt-in: start API on the isolated test database at port 8000, configure Gemini in that
operator environment, then run `BLUE_LIVE_E2E=1 npm test -- tests/live-real-browser.spec.ts`
(use the equivalent environment syntax in PowerShell). It cleans the test DB and uses
real Gemini; never aim it at the public demo.

For the already seeded demo, run the non-destructive browser check with
`BLUE_SYNTHETIC_E2E=1 API_PROXY_TARGET=<demo-api> npm test -- tests/synthetic-live.spec.ts`
(use PowerShell environment assignments on Windows). It requires 36 processed records and
three successfully analyzed images and checks actual browser image loading. No model
responses are mocked in this test. The default browser run skips both live suites explicitly.

After deployment, record actual evidence for each item:

- API `/health` returns 200 and verifies PostgreSQL `SELECT 1`.
- Frontend loads and uses the configured API origin; protected ingestion denies missing tokens.
- Run seed twice: exactly 36 synthetic source messages, no duplicates.
- Separate worker processes text and all three images; no ERROR/stuck PROCESSING records.
- Original uploaded image bytes can be retrieved through API after API/worker restarts;
  R2 objects stay private. Image cards have `image_analyzed=true` only after successful AI.
- Dashboard list, detail, alerts and statistics match processed database records.
- Private-chat Telegram webhook smoke, consent withdrawal and deletion succeed.
- Built frontend and logs contain no actual ingestion/Gemini/R2/Telegram secrets.

Do not declare the release ready if any item is unverified or failed. Keep `main` untouched.
Only after a successful public test prepare a reviewed transfer from `pre-main` to `main`.
Actual cloud costs depend on the owner's plans and usage; no price, spend cap or RAM
estimate is asserted here. Review billing in Railway, Cloudflare and Google before enabling.

Reference documentation: [Railway configuration](https://docs.railway.com/config-as-code),
[Railway healthchecks](https://docs.railway.com/deployments/healthchecks),
[Cloudflare R2 S3 setup](https://developers.cloudflare.com/r2/get-started/s3/).
