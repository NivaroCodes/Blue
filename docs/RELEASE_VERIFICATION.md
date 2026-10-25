# Local release verification — 2026-10-25

Branch: `pre-main`. Starting HEAD: `e295849def91f0eaa93434064df66fcd7634ed10`.
The original working copy at `C:/Users/nivar/Documents/Projects/Blue` was found with
uncommitted Railway, Telegram allowlist and analyst-authentication changes. A binary
tracked patch plus untracked source files was archived outside the repository before edits.
No reset, force push, main change, cloud billing change or secret publication was performed.

## Scope

Preserved the Railway preparation, health/ingestion protection, Telegram allowlist,
retention and consent behavior. Retired the uncommitted analyst-login/JWT feature as
requested; its feature-specific checks were replaced with public synthetic-demo access
contract tests. Existing pipeline, review, security and failure assertions were retained.
Added idempotent API-based seed, synthetic PNG fixtures, private R2 storage adapter,
image/OCR display, separate service configs and deployment instructions.

## Results

| Check | Actual result |
| --- | --- |
| `git diff --check` | Passed |
| `python -m pytest ai_data/tests/test_telegram_connector.py -q` | 15 passed |
| `python run.py test` | 108 passed (unittest; excludes pytest-style Telegram functions) |
| `python -m pytest ai_data/tests -q` | 123 passed |
| `python test_e2e_full.py` | All 8 PostgreSQL API/worker/review steps passed, AI response mocked |
| `npm ci` | Passed; 149 packages audited, zero reported vulnerabilities |
| `npm run build` | Passed; existing bundle-size and dependency annotation warnings |
| `npm test` | 42 passed, 6 skipped; both live suites then passed separately |
| `BLUE_LIVE_E2E=1 npm test -- tests/live-real-browser.spec.ts` | 5 passed, actual local API/PostgreSQL/Gemini |
| `BLUE_SYNTHETIC_E2E=1 npm test -- tests/synthetic-live.spec.ts` | 1 passed; actual processed records and browser image loading |
| S3 adapter with separate API/worker directories | Passed with Moto S3 emulator + model double; original bytes verified |
| Configured secret values in source and built frontend | No matches; diagnostic logs sanitized |

Previous Playwright error artifacts reported navigation to `/` without a base URL. Tests
were run from `frontend` using its actual Playwright config and base URL; existing
assertions passed. Original `.pytest_cache` recorded no outstanding failures.

## Actual synthetic processing

Created the isolated local PostgreSQL database `blue_release_test` without clearing the
existing user databases. Started API in a separate process on loopback port 8010 and
submitted `python run.py seed-demo` twice over HTTP: exactly 36 rows, stable unique IDs.
Worker ran separately and called real `gemini-3.5-flash-lite`; no verdicts were prefilled.

Final actual statistics:

- Total: 36; PENDING: 0; PROCESSING: 0; ERROR: 0.
- HIGH: 8; MEDIUM: 2; LOW: 26. These are observed model outcomes, not seed constants.
- Three original PNG images analyzed successfully, `image_analyzed=true`.
- The fictional poster had actual OCR and six image-sourced reasons; dashboard displayed
  the original image, OCR and its persisted risk score of 95.
- API `/health`: HTTP 200, backed by PostgreSQL `SELECT 1`.
- A model free-tier request-frequency limit produced transient 429 responses; existing
  retries recovered successfully. Worker interval is now configurable with
  `WORKER_THROTTLE_SECONDS` (default 4.5). This is not a distributed rate limiter.

Generated assets: `ai_data/demo_assets/`; exact prompts and provenance are recorded in
that directory's README. Built-in image generation was used. A browser screenshot and
raw diagnostic logs remain outside Git in the Codex working folder.

## Unverified cloud gates

**No public deployment was performed or claimed.** Railway CLI is absent and Railway/R2
credentials were not configured. No frontend/API public URL is confirmed. Real R2 network
access and credentials, cross-container image analysis on Railway, deployed CORS, public
bundle/log review and a live private-chat Telegram webhook round trip remain unverified.
Local images used local storage; S3 transport used an emulator. These checks do not
substitute for real R2 end-to-end verification.

Use `DEPLOY_RAILWAY.md` for the exact account/service/secret setup and post-deployment
checklist. Keep the dashboard synthetic-only and PostgreSQL private. The demo is not
release-ready for public use until all cloud gates pass. No transfer to `main` is prepared
before that gate. Charges for the existing AI account are not independently measurable
from this run; no tariff changes or additional-payment confirmations were made.
