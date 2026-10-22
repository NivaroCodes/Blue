import json
import logging
import time
import httpx
from typing import Optional, Dict, Any, List

from .config import GEMINI_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from .models import AnalysisResult, ReasonItem, RiskLevelEnum
from .normalizer import find_exact_substring

logger = logging.getLogger(__name__)


class AIAnalysisError(Exception):
    """Raised when the AI model call or response validation fails."""
    pass


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

3. MONEY_REQUEST — требование денег / взноса:
   • «Вложи 5000 тг», «жарна 10000 теңге», «входной билет», «депозит»
   • Переводы для «активации счёта», «вступления в клуб», подписки
   • Скрытые формулировки: «узнай сумму у куратора», «условия в ЛС»

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
СЛОЖНЫЕ ВИДЫ СКАМА (распознавай их тоже):
═══════════════════════════════════════

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
- История отправителя: сколько раз он уже был отмечен как HIGH/MEDIUM риск
- История группы/чата: сколько скамов уже найдено в этом чате

Если отправитель ПОВТОРНО шлёт подозрительные сообщения (2+ раза HIGH) — это усиливает риск текущего сообщения.
Если в группе/чате МНОГО скамов — даже умеренно подозрительное сообщение заслуживает повышенной оценки.

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


def _build_user_message(text: str, context_block: str = "") -> str:
    """Builds the user message with optional context from the database."""
    parts = [f"Проанализируй следующее сообщение:\n\"\"\"{text}\"\"\""]
    if context_block:
        parts.append(context_block)
    return "\n".join(parts)


def call_gemini_api(
    text: str,
    api_key: str,
    model: str = "gemini-3-flash-preview",
    context_block: str = "",
    image_base64: Optional[str] = None
) -> AnalysisResult:
    """
    Calls Google Gemini Generative Language REST API.
    Supports multimodal input (text + screenshots of fake payments/checks).
    Automatically retries on temporary 503 spikes across model variants.
    Raises AIAnalysisError if the call fails or API key is invalid.
    """
    if not api_key:
        raise AIAnalysisError("GEMINI_API_KEY is not configured.")

    fallback_models = [model, "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.8-flash"]
    # De-duplicate preserving order
    seen = set()
    candidate_models = [m for m in fallback_models if not (m in seen or seen.add(m))]

    user_msg = _build_user_message(text, context_block)

    parts: List[Dict[str, Any]] = [
        {"text": SYSTEM_PROMPT},
        {"text": user_msg}
    ]

    # Multimodal image support (Hackathon Criterion 3: Multimodality)
    if image_base64:
        parts.append({
            "inlineData": {
                "mimeType": "image/jpeg",
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

    last_error = ""
    with httpx.Client(timeout=35.0) as client:
        for m in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            for attempt in range(2):
                try:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            raw_text = candidates[0]["content"]["parts"][0]["text"]
                            return _parse_and_validate_llm_json(raw_text, text, f"gemini-{m}")
                    elif resp.status_code == 429:
                        last_error = f"Gemini status 429 (Rate limit) on {m}"
                        time.sleep(3.0)
                        continue
                    elif resp.status_code == 503:
                        last_error = f"Gemini status 503 on {m}"
                        time.sleep(2.0)
                        continue
                    else:
                        last_error = f"Gemini status {resp.status_code}: {resp.text}"
                        break
                except httpx.RequestError as e:
                    last_error = f"Network error calling Gemini ({m}): {e}"
                    time.sleep(1.5)
                    continue

    raise AIAnalysisError(f"All Gemini model candidates failed. Last error: {last_error}")


def call_openai_api(text: str, api_key: str, base_url: str = OPENAI_BASE_URL, model: str = "gpt-4o-mini", context_block: str = "") -> AnalysisResult:
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
    user_msg = _build_user_message(text, context_block)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
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
            return _parse_and_validate_llm_json(raw_text, text, f"openai-{model}")
    except httpx.RequestError as e:
        raise AIAnalysisError(f"Network error calling OpenAI API: {e}")


def _parse_and_validate_llm_json(raw_json: str, original_text: str, model_id: str) -> AnalysisResult:
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
    except Exception as e:
        raise AIAnalysisError(f"AI returned invalid JSON: {e}, payload: {raw_json}")

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
        exact_evidence = find_exact_substring(original_text, raw_evidence)
        if exact_evidence:
            validated_reasons.append(ReasonItem(code=code, evidence=exact_evidence))
        else:
            logger.warning(f"AI hallucinated evidence '{raw_evidence}' — not found in text, dropping")

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
        model_version=model_id
    )
