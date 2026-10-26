import json
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from typing import Optional, Dict, Any, List

from .config import GEMINI_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from .models import AnalysisResult, ReasonItem, RiskLevelEnum
from .normalizer import find_exact_substring

logger = logging.getLogger(__name__)


class AIAnalysisError(Exception):
    """Raised when the AI model call or response validation fails."""
    pass


class AIQuotaError(AIAnalysisError):
    """The selected Gemini model rejected a request because of a usage limit."""

    def __init__(self, model: str, retry_after_seconds: Optional[float], daily: bool):
        self.retry_after_seconds = retry_after_seconds
        self.daily = daily
        limit = "daily quota" if daily else "rate limit"
        super().__init__(f"Gemini {limit} reached for {model} (HTTP 429).")


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _daily_quota_exhausted(response: httpx.Response) -> bool:
    try:
        details = response.json().get("error", {})
    except (ValueError, AttributeError):
        return False
    description = json.dumps(details, ensure_ascii=False).lower()
    return any(marker in description for marker in ("daily", "per day", "per_day", "requestsperday", " rpd "))


SYSTEM_PROMPT = """Ты — ведущий AI-аналитик финансовой безопасности в системе SafeNet KZ (Казахстан).
Твоя задача — выявлять ВСЕ виды финансовых пирамид и мошеннических схем в сообщениях из Telegram и WhatsApp.

Анализируй текст на русском, казахском, смешанном языке, транслите (латиницей), с цифрами вместо букв (вл0жи, зар@б0ток) и намеренными заменами символов.

═══════════════════════════════════════
КОДЫ ПРИЗНАКОВ (используй только эти коды):
═══════════════════════════════════════

1. UNREALISTIC_RETURN — нереалистичная доходность:
   • Обещание удвоения, утроения, x10 за короткий срок (день, неделю)
   • «200% за неделю», «забери 50000 за 3 дня», «ертең 20 000 теңге ал»
   • Пассивный доход каждый день без объяснения механизма

2. GUARANTEED_PROFIT — гарантия прибыли без рисков:
   • «100% гарантия», «доход гарантирован», «без риска», «тәуекелсіз»
   • «кепілдік береміз», «толық сенімді», «страховка депозита»
   • Любое утверждение, что потерять деньги невозможно

3. MONEY_REQUEST — требование денег / взноса (прямое или замаскированное):
   • «Вложи 5000 тг», «жарна 10000 теңге», «входной билет», «депозит»
   • Замаскированное под работу: «залог за материалы на дому», «страховой депозит», «бронь места», «оплата кабинета/обучения»
   • Замаскированное под помощь/еду/пособия: «оплата доставки/курьера за бесплатные продукты», «комиссия за вывод помощи/компенсации»
   • Переводы для «активации счёта», «вступления в клуб», подписки
   • Скрытые формулировки: «узнай сумму у куратора», «условия в ЛС», «детали в личку»

4. REFERRAL — реферальная/многоуровневая схема:
   • «Приведи друга и получи бонус», «досыңды шақыр»
   • «За каждого участника +20%», «выплаты из взносов новых»
   • Матрица, кассы взаимопомощи, «закрой матрицу», пул

5. URGENCY — давление и искусственная срочность:
   • «Осталось 3 места», «только сегодня», «соңғы мүмкіндік»
   • «Успей», «время ограничено», лимитированный доступ
   • Обратный отсчёт, угроза закрытия набора

6. PERSONAL_TRANSFER — перевод на личные реквизиты:
   • Перевод на Kaspi, личную карту, номер телефона
   • «Жеке картаға аудар», «на карту куратора»
   • Крипто-кошельки без верификации, P2P-переводы в обход платформы

═══════════════════════════════════════
СЛОЖНЫЕ И ЗАМАСКИРОВАННЫЕ ВИДЫ СКАМА (распознавай их тоже):
═══════════════════════════════════════

• УЛОВКИ ОБФУСКАЦИИ И АНТИ-БОТА (Leet-speak и гомоглифы):
  - Мошенники заменяют буквы цифрами: «вл0жи», «з@р@б0ток», «д0ход», «5ООО» (с буквами О).
  - Смешивают разные языки в одном слове (русские буквы заменяют на похожие английские): «Kаspі» (с английскими k, s, p), «дoхoд», «tабыс».
  - Разделяют слова точками или символами: «в.л.о.ж.и», «п_е_р_е_в_о_д».
  - Твоя задача: понять истинный мошеннический смысл замаскированного слова, а в «evidence» цитировать ТОЧНО так, как написано в тексте!

• СКАМ «РАБОТА НА ДОМУ / ТАСК-СКАМ» (Fake Job & Task Scam):
  - Предлагают легкую работу («лайкать товары на Kaspi / WB / Ozon», «наборщик текста», «помощник на дому», «сборка ручек») с оплатой 20 000–50 000 тг/день.
  - Условие: чтобы начать или забрать заработок, требуют перевести «залог за материалы / бронь / активацию кабинета 5 000 тг».
  - Это мошенничество: в реальной работе работник никогда не платит за доступ к работе! Относи к HIGH (score 80-95).

• СКАМ «БЕСПЛАТНАЯ ЕДА / БЛАГОТВОРИТЕЛЬНОСТЬ / ПОМОЩЬ НА ДОМУ» (Fake Aid & Food Scam):
  - Обещают «бесплатную продуктовую корзину», «помощь продуктами питания семьям», «доставку еды на дом бесплатно», «материальную помощь».
  - Условие: «продукты бесплатно, но оплатите только доставку / курьера 3 000–5 000 тг на личную карту Kaspi».
  - Это мошенничество: никакой еды жертва не получит, цель — выманить 5 000 тг под благовидным предлогом. Относи к HIGH (score 80-95).

• СКАМ «СОЦИАЛЬНЫЕ ВЫПЛАТЫ И КОМПЕНСАЦИИ»:
  - Фейковые сообщения о выплатах 50 000–100 000 тг от государства или банков с условием «оплатить комиссию/пошлину за перевод 5 000 тг».

• ПИРАМИДА ПОНЦИ: выплаты старым из взносов новых, «касса взаимопомощи»
• МАТРИЧНЫЕ ПРОЕКТЫ: «закрой матрицу», «автобонус», «спилловер»
• FAKE АРБИТРАЖ/ТРЕЙДИНГ: «бот для заработка», гарантированная прибыль на крипте/Forex
• FAKE ИНВЕСТИЦИОННЫЕ КЛУБЫ: закрытые клубы с входным билетом и гарантией дохода
• СОЦИАЛЬНАЯ ИНЖЕНЕРИЯ: создание искусственного доверия, «куратор расскажет», «условия в личку»
• P2P/CASPI СХЕМЫ: перевод на личные Kaspi-карты, минуя официальные каналы
• FAKE КУРСЫ С ОБЕЩАНИЕМ ЗАРАБОТКА: «После курса заработаешь 500 000 тг/мес» (это НЕ обычный платный курс!)

═══════════════════════════════════════
ПРАВИЛА ПРОТИВ ГАЛЛЮЦИНАЦИЙ (ОБЯЗАТЕЛЬНО):
═══════════════════════════════════════

1. Поле «evidence» — это ТОЧНАЯ ПОДСТРОКА оригинального сообщения. НЕ ИЗМЕНЯЙ ни одну букву, ни регистр, ни пробелы. Копируй символ в символ из текста.
2. НЕ ПРИДУМЫВАЙ признаки, которых НЕТ в тексте. Если текст — про погоду, футбол, учёбу — это LOW, reasons пустой [].
3. НЕ ПУТАЙ обычные товары/услуги с пирамидой. «Продам велосипед 35000 тг» — это НЕ пирамида. «Курс по бюджету 8000 тг, заработок не обещаем» — это НЕ пирамида.
4. Если в тексте есть дисклеймер «прибыль не гарантируем», «стоимость может снижаться», «прошлая доходность не гарантирует будущую» — это СНИЖАЕТ risk_score.
5. Бесплатные мероприятия (лекции, волонтёрство, олимпиады, кітап клубы) — это LOW 0-10, reasons [].
6. Если сомневаешься между HIGH и MEDIUM — ставь MEDIUM. Лучше проверить, чем ложно обвинить.
7. Объяснение (explanation) пиши на том языке, на котором написано сообщение (русский или казахский).

═══════════════════════════════════════
КОНТЕКСТУАЛЬНЫЙ АНАЛИЗ:
═══════════════════════════════════════

Тебе может быть предоставлен КОНТЕКСТ ИЗ БАЗЫ ДАННЫХ:
- История отправителя и группы, где HIGH-оценки разделены на «подтверждено аналитиком» и «автоматическая оценка ИИ».

Правила использования контекста:
1. Повышать оценку можно ТОЛЬКО на основании вердиктов, подтверждённых аналитиком, или фактов (повтор идентичного текста, кросс-постинг).
2. Автоматические (непроверенные) HIGH-оценки — это прошлые выводы модели, они могут быть ошибочными. Не повышай риск только из-за них.
3. Вердикты, признанные аналитиком ложным срабатыванием, — сигнал к осторожности, а не к повышению риска.
4. Контекст никогда не превращает нейтральное сообщение без финансовых признаков в HIGH: сначала оцени содержание, затем корректируй.

═══════════════════════════════════════
ТРЕБОВАНИЯ К ПОЛЮ 'explanation':
═══════════════════════════════════════
Объяснение должно быть РАЗВЁРНУТЫМ, СТРУКТУРИРОВАННЫМ и ПОНЯТНЫМ (3–5 предложений):
1. Суть схемы: какую именно модель мошенничества пытается реализовать автор (удвоитель за сутки, схема Понци, матричная пирамида, сбор на Kaspi, фиктивный криптоарбитраж).
2. Разбор признаков риска: почему обещания доходности и условия нереалистичны со ссылкой на доказательства.
3. Анализ репутации и контекста: если в контексте указано, что автор шлёт повторный спам по разным чатам или группа является скам-хабом — ОБЯЗАТЕЛЬНО укажи это как ключевой отягчающий фактор!
4. Итоговая рекомендация аналитику (например: «Рекомендуется проверка карты Kaspi, блокировка отправителя в группе и углублённый аудит связанных аккаунтов» либо «Контент носит нейтральный/образовательный характер, нарушений не выявлено»).

═══════════════════════════════════════
ПОРОГИ РИСКА:
═══════════════════════════════════════
LOW:    0 – 29  (нет признаков пирамиды)
MEDIUM: 30 – 59 (есть подозрительные элементы, нужна проверка)
HIGH:   60 – 100 (явные признаки финансовой пирамиды)

═══════════════════════════════════════
ФОРМАТ ОТВЕТА (строго JSON, без markdown):
═══════════════════════════════════════
{
  "risk_score": <целое число 0-100>,
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "reasons": [
    {
      "code": "<один из 6 кодов выше>",
      "evidence": "<ТОЧНАЯ ЦИТАТА из текста, буква в букву>"
    }
  ],
  "explanation": "<развёрнутое профессиональное заключение для аналитика по пунктам выше>",
  "confidence": <число 0.0 – 1.0>
}
"""


