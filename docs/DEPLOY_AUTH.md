# Blue: опубликованный вход аналитика

После консолидации 26 октября 2026 единственный источник для следующих публикаций — `pre-main`. Исторические ветки и коммиты не разворачивайте отдельно.

## Текущая схема

- API и worker: Fly app `blue-omnis-demo`, [health](https://blue-omnis-demo.fly.dev/health).
- PostgreSQL и Auth: отдельный проект Supabase `Blue Omnis Synthetic Demo` на Free.
- Frontend: [blue-omnis-demo.pages.dev](https://blue-omnis-demo.pages.dev), Cloudflare Pages **Direct Upload** без Git Provider. Новые сборки делайте из `pre-main`; push сам по себе frontend не пересобирает.

## Секреты и сборка

Fly получает через `flyctl secrets import -a blue-omnis-demo` или `flyctl secrets set` серверные `DATABASE_URL`, `INGEST_API_TOKEN`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `CORS_ORIGINS` и прочие секреты pipeline. `CORS_ORIGINS=https://blue-omnis-demo.pages.dev`. Ключи и пароль базы никогда не коммитить.

Для сборки frontend из корня репозитория:

```powershell
git switch pre-main
git pull --ff-only origin pre-main
Set-Location frontend
$env:VITE_DATA_MODE = 'api'
$env:VITE_API_BASE_URL = 'https://blue-omnis-demo.fly.dev'
$env:VITE_SUPABASE_URL = 'https://<project-ref>.supabase.co'
$env:VITE_SUPABASE_PUBLISHABLE_KEY = '<Supabase publishable key>'
npm ci
npm run build
npx wrangler pages deploy dist --project-name blue-omnis-demo --branch pre-main --commit-hash (git rev-parse HEAD)
```

Значения Supabase берутся в настройках **того же проекта**, что используется Fly. Для Direct Upload переменные нужны процессу `npm run build`: запись в Pages Production variables не меняет уже собранный JS. В `VITE_*` допустим только publishable key; `SUPABASE_SECRET_KEY`, service role и пароль PostgreSQL туда не помещать.

## Контроль

1. В Supabase **Authentication → Users** должен быть подтверждённый пользователь аналитика. Участник организации Supabase не становится пользователем Auth автоматически. Самостоятельная регистрация в проекте отключена.
2. `flyctl deploy --config fly.toml -a blue-omnis-demo --strategy rolling` запускайте из корня. Затем `flyctl status -a blue-omnis-demo`: API и worker должны быть `started`, health check API — `passing`.
3. `/health` должен вернуть `{"status":"ok"}`. `/api/alerts` и `/api/messages` без Bearer должны вернуть `401`; запрос Pages origin на `/api/alerts` должен пройти CORS preflight.
4. В браузере откройте Pages URL, войдите существующим пользователем Auth и проверьте, что лента и статистика загружаются. Вход через опубликованную страницу проверен временным синтетическим пользователем; учётная запись после теста удалена.
5. После ручной публикации frontend проверьте `npx wrangler pages deployment list --project-name blue-omnis-demo` и публичный Pages URL. В Direct Upload нет автоматического перехода на новый Git-коммит.

Не отключайте Bearer-проверку для демонстрации. Для живых данных отдельно проверяйте разрешение пользователя и согласие на ingestion. Расходы Fly, Supabase и Cloudflare отслеживайте в кабинетах владельцев аккаунтов.
