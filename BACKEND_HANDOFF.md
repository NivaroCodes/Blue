# Инструкция для Backend-разработчика (SafeNet KZ)

> **Ветка в Git:** `ai-data`  
> **Роль:** Интеграция парсера, базы данных и фронтенда с готовым AI-модулем.

---

## 1. Что уже готово (Data / AI)

1. **100% LLM-анализ (Google Gemini)**: Никаких заглушек. При недоступности ИИ статус становится `ERROR`.
2. **Защита от галлюцинаций**: Улики (`evidence`) строго вырезаются как точные подстроки исходного текста.
3. **Защита от обфускации**: Распознаёт смесь латиницы/кириллицы (`Kаspі`), цифры в словах (`вл0жи`, `5ООО`) и точки (`в.л.о.ж.и`).
4. **Скрытые схемы**: Детектирует таск-скамы («работа на дому/лайки» с залогом) и фейковую помощь («бесплатная еда/продукты» с оплатой доставки на Kaspi).
5. **Динамическая эскалация**: Если автор спамит в разные чаты или чат признан скам-хабом — ИИ автоматически повышает риск.
6. **Схема БД (SQLAlchemy)**: [`ai_data/db/models.py`](file:///c:/Users/LOQ/Downloads/blue/ai_data/db/models.py) (таблицы `messages`, `analyses`, `reviews`, `entities`).
7. **AI-воркер**: [`ai_data/worker.py`](file:///c:/Users/LOQ/Downloads/blue/ai_data/worker.py) — слушает `PENDING`, прогоняет через ИИ, вычленяет сущности и пишет `PROCESSED`.
8. **Готовый API-сервер**: [`ai_data/api_server.py`](file:///c:/Users/LOQ/Downloads/blue/ai_data/api_server.py) — полностью рабочий эталон на FastAPI.

---

## 2. Что нужно сделать Бэкендеру (Задачи)

### Задача 1. Приём сообщений от парсера
* **Эндпоинт**: `POST /api/messages`
* **Входной JSON**:
  ```json
  {
    "platform": "telegram",              // "telegram" | "whatsapp"
    "chat_id": "tg_invest_kz",
    "chat_name": "Инвест Клуб",
    "chat_url": "https://t.me/chat_link", // ссылка на группу из парсера
    "message_id": "msg_101",
    "sender_hash": "user_hash_abc",
    "text": "Вложи 5 000 тг — удвой за 24ч",
    "timestamp": "2026-10-22T14:00:00+05:00"
  }
  ```
* **Действие**: Сохранить в таблицу `messages` со статусом **`PENDING`**.
* **Результат**: AI-воркер сам заберёт запись из БД и проанализирует.

---

### Задача 2. Эндпоинты для Фронтенда (по контракту `docs/API.md`)

#### 1. `GET /api/alerts`
* Возвращает список алертов (join `messages` + `analyses` + `reviews`).
* **Формат одного элемента**:
  ```json
  {
    "id": "alert_msg_101",
    "platform": "telegram",
    "chat_id": "tg_invest_kz",
    "chat_name": "Инвест Клуб",
    "chat_url": "https://t.me/chat_link",
    "message_id": "msg_101",
    "sender_hash": "user_hash_abc",
    "text": "Вложи 5 000 тг — удвой за 24ч",
    "image_url": null,
    "timestamp": "2026-10-22T14:00:00+05:00",
    "status": "PROCESSED",               // PENDING | PROCESSING | PROCESSED | ERROR
    "risk_score": 95,                    // число 0-100 (или null, если не PROCESSED)
    "risk_level": "HIGH",                // LOW | MEDIUM | HIGH (или null)
    "reasons": [
      { "code": "UNREALISTIC_RETURN", "evidence": "удвой за 24ч" }
    ],
    "explanation": "Развёрнутый разбор схемы...",
    "confidence": 0.98,
    "review_status": "NEW",              // NEW | REVIEWED | FALSE_POSITIVE
    "reviewer_note": "",
    "reviewed_by": null,                 // логин аналитика, подтвердившего алерт
    "model_version": "gemini-3-flash"
  }
  ```

#### 2. `GET /api/alerts/{id}`
* Возвращает один объект алерта по `id` (структура как выше).

#### 3. `POST /api/alerts/{id}/review`
* Вызывается, когда аналитик на дашборде нажал кнопку проверки.
* **Принимает**:
  ```json
  {
    "review_status": "REVIEWED",         // или "FALSE_POSITIVE"
    "reviewer_note": "Проверено, заблокирован",
    "reviewed_by": "analyst_1"
  }
  ```
* **Действие**: Обновляет запись в таблице `reviews`.

#### 4. `GET /api/stats`
* Счётчики для карточек дашборда:
  ```json
  {
    "total_messages": 25,
    "pending": 0,
    "processing": 0,
    "errors": 0,
    "by_level": {
      "HIGH": 14,
      "MEDIUM": 6,
      "LOW": 5
    }
  }
  ```

#### 5. `GET /api/network-graph` (Хакатон Критерий 3: Граф синдикатов)
* Готовая логика уже лежит в [`ai_data/graph_analysis.py`](file:///c:/Users/LOQ/Downloads/blue/ai_data/graph_analysis.py).
* Возвращает стандартную структуру `nodes` и `links` для визуализации D3.js/Cytoscape, список скам-хабов, ботов и выявленные финансовые синдикаты (боты с общими номерами телефонов/картами Kaspi).
* Вызов:
  ```python
  from ai_data.graph_analysis import analyze_network_graph
  return analyze_network_graph(session)
  ```

#### 6. `GET /api/export?format=csv` (Экспорт отчёта для АФМ / АРРФР)
* Выгружает полный реестр выявленных инцидентов в формате CSV или JSON со всеми уликами и ссылками на чаты (`chat_url`).

#### 7. `POST /api/analyze-image` (Мультимодальный анализ скриншотов)
* Принимает `{ "image_base64": "...", "text_caption": "..." }` и прогоняет чек Kaspi или фальшивый баланс через Gemini Vision.

---

### Задача 3. Запуск фонового воркера

Воркер можно запускать как отдельный демон:
```bash
python run.py worker
```
Или вызывать функцию в коде фоновой очереди (Celery / BackgroundTasks):
```python
from ai_data.worker import process_pending_messages
process_pending_messages(session, limit=10)
```

---

### Задача 4. CORS и окружение

1. В `.env` файле должны быть:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   AI_MODEL_NAME=gemini-3-flash-preview
   DATABASE_URL=sqlite:///safenet.db
   ```
2. Разрешить CORS для фронтенда: `http://localhost:5173` и `http://127.0.0.1:5173`.

---

## 3. Быстрые команды для проверки

```bash
# Запустить уже готовый эталонный бэк
python run.py api

# Запустить обработку сообщений через ИИ
python run.py worker

# Засеять базу 25 реалистичными сценариями (боты, скам-хабы, казахский язык)
python run.py seed

# Прогнать 14 модульных тестов
python run.py test
```
