# Blue: Fly.io + Supabase + Cloudflare Pages/R2

Конфигурация подготовлена для синтетического демо, **облачный запуск не проверен**.
Dashboard открыт: использовать только вымышленные сообщения и изображения.
Рабочая ветка — `pre-main`; до успешной облачной проверки `main` не менять.

## 1. Граница доступа и решение владельца

Здесь не создавались облачные ресурсы, не использовались сохранённые облачные credentials,
не проверялась авторизация аккаунта, не подтверждались платежи. `flyctl` локально установлен;
проверялись только версия и справка. Все следующие облачные команды выполняет владелец
после проверки организации, сетевой модели и стоимости.

**Supabase Free не обеспечивает приватное соединение внутри сети Fly.** Direct и Supavisor
используют доступные по сети endpoints с аутентификацией PostgreSQL. TLS и пароль не
превращают такое соединение в private networking. Если «непубличная база» означает отсутствие
интернет endpoint вообще, **не создавайте проект и не запускайте деплой по этой инструкции**:
нужно отдельное решение владельца о совместимой приватной архитектуре. Бесплатная схема
Supabase не объявляется соответствующей этому требованию.

Если владелец разрешит защищённое внешнее соединение, сначала проверьте доступность
[Network Restrictions](https://supabase.com/docs/guides/platform/network-restrictions)
в своём плане и возможность ограничить соединения адресами приложения. IP входящего
Fly Proxy не является исходящим IP Machines; обычный egress может меняться. Закреплённый
egress и ограничения нужно согласовать отдельно, включая временную release Machine.
Не открывайте `0.0.0.0/0` или `::/0` ради устранения ошибки соединения. Если ограничения
недоступны или не соответствуют требованию владельца — остановитесь до создания БД.

## 2. Что запускается

Один Fly app, две [process groups](https://fly.io/docs/launch/processes/):

| Компонент | Команда | Доступ |
| --- | --- | --- |
| `api` | `python run.py api` | HTTPS через Fly Proxy, внутренний порт 8000 |
| `worker` | `python run.py worker` | Отдельная постоянно работающая Machine, без HTTP-сервиса |
| Release task | `python run.py init-db` | Подготовка схемы перед стартом обеих групп; без seed/очистки |

Обе группы используют один Docker image и app-level secrets: одна БД и один R2 bucket.
Это исключает расхождение secrets между двумя Fly apps. API и worker не разделяют диск.
`fly.toml` отключает autostop API; worker без service не зависит от HTTP-трафика.
Restart policy — `always`. Заданы 512 MiB и один shared CPU на каждую Machine.
SIGTERM и 240 секунд дают worker время закончить текущую пачку; при принудительном
завершении остаётся существующее восстановление просроченных claims.

`Dockerfile` работает из `/app`, запускает Python 3.12 непривилегированным пользователем.
Build context — **корень репозитория**, не `frontend` и не `ai_data`.
`.dockerignore` исключает `.env*`, Git, локальные media, тесты, логи и frontend.
Secrets не передаются через build args. Reload в production отключён кодом и конфигурацией.
Описание параметров: [Fly app configuration](https://fly.io/docs/reference/configuration/).

## 3. Supabase PostgreSQL: совместимость и лимиты

Только после решения из раздела 1 владелец может выбрать/создать отдельный Free-проект
для синтетического демо, желательно рядом с регионом Fly (`fra` — шаблон, проверить выбор).
Не переносите настоящие чаты и не используйте существующую рабочую БД.

Blue использует SQLAlchemy + psycopg2, обычные транзакции PostgreSQL, уникальные индексы,
FK и `FOR UPDATE SKIP LOCKED`. Эти возможности подходят PostgreSQL; фактическая работа
на Supabase требует облачной проверки. Приложению нужны права создания/изменения своей
схемы для release task и текущего startup `init_db`; роль только для чтения не подходит.

В Dashboard → Connect скопируйте точную строку:

- Direct `db.<ref>.supabase.co:5432`: предпочтительно для постоянных backend; на Free
  обычно IPv6. Сначала проверить DNS/IPv6 из Fly, не покупать IPv4 add-on автоматически.
- Session pooler `<pooler-host>:5432`: вариант для IPv4. Имя пользователя обычно
  `postgres.<ref>`; берите его из Connect, не собирайте hostname по памяти.
- Transaction pooler `:6543` здесь **не выбран**: смена семантики сессий не тестировалась.

См. [официальные варианты подключения](https://supabase.com/docs/guides/database/connecting-to-postgres).
Используется пароль БД, **не** Supabase anon/publishable/service-role API key.
Percent-encode специальные символы пароля. Добавьте `sslmode=require&connect_timeout=10`
к query DSN (`?` или `&` по существующей строке). `require` шифрует канал, но сам по себе
не обещает полную проверку hostname/CA; для `verify-full` настройте доверенный CA по
документации проекта и проверьте цепочку сертификата. Не отключайте TLS.

Fly задаёт `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=0`, `DB_POOL_TIMEOUT=10`,
`DB_POOL_RECYCLE=300`, `pool_pre_ping` остаётся включён. При одной Machine в каждой группе
это до четырёх клиентских соединений приложения; rolling deploy и release task временно
добавляют соединения. Учитывайте Dashboard, pooler и другие клиенты; session pooler не
отменяет серверные лимиты. См. [pooling and limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits).

Free: 500 MB БД, 5 GB egress, до двух активных проектов; возможна пауза после недели
неактивности. Не считать это SLA для постоянного демо. Фотографии хранятся в R2,
а не в PostgreSQL/Supabase Storage. Следить за размером анализов и исходящим трафиком
опроса dashboard. Перед показом проверить, что проект активен, и сохранить резервную
копию нужных синтетических данных. Лимиты перепроверять в [Supabase pricing](https://supabase.com/pricing).

**До создания таблиц отключите Supabase Data API**, поскольку Blue не использует REST/
GraphQL Supabase. SQLAlchemy создаёт таблицы в `public`; они не должны стать альтернативным
анонимным API. Проверьте grants/RLS, не выдавайте `anon`/`authenticated` доступ к таблицам
Blue. Не добавляйте разрешающие RLS policies ради демо. См.
[Securing your API](https://supabase.com/docs/guides/api/securing-your-api).

## 4. Fly app и secrets — действия владельца

В PowerShell, из корня checkout `pre-main`:

```powershell
flyctl auth login
flyctl auth whoami
# Выберите существующую организацию, проверьте её billing.
flyctl apps create <unique-blue-app> --org <owner-org>
# Публичные адреса только API Fly Proxy, не базы данных:
flyctl ips allocate-v6 --app <unique-blue-app>
flyctl ips allocate-v4 --shared --app <unique-blue-app>
```

Замените `app` в `fly.toml` на созданное имя, проверьте `primary_region`. Не запускайте
`fly launch` поверх подготовленной конфигурации. Второй app для worker не нужен.

Подготовьте файл `NAME=VALUE` **вне checkout** с настоящими значениями:

| Переменная | Значение |
| --- | --- |
| `DATABASE_URL` | Одна согласованная PostgreSQL TLS DSN для API и worker |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Ключ владельца и доступная ему модель |
| `ENTITY_HASH_SECRET` | Случайный устойчивый секрет |
| `INGEST_API_TOKEN` | Случайный Bearer token, только server/operator |
| `R2_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | Выделенный приватный bucket демо |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Bucket-scoped S3 credentials |
| `CORS_ORIGINS` | Точный HTTPS origin Pages, без `*` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | Секреты бота и webhook |
| `TELEGRAM_HASH_SECRET` | Отдельный постоянный HMAC secret |
| `TELEGRAM_ALLOWED_USER_IDS` | ID добровольных тестировщиков, через запятую |
| `TELEGRAM_WEBHOOK_URL` | `https://<unique-blue-app>.fly.dev/webhooks/telegram` |
| `TELEGRAM_RETENTION_DAYS`, `TELEGRAM_RETENTION_SWEEP_SECONDS` | `30`, `3600` |

```powershell
Get-Content -Raw -LiteralPath 'C:\secure\blue-fly.env' | flyctl secrets import --stage --app <unique-blue-app>
flyctl config validate --strict --config fly.toml
flyctl deploy . --config fly.toml --ha=false --remote-only
flyctl scale count api=1 worker=1 --app <unique-blue-app>
flyctl status --app <unique-blue-app>
flyctl checks list --app <unique-blue-app>
```

Эти команды **здесь не выполнялись**. `--ha=false` предотвращает автоматическое создание
spare Machines при первом деплое, но не удаляет ранее существующие; проверьте реальное
число Machines после scale. Remote builder и release task могут иметь отдельные расходы.
При запросе оплаты/смены плана остановитесь до решения владельца. Не добавляйте реальные
значения в `fly.toml`, Git, аргументы build или terminal transcript.

## 5. Приватный R2

Владелец создаёт отдельный bucket, оставляет public access, `r2.dev` и публичный custom
domain выключенными. Выдаёт токен только на нужный bucket с object read/write и импортирует
одинаковые параметры в общий Fly app. Не принимать billing prompts автоматически.
См. [R2 S3 API](https://developers.cloudflare.com/r2/get-started/s3/).

API сохраняет `blue-media/<filename>`, worker читает оригинальные байты через S3 API.
Frontend получает `/api/media/<filename>` от Blue; bucket остаётся приватным. Сам Blue
dashboard открыт только ради синтетического демо. Локальный `media/` между Machines не
разделяется и на Fly отклоняется кодом. Старые локальные файлы автоматически не мигрируют.
`image_analyzed=true` сохраняется только после успешного multimodal analysis; при текстовом
fallback остаётся false. Без реальной проверки R2 не считать изображения готовыми в облаке.

## 6. Frontend, seed и Telegram

Cloudflare Pages: GitHub `NivaroCodes/Blue`, ветка `pre-main`, root `frontend`, build
`npm ci && npm run build`, output `dist`, Node 22.12+.
Публичные переменные: `VITE_API_BASE_URL=https://<unique-blue-app>.fly.dev`, `VITE_DATA_MODE=api`.
Не добавлять PostgreSQL, Gemini, ingestion, Telegram или R2 secrets в `VITE_*`.
После получения Pages URL обновить API CORS. Старый сохранённый режим браузера переключить
на рабочие данные; проверить прямую загрузку detail route.

В отдельном операторском окружении задать `DEMO_API_URL` и `INGEST_API_TOKEN`, затем:

```powershell
python run.py seed-demo
python run.py seed-demo
```

Ожидается 36 уникальных вымышленных сообщений, включая три PNG, без очистки БД и без
готовых AI-результатов. **Legacy `python run.py seed` очищает данные — его не использовать.**
Worker обрабатывает очередь штатным pipeline. `WORKER_THROTTLE_SECONDS=4.5` — интервал
внутри пачки одного worker, а не глобальный лимитер. Сначала одна worker Machine.

После успешного HTTPS `/health`, в окружении оператора с переменными бота:

```powershell
python -m ai_data.telegram_connector set-webhook
```

Проверить `getWebhookInfo` без вывода token-containing URL в общие логи. В личном чате
проверить `/start`, `/consent`, `/agree`, `/analyze` с синтетическим текстом, `/revoke` и
`/delete_my_data`. Allowlist и webhook secret обязательны. Группы и каналы игнорируются;
community можно использовать для объявления теста, автоматический сбор не включается.

## 7. Проверки и граница готовности

Локально, только с изолированной PostgreSQL test DB:

```powershell
git diff --check
python -m pip install -r requirements-dev.txt
python -m pytest ai_data/tests/test_telegram_connector.py -q
python -m pytest ai_data/tests -q
python run.py test
python test_e2e_full.py
docker build -t blue-fly-check .
cd frontend
npm ci
npm run build
npm test
```

`TEST_DATABASE_URL` должен иметь строгое test-имя. Supabase `postgres` не проходит этот
защитный барьер: не обходить его и не запускать очищающие тесты против демо-проекта.
Docker build требует работающий локальный daemon; локальная проверка TOML не заменяет
платформенную `flyctl config validate`, сборку Linux image и cloud smoke.

После деплоя владелец проверяет:

- `https://<app>.fly.dev/health` → 200, PostgreSQL доступен; без токена ingestion → 401.
- `flyctl logs --app <app>`: запуск обеих групп, очередь обрабатывается, нет stuck claims,
  ошибок соединения, OOM, раскрытых DSN/токенов. `/health` проверяет API/БД, не worker/R2/Gemini.
- Seed дважды → ровно 36 записей, все PROCESSED; три изображения получены worker из R2,
  после перезапуска Machines доступны оригиналы и OCR, dashboard отражает реальные stats.
- Pages обращается к Fly API с корректным CORS, не подменяет данные локальными fixtures.
- Реальный private-chat webhook, согласие, отзыв и удаление работают; group updates игнорируются.
- Bundle и логи не содержат secrets. У Supabase не открыт Data API для таблиц Blue.

Доступные live browser suites остаются opt-in: `BLUE_LIVE_E2E=1` требует отдельные локальные
test DB/API/Gemini и очищает test DB. `BLUE_SYNTHETIC_E2E=1` вместе с `API_PROXY_TARGET`
проверяет уже заполненное демо без очистки: `npm test -- tests/synthetic-live.spec.ts`.
Не использовать облачные credentials автоматически. При непроверенном пункте не объявлять
релиз готовым и не переносить его в `main`.

## 8. Локальная проверка этой миграции

2026-10-25, исходный HEAD `48c3fae50a14f7526a228fce1ee428ab01f97ac1`:

| Проверка | Результат |
| --- | --- |
| `git diff --check` | Успешно |
| `python -m pytest ai_data/tests -q` | 128 passed, включая 15 Telegram-тестов |
| `python run.py test` | 113 unittest-тестов, успешно |
| `python test_e2e_full.py` | Все 8 шагов на локальном PostgreSQL, AI mock |
| `npm run build` | Успешно; предупреждения о размере bundles остаются |
| `npm test` | 42 passed, 6 live-тестов явно skipped |
| `fly.toml` | Локальный TOML parse и согласованность портов/process groups проверены |
| Linux Docker build | Не выполнен: локальный Docker daemon недоступен |
| Fly platform validation, Supabase, R2, webhook | Не выполнены: облачные credentials не использовались |

Новые runtime-тесты проверяют fail-closed ingestion на Fly, запрет local media,
отключение production reload, ограничение соединений и сохранность сообщений при `init-db`.
Предыдущий успешный локальный Gemini/image smoke описан в `RELEASE_VERIFICATION.md`;
он не подтверждает новую облачную архитектуру. Настоящие облачные live-тесты не запускались.

## 9. Расходы

По официальному примеру [Fly resource pricing](https://fly.io/docs/about/pricing/) одна
постоянная `shared-cpu-1x` 512 MB Machine стоит примерно $3.69/месяц: две — около **$7.38**
за compute, до региональных отличий. Практический предварительный бюджет — **$8–12/месяц**
при малом трафике, без гарантий: добавить builders/release overlap, egress, налоги и Gemini.
Dedicated IPv4, volumes и static egress в базовую конфигурацию не заложены.

Supabase Free — $0 в пределах ограничений и согласованной сетевой модели. R2 Standard
имеет бесплатные квоты (10 GB-month хранения и квоты операций); Pages static обычно
укладывается в Free, но это не отменяет проверку текущих [R2 цен](https://developers.cloudflare.com/r2/pricing/)
и [Pages limits](https://developers.cloudflare.com/pages/platform/limits/).
Обязательные сетевые опции могут изменить бюджет. Владелец проверяет usage/billing во всех
четырёх сервисах и Gemini, устанавливает доступные уведомления/лимиты и следит за числом
Machines. Alerts не обещают жёсткого лимита списаний. Тарифы здесь не менялись.
