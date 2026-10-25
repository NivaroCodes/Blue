# Railway deployment retired

The active target is Fly.io + Supabase + Cloudflare Pages/R2.
See [DEPLOY_FLY.md](DEPLOY_FLY.md). Railway configs and Procfile were removed.
The historical local verification of commit `48c3fae` remains in
[RELEASE_VERIFICATION.md](RELEASE_VERIFICATION.md); it does not verify Fly deployment.
No existing Railway service or database has been deleted or changed. The owner should
stop old services only after validating the replacement and reviewing any billing.