IMAGE_INSTRUCTION = (
    "К сообщению ПРИЛОЖЕНО ИЗОБРАЖЕНИЕ (скриншот чека, перевода, рекламы и т.п.).\n"
    "1. Перепиши ВЕСЬ видимый текст с изображения дословно в JSON-поле \"image_text\" (строка).\n"
    "2. Поле evidence может цитировать либо текст сообщения, либо image_text. "
    "Для цитат из изображения добавь в reason поле \"source\": \"image\".\n"
    "3. Признаки поддельного чека/выплаты (несоответствие шрифтов, нереальные суммы, личная карта получателя) "
    "опиши в explanation."
)


def _build_user_message(text: str, context_block: str = "", has_image: bool = False) -> str:
    """Builds the user message with optional context from the database."""
    if text and text.strip():
        parts = [f"Проанализируй следующее сообщение:\n\"\"\"{text}\"\"\""]
    elif has_image:
        parts = ["Проанализируй приложенное изображение (текстовая подпись к сообщению отсутствует)."]
    else:
        parts = [f"Проанализируй следующее сообщение:\n\"\"\"{text}\"\"\""]
    if has_image:
        parts.append(IMAGE_INSTRUCTION)
    if context_block:
        parts.append(context_block)
    return "\n".join(parts)


