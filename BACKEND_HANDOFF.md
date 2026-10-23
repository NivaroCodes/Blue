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
* При `INLINE_ANALYSIS=0` (по умолчанию) запись сохраняется со статусом `PENDING` для обработки воркером; при `INLINE_ANALYSIS=1` выполняется синхронный анализ.
* Ответ: `{ "id": "alert_m_...", "message_id": "101", "status": "PENDING" }` (или `"PROCESSED"` при включённом синхронном режиме).

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
INLINE_ANALYSIS=0
ENTITY_HASH_SECRET=change-me-in-production
```

Команды:
```bash
python run.py api      # Запуск FastAPI сервера (http://127.0.0.1:8000)
python run.py worker   # Запуск фонового AI-воркера (безопасно в несколько процессов)
python run.py seed     # Засев БД тестовыми сценариями
python run.py test     # Прогон всех 38 модульных, конкурентных и интеграционных тестов
```
