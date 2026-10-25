# Инструкция для Backend-разработчика (SafeNet KZ)

> **Ветка в Git:** `ai-data`  
> **Роль:** Интеграция парсера, базы данных и фронтенда с готовым AI-модулем.

---

## 1. Что уже готово (Data / AI)

1. **100% LLM-анализ (Google Gemini / OpenAI-compatible)**: Никаких заглушек. При недоступности ИИ статус становится `ERROR`.
2. **Защита от галлюцинаций**: Улики (`evidence`) валидируются как точные подстроки исходного текста (или OCR-текста изображения с пометкой `source: "image"`).
3. **Защита от обфускации и скрытых схем**: Распознаёт гомоглифы (`Kаspі`), leet-speak (`вл0жи`, `5ООО`), точки (`в.л.о.ж.и`), таск-скамы («лайки товарам» с залогом) и фейковую помощь с предоплатой доставки на Kaspi.
4. **Безопасная репутация с учётом решений аналитика**: Повышение оценки по репутации срабатывает **только по подтверждённым аналитиком** вердиктам (`REVIEWED`) и при выборке чата `>= 5` сообщений; `FALSE_POSITIVE` исключается из статистики и графа, а непроверенные авто-оценки не усиливают сами себя.
5. **Граф синдикатов без коллизий карт**: Полный 16-значный номер карты хэшируется через `HMAC-SHA256` (`normalized_value`) для точного связывания авторов, а в интерфейс отдаётся только безопасная маска `4400 **** **** 1234` (`display_value`).
6. **Корректный часовой пояс (`UTC` -> `+05:00`)**: В БД все времена хранятся строго в UTC (`UTCDateTime`), а в API конвертируются в часовой пояс Казахстана (`+05:00`) с пересчётом часов.
7. **Дедупликация по `(platform, chat_id, message_id)`**: Локальные номера сообщений из разных чатов и платформ не затирают друг друга (`make_message_pk`).
8. **Атомарная очередь воркера и единый пайплайн изображений**: Атомарный захват `PENDING -> PROCESSING` (`claimed_by`, `claimed_at`, `recover_stale_claims`) исключает двойную обработку при параллельной работе API и воркеров; воркер анализирует `image_url`, а `POST /api/analyze-image` сохраняет результат как полноценный алерт.

---

## 2. Эндпоинты и контракты

### 1. Приём сообщений от парсера — `POST /api/messages`
```json
{
  "platform": "telegram",
  "chat_id": "tg_invest_kz",
  "chat_name": "Инвест Клуб",
  "chat_url": "https://t.me/chat_link",
  "message_id": "101",
  "sender_hash": "user_hash_abc",
  "text": "Вложи 5 000 тг — удвой за 24ч",
  "image_url": null,
  "image_base64": null,
  "timestamp": "2026-10-22T14:00:00+05:00"
}
```
* Ключ дедупликации: `(platform, chat_id, message_id)`.
* При `INLINE_ANALYSIS=1` сразу запускается атомарный AI-анализ; при `INLINE_ANALYSIS=0` запись остаётся в `PENDING` для фонового воркера.
* Ответ: `{ "id": "alert_m_...", "message_id": "101", "status": "PROCESSED" }`.

### 2. Список и детали алертов — `GET /api/alerts`, `GET /api/alerts/{id}`
Полностью соответствует `docs/API.md` и Zod-схеме фронтенда (`AlertSchema`):
```json
{
  "id": "alert_m_8f12...",
  "platform": "telegram",
  "chat_id": "tg_invest_kz",
  "chat_name": "Инвест Клуб",
  "chat_url": "https://t.me/chat_link",
  "message_id": "101",
  "sender_hash": "user_hash_abc",
  "text": "Вложи 5 000 тг — удвой за 24ч",
  "image_url": null,
  "timestamp": "2026-10-22T14:00:00+05:00",
  "status": "PROCESSED",
  "risk_score": 95,
  "risk_level": "HIGH",
  "reasons": [
    { "code": "UNREALISTIC_RETURN", "evidence": "удвой за 24ч" }
  ],
  "explanation": "Развёрнутый разбор схемы...",
  "confidence": 0.98,
  "image_analyzed": false,
  "image_text": null,
  "review_status": "NEW",
  "reviewer_note": "",
  "reviewed_by": null,
  "model_version": "gemini-gemini-3-flash-preview"
}
```

### 3. Решение аналитика — `POST /api/alerts/{id}/review`
Принимает `{ "review_status": "REVIEWED" | "FALSE_POSITIVE" | "NEW", "reviewer_note": "...", "reviewed_by": "analyst_1" }`. Обновляет `reviews` и сразу влияет на расчёт репутации автора/чата и графа связей.

### 4. Статистика — `GET /api/stats`
Возвращает `{ "total_messages", "last_24h", "pending", "processing", "errors", "by_level": { "HIGH", "MEDIUM", "LOW" } }`.

### 5. Граф связей — `GET /api/network-graph`
Вызывает `analyze_network_graph(session)` и возвращает `nodes`, `links`, `syndicates`, `bot_clusters`, `cross_chat_senders`, `high_risk_chats`.