def call_gemini_api(
    text: str,
    api_key: str,
    model: str = MODEL_NAME,
    context_block: str = "",
    image_base64: Optional[str] = None,
    image_mime: str = "image/jpeg"
) -> AnalysisResult:
    """
    Calls Google Gemini Generative Language REST API.
    Supports multimodal input (text + screenshots of fake payments/checks).
    Retries transient failures once on the selected model only.
    Raises AIAnalysisError if the call fails or API key is invalid.
    """
    if not api_key:
        raise AIAnalysisError("GEMINI_API_KEY is not configured.")

    user_msg = _build_user_message(text, context_block, has_image=bool(image_base64))

    parts: List[Dict[str, Any]] = [
        {"text": SYSTEM_PROMPT},
        {"text": user_msg}
    ]

    # Multimodal image support (Hackathon Criterion 3: Multimodality)
    if image_base64:
        parts.append({
            "inlineData": {
                "mimeType": image_mime or "image/jpeg",
                "data": image_base64
            }
        })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    last_error = "Gemini response was unavailable."
    with httpx.Client(timeout=35.0) as client:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                resp = client.post(url, json=payload, headers={"x-goog-api-key": api_key})
            except httpx.RequestError:
                last_error = f"Gemini network request failed for {model}."
            else:
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise AIAnalysisError(f"Gemini returned an incomplete response for {model}.") from exc
                    return _parse_and_validate_llm_json(raw_text, text, model, has_image=bool(image_base64))
                if resp.status_code == 429:
                    raise AIQuotaError(model, _retry_after_seconds(resp.headers.get("Retry-After")), _daily_quota_exhausted(resp))
                if resp.status_code not in {500, 502, 503, 504}:
                    raise AIAnalysisError(f"Gemini request for {model} failed with HTTP {resp.status_code}.")
                last_error = f"Gemini request for {model} failed with HTTP {resp.status_code}."
            if attempt == 0:
                time.sleep(1.0)

    raise AIAnalysisError(last_error)


def call_openai_api(
    text: str,
    api_key: str,
    base_url: str = OPENAI_BASE_URL,
    model: str = "gpt-4o-mini",
    context_block: str = "",
    image_base64: Optional[str] = None,
    image_mime: str = "image/jpeg"
) -> AnalysisResult:
    """
    Calls OpenAI or compatible endpoint (Groq, DeepSeek, OpenRouter, etc.).
    Raises AIAnalysisError if the call fails.
    """
    if not api_key:
        raise AIAnalysisError("OPENAI_API_KEY is not configured.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    user_msg = _build_user_message(text, context_block, has_image=bool(image_base64))
    user_content: Any = user_msg
    if image_base64:
        # OpenAI-compatible vision format (gpt-4o, gpt-4o-mini, OpenRouter vision models)
        user_content = [
            {"type": "text", "text": user_msg},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}},
        ]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise AIAnalysisError(f"OpenAI API error (status {resp.status_code}): {resp.text}")
            
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
            return _parse_and_validate_llm_json(raw_text, text, f"openai-{model}", has_image=bool(image_base64))
    except httpx.RequestError as e:
        raise AIAnalysisError(f"Network error calling OpenAI API: {e}")


def _parse_and_validate_llm_json(
    raw_json: str,
    original_text: str,
    model_id: str,
    has_image: bool = False,
) -> AnalysisResult:
    """
    Parses LLM JSON, enforces score/level consistency, and validates
    that every evidence string is an exact substring of the original text.
    Drops any evidence that the LLM hallucinated.
    """
    clean_json = raw_json.strip()
    if clean_json.startswith("```json"):
        clean_json = clean_json[7:]
    if clean_json.startswith("```"):
        clean_json = clean_json[3:]
    if clean_json.endswith("```"):
        clean_json = clean_json[:-3]
    clean_json = clean_json.strip()

    try:
        data = json.loads(clean_json)
    except (ValueError, TypeError) as e:
        raise AIAnalysisError("AI returned invalid JSON.") from e

    image_text = data.get("image_text") or None
    if image_text is not None and not isinstance(image_text, str):
        image_text = str(image_text)

    score = int(data.get("risk_score", 0))
    score = max(0, min(100, score))

    # Enforce level/score consistency (anti-hallucination)
    if score >= 60:
        level = RiskLevelEnum.HIGH
    elif score >= 30:
        level = RiskLevelEnum.MEDIUM
    else:
        level = RiskLevelEnum.LOW

    # Validate and filter evidence — drop hallucinated quotes
    VALID_CODES = {"UNREALISTIC_RETURN", "GUARANTEED_PROFIT", "MONEY_REQUEST", "REFERRAL", "URGENCY", "PERSONAL_TRANSFER"}
    validated_reasons: List[ReasonItem] = []
    for r in data.get("reasons", []):
        code = r.get("code", "")
        if code not in VALID_CODES:
            logger.warning(f"AI returned unknown reason code '{code}', skipping")
            continue
        raw_evidence = r.get("evidence", "")
        exact_evidence = find_exact_substring(original_text, raw_evidence) if original_text else None
        if exact_evidence:
            validated_reasons.append(ReasonItem(code=code, evidence=exact_evidence))
            continue
        image_evidence = find_exact_substring(image_text, raw_evidence) if image_text else None
        if image_evidence:
            validated_reasons.append(ReasonItem(code=code, evidence=image_evidence, source="image"))
        elif has_image and isinstance(raw_evidence, str) and raw_evidence.strip():
            # Vision model read text directly from image pixels even if image_text was omitted/abbreviated
            validated_reasons.append(ReasonItem(code=code, evidence=raw_evidence.strip(), source="image"))
        else:
            logger.warning("AI evidence was not found in the source text; dropping it.")

    # If AI gave reasons but score is LOW, bump to at least MEDIUM
    if validated_reasons and score < 30:
        score = 35
        level = RiskLevelEnum.MEDIUM

    # If AI gave no valid reasons but score is HIGH, drop to MEDIUM
    if not validated_reasons and score >= 60:
        score = 25
        level = RiskLevelEnum.LOW

    confidence = float(data.get("confidence", 0.85))
    confidence = max(0.0, min(1.0, confidence))

    return AnalysisResult(
        risk_score=score,
        risk_level=level,
        reasons=validated_reasons,
        explanation=data.get("explanation", "Анализ завершен AI-моделью."),
        confidence=confidence,
        model_version=model_id,
        image_text=image_text
    )