### 6. Мультимодальный анализ скриншотов — `POST /api/analyze-image` и `GET /api/media/{filename}`
Сохраняет скриншот в `MEDIA_DIR`, создаёт стандартный `MessageRecord` + `AnalysisRecord` + `EntityRecord` (с извлечением карт/телефонов из OCR скриншота) и возвращает готовый объект `Alert`, который сразу виден в `/api/alerts`.

### 7. Экспорт — `GET /api/export?format=csv|json`
Выгружает реестр инцидентов для отчётности (АФМ / АРРФР).

---

## 3. Окружение и команды запуска

В `.env`:
```env
GEMINI_API_KEY=your_gemini_api_key_here
AI_MODEL_NAME=gemini-3-flash-preview
DATABASE_URL=sqlite:///safenet.db
INLINE_ANALYSIS=1
ENTITY_HASH_SECRET=change-me-in-production
```

## 4. Входящие сообщения через вебхуки

Вебхук — это HTTP-адрес backend, на который Telegram или GREEN-API отправляет POST-запрос при
новом сообщении. Blue принимает события непосредственно, затем использует общий `_ingest` и
таблицы сообщений/анализа. База данных не открывается в интернет.

Endpoints:

- `POST /webhooks/telegram` — Telegram Bot API; защищается заголовком
  `X-Telegram-Bot-Api-Secret-Token` и принимает только group/supergroup с ID из `TELEGRAM_CHAT_ID`.
- `POST /webhooks/green-api` — GREEN-API; защищается `Authorization` и принимает только
  `GREEN_API_ALLOWED_CHAT_ID`.

Все dashboard endpoints (`/api/alerts`, `/api/stats`, `/api/network-graph`, `/api/export`,
review и изображения) в production требуют `Authorization: Bearer <token>`. Backend принимает
Supabase Auth access token либо серверный `INGEST_API_TOKEN`/`DASHBOARD_API_KEY`. Не встраивай
эти серверные ключи в `VITE_*` и JavaScript браузера. Если сайт показывает HTTP 401, frontend
должен отправлять Supabase session access token; публичный demo endpoint для реальных сообщений
не включай.

Дополнительные secrets backend:

```env
SENDER_HASH_SECRET=длинный_случайный_секрет
TELEGRAM_HASH_SECRET=если SENDER_HASH_SECRET не задан, используется этот ключ
TELEGRAM_BOT_TOKEN=токен_бота
TELEGRAM_CHAT_ID=-100...
TELEGRAM_WEBHOOK_SECRET=случайный_секрет_для_заголовка_Telegram
TELEGRAM_WEBHOOK_URL=https://your-app.fly.dev/webhooks/telegram
GREEN_API_API_URL=https://your-instance.api.green-api.com
GREEN_API_ID_INSTANCE=...
GREEN_API_TOKEN_INSTANCE=...
GREEN_API_WEBHOOK_TOKEN=отдельный_секрет_для_GREEN_API
GREEN_API_ALLOWED_CHAT_ID=...
DATABASE_URL=postgresql+psycopg://user:password@host:5432/postgres
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

Перед настройкой провайдеров сначала выложи backend с обоими маршрутами и добавь их переменные
окружения в Fly Secrets. Telegram Bot API настраивается командой
`python -m ai_data.configure_telegram_webhook`; она использует `TELEGRAM_PUBLIC_BASE_URL`, задаёт
endpoint `/webhooks/telegram`, передаёт `TELEGRAM_WEBHOOK_SECRET` и разрешает update `message` и
`channel_post`. Чтобы бот видел обычные сообщения в группе, отключи Group Privacy в BotFather или
выдай боту права администратора. Добавляй бота только в выделенную тестовую группу с
синтетическими сообщениями и уведомлёнными участниками: текущий dashboard/export не имеет
пользовательской авторизации и может раскрыть сохранённое содержимое.

GREEN-API настраивается после выкладки командой `python -m ai_data.configure_green_api_webhook`.
Она задаёт endpoint `/webhooks/green-api`, `incomingWebhook=yes` и токен авторизации в формате
`Bearer <GREEN_API_WEBHOOK_TOKEN>`. GREEN-API перезапускает instance после `setSettings`; настройки
могут примениться в течение пяти минут. Не запускай эту команду до появления маршрута в Fly.

Поддерживаются текст Telegram/WhatsApp и изображения; изображения скачиваются через Bot API или
GREEN-API и передаются существующему мультимодальному pipeline. На Fly локальная папка `media/`
эфемерна: для сохранения изображений после перезапуска надо подключить постоянный volume или
внешнее объектное хранилище. Секреты добавляются в Fly Secrets, не в Git.
Загрузка картинок разрешает HTTPS только с доменов Telegram/GREEN-API, запрещает redirects и
ограничивает размер; все остальные URL отклоняются.

Команды:
```bash
python run.py api      # Запуск FastAPI сервера (http://127.0.0.1:8000)
python run.py worker   # Запуск фонового AI-воркера (безопасно в несколько процессов)
python run.py seed     # Засев БД тестовыми сценариями
python run.py test     # Прогон всех 26 модульных и конкурентных тестов
```
