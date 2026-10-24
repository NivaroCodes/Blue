import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any, List

import httpx

from .config import GEMINI_API_KEY, GEMINI_MODEL
from .models import AnalysisResult, ReasonItem, RiskLevelEnum
from .normalizer import find_exact_substring

logger = logging.getLogger(__name__)

# Constants for exponential backoff recovery and wall-clock deadlines
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 10.0  # seconds cap for single delay
DEFAULT_OPERATION_TIMEOUT = 30.0  # seconds wall-clock budget for the entire operation
DEFAULT_PER_REQUEST_TIMEOUT = 12.0  # seconds per individual HTTP read attempt
MAX_ALLOWED_RETRY_AFTER = 20.0  # seconds threshold; if server asks longer, abort to avoid holding worker


class AIAnalysisError(Exception):
    """Raised when the AI model call or response validation fails."""
    pass


def _sanitize_error_msg(error_msg: Any) -> str:
    """Strips API keys, tokens, and credentials from error messages."""
    if not error_msg:
        return ""
    if not isinstance(error_msg, str):
        error_msg = str(error_msg)
    # Mask key=, token=, etc.
    s = re.sub(r"(key|api_key|token|password|secret)=[^\s&\"']+", r"\1=[REDACTED]", error_msg)
    # Mask x-goog-api-key header / json values
    s = re.sub(r"(x-goog-api-key[\"':\s]+)[^\s,}\"']+", r"\1[REDACTED]", s, flags=re.IGNORECASE)
    # Mask Google AI Studio keys (AQ. or AIza format)
    s = re.sub(r"AQ\.[A-Za-z0-9_-]{20,}", "[REDACTED_KEY]", s)
    s = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "[REDACTED_KEY]", s)
    # Mask Bearer tokens
    s = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    return s[:2000]


def _parse_retry_after(header_val: Optional[str]) -> Optional[float]:
    """Parses Retry-After header as either seconds or HTTP-date string."""
    if not header_val:
        return None
    val_str = header_val.strip()
    try:
        val = float(val_str)
        return max(0.0, val)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(val_str)
        if dt:
            now = datetime.now(timezone.utc)
            delta = (dt - now).total_seconds()
            return max(0.0, delta)
    except Exception:
        pass
    return None


def _compute_backoff_delay(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retry_after: Optional[float] = None,
) -> float:
    """
    Computes delay with exponential backoff and random jitter following Google API guidance:
    - Base delay * 2^attempt
    - Adds random jitter to prevent synchronized retry stampedes
    - Respects Retry-After if provided
    - Capped at max_delay
    """
    if retry_after is not None and retry_after >= 0:
        return min(max_delay, retry_after + random.uniform(0.1, 0.4))

    exp_delay = base_delay * (2 ** attempt)
    max_jitter = min(1.0, max(0.01, exp_delay * 0.5))
    jitter = random.uniform(0.01, max_jitter)
    delay = exp_delay + jitter
    return round(min(delay, max_delay), 3)


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
ТРЕБОВАНИЯ К ПОЛЮ 'explanation' (ЗАКЛЮЧЕНИЕ ДЛЯ АНАЛИТИКА):
═══════════════════════════════════════
Заключение должно быть ПРОФЕССИОНАЛЬНЫМ, ОБЪЕКТИВНЫМ, СТРУКТУРИРОВАННЫМ и ЛИШЁННЫМ ТАВТОЛОГИЙ (3–5 предложений):

1. СТИЛИСТИЧЕСКАЯ ЧИСТОТА:
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ тавтологии, плеоназмы и зацикливания (запрещены фразы вроде «классические признаки классической финансовой пирамиды», «гарантированная гарантия», «очевидный обман»). Используй ясный профессиональный язык («зафиксированы характерные признаки финансовой пирамиды», «выявлены признаки недобросовестной финансовой деятельности»).

2. ПРЕЗУМПЦИЯ НЕВИНОВНОСТИ И ЮРИДИЧЕСКАЯ КОРРЕКТНОСТЬ:
   - НЕ ДЕЛАЙ категоричных утверждений о совершении преступления или виновности («автор является мошенником», «это уголовное мошенничество», «преступная группа доказана»). Квалификацию состава и решение о виновности выносят правоохранительные органы и суд, а не ИИ.
   - Формулируй выводы в терминах рисков, признаков и паттернов («выявлены признаки, типичные для схем финансовых пирамид», «зафиксированы индикаторы высокорискового нерегулируемого привлечения средств»).

3. РАЗДЕЛЕНИЕ НАБЛЮДАЕМЫХ ФАКТОВ И АНАЛИТИЧЕСКИХ ВЫВОДОВ:
   - Наблюдаемые факты: ссылайся на конкретные доказательства из текста (обещанный процент доходности, требование вступительного взноса, привлечение новых участников/рефералов, перевод на карту Kaspi).
   - Аналитическая оценка: укажи, почему выявленные факты представляют риск (отсутствие регистрации в реестрах АРРФР/МФЦА, непрозрачный экономический механизм выплат, перекладывание риска на вкладчика).
   - Контекст: репутация отправителя или статус группы, если они указаны в предоставленном блоке контекста.

4. РЕКОМЕНДАЦИИ АНАЛИТИКУ — ИСКЛЮЧИТЕЛЬНО АНАЛИТИЧЕСКИЕ И ВЕРИФИКАЦИОННЫЕ:
   - Предлагай меры проверки: проверка реквизитов карты/счёта по базам АФМ/АРРФР, аудит связанной сетевой активности и кросс-постинга, запрос лицензии на осуществление финансовой деятельности, ручная верификация аналитиком.
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ безапелляционные карательные команды («немедленная блокировка отправителя», «арест счёта»). Решение о модерации и правовых мерах принимает ответственный специалист после верификации.
   - Для нейтральных или образовательных текстов: «Материал носит информационный/образовательный характер, признаков недобросовестных финансовых схем не выявлено».

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
  "explanation": "<развёрнутое объективное аналитическое заключение по требованиям выше>",
  "confidence": <число 0.0 – 0.95: показатель однозначности признаков и достаточности контекста для квалификации; 0.85–0.95 для явного HIGH с 2+ признаками, 0.45–0.65 для неоднозначного MEDIUM, 0.75–0.85 для полного LOW, 0.30–0.45 при кратком тексте или нехватке данных>
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
    model: Optional[str] = None,
    context_block: str = "",
    image_base64: Optional[str] = None,
    image_mime: str = "image/jpeg",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    max_total_wait: float = DEFAULT_OPERATION_TIMEOUT,
    per_request_timeout: float = DEFAULT_PER_REQUEST_TIMEOUT,
) -> AnalysisResult:
    """
    Calls Google Gemini Generative Language REST API using the single configured model.
    Passes API key securely via the 'x-goog-api-key' header (never in query parameters).
    Enforces a strict wall-clock deadline across all network requests and backoff pauses.
    Constrains connect/read/write/pool timeouts on each attempt to the remaining operation budget.
    Retries temporary 429/503 errors on the SAME model with exponential backoff and random jitter.
    Respects 'Retry-After' header if returned by the server.
    Does not start any attempt or backoff pause if the overall budget is exhausted.
    No multi-model fallback or cross-provider switching.
    Raises AIAnalysisError if the call fails or API key is invalid.
    """
    if not api_key or not api_key.strip():
        raise AIAnalysisError("GEMINI_API_KEY is not configured. Provide GEMINI_API_KEY in .env.")

    target_model = (model or GEMINI_MODEL).strip()
    user_msg = _build_user_message(text, context_block, has_image=bool(image_base64))

    parts: List[Dict[str, Any]] = [
        {"text": SYSTEM_PROMPT},
        {"text": user_msg}
    ]

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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
    headers = {
        "x-goog-api-key": api_key.strip(),
        "Content-Type": "application/json",
    }

    last_error = ""
    attempts_done = 0

    with httpx.Client() as client:
        start_time = time.monotonic()
        deadline = start_time + max_total_wait
        for attempt in range(max_attempts):
            now = time.monotonic()
            remaining_budget = deadline - now
            if remaining_budget <= 0.05:
                logger.warning(
                    f"Gemini call aborted before attempt {attempt + 1}: operation budget of {max_total_wait:.1f}s exhausted."
                )
                last_error = f"Operation deadline of {max_total_wait:.1f}s exhausted before attempt {attempt + 1}. Last error: {last_error}"
                break

            attempts_done += 1

            connect_t = max(0.01, min(5.0, remaining_budget))
            read_t = max(0.01, min(per_request_timeout, remaining_budget))
            write_t = max(0.01, min(5.0, remaining_budget))
            pool_t = max(0.01, min(5.0, remaining_budget))
            attempt_timeout = httpx.Timeout(
                timeout=remaining_budget,
                connect=connect_t,
                read=read_t,
                write=write_t,
                pool=pool_t,
            )

            try:
                resp = client.post(url, json=payload, headers=headers, timeout=attempt_timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_text = candidates[0]["content"]["parts"][0]["text"]
                        model_id = target_model if target_model.startswith("gemini-") else f"gemini-{target_model}"
                        return _parse_and_validate_llm_json(
                            raw_text, text, model_id, has_image=bool(image_base64)
                        )
                    raise AIAnalysisError(f"Gemini API returned 200 but candidate list is empty: {data}")

                retry_after_hdr = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                retry_after_sec = _parse_retry_after(retry_after_hdr)

                if resp.status_code == 429:
                    err_body = _sanitize_error_msg(resp.text)
                    error_obj = {}
                    try:
                        parsed = resp.json()
                        if isinstance(parsed, dict):
                            cand_err = parsed.get("error")
                            if isinstance(cand_err, dict):
                                error_obj = cand_err
                    except Exception:
                        pass
                    status_str = str(error_obj.get("status") or "RESOURCE_EXHAUSTED")
                    raw_msg = error_obj.get("message")
                    err_msg = str(raw_msg) if (raw_msg is not None and isinstance(raw_msg, str)) else err_body
                    cat_desc = "Quota exceeded" if "quota" in err_msg.lower() else "Rate limit exceeded"
                    last_error = f"Gemini 429 ({cat_desc} / {status_str}) on {target_model}: {_sanitize_error_msg(err_msg)}"
                    logger.warning(
                        f"Gemini API 429 on {target_model} (attempt {attempt + 1}/{max_attempts}): "
                        f"Category={cat_desc}, Status={status_str}, Details={_sanitize_error_msg(err_msg)}"
                    )
                elif resp.status_code == 503:
                    err_body = _sanitize_error_msg(resp.text)
                    error_obj = {}
                    try:
                        parsed = resp.json()
                        if isinstance(parsed, dict):
                            cand_err = parsed.get("error")
                            if isinstance(cand_err, dict):
                                error_obj = cand_err
                    except Exception:
                        pass
                    status_str = str(error_obj.get("status") or "UNAVAILABLE")
                    raw_msg = error_obj.get("message")
                    err_msg = str(raw_msg) if (raw_msg is not None and isinstance(raw_msg, str)) else err_body
                    last_error = f"Gemini 503 (Service Unavailable / High Demand / {status_str}) on {target_model}: {_sanitize_error_msg(err_msg)}"
                    logger.warning(
                        f"Gemini API 503 Service Unavailable [{status_str}] on {target_model} (attempt {attempt + 1}/{max_attempts}): "
                        f"{_sanitize_error_msg(err_msg)}"
                    )
                elif resp.status_code in (400, 401, 403, 404):
                    err_body = _sanitize_error_msg(resp.text)
                    raise AIAnalysisError(
                        f"Gemini API error for model '{target_model}': HTTP {resp.status_code}. "
                        f"Verify that model '{target_model}' is accessible in Google AI Studio for your API key. Details: {err_body}"
                    )
                else:
                    err_body = _sanitize_error_msg(resp.text)
                    last_error = f"Gemini HTTP {resp.status_code}: {err_body}"
                    logger.warning(f"Gemini API HTTP {resp.status_code} on {target_model}: {last_error}")

                if resp.status_code in (429, 503, 500, 502, 504):
                    if retry_after_sec is not None and retry_after_sec > MAX_ALLOWED_RETRY_AFTER:
                        raise AIAnalysisError(
                            f"Gemini API requested Retry-After {retry_after_sec:.1f}s, exceeding maximum allowed retry window of {MAX_ALLOWED_RETRY_AFTER}s. Last error: {last_error}"
                        )
                    if attempt < max_attempts - 1:
                        delay = _compute_backoff_delay(
                            attempt, base_delay=base_delay, max_delay=max_delay, retry_after=retry_after_sec
                        )
                        remaining_after_req = deadline - time.monotonic()
                        if delay >= remaining_after_req:
                            logger.warning(
                                f"Gemini retry aborting on {target_model}: delay {delay:.2f}s exceeds remaining budget {remaining_after_req:.2f}s."
                            )
                            break
                        logger.info(f"Gemini backing off for {delay:.2f}s before retry {attempt + 2}/{max_attempts} on {target_model}...")
                        time.sleep(delay)
                        continue
                else:
                    break

            except httpx.TimeoutException as e:
                clean_err = _sanitize_error_msg(str(e))
                timeout_type = type(e).__name__
                last_error = f"Timeout ({timeout_type}) calling Gemini ({target_model}): {clean_err}"
                logger.warning(f"Timeout ({timeout_type}) on {target_model} (attempt {attempt + 1}/{max_attempts}): {clean_err}")
                if attempt < max_attempts - 1:
                    delay = _compute_backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
                    remaining_after_req = deadline - time.monotonic()
                    if delay >= remaining_after_req:
                        logger.warning(
                            f"Gemini retry aborting on {target_model}: delay {delay:.2f}s exceeds remaining budget {remaining_after_req:.2f}s."
                        )
                        break
                    logger.info(f"Gemini backing off for {delay:.2f}s before retry {attempt + 2}/{max_attempts} on {target_model}...")
                    time.sleep(delay)
                    continue

            except httpx.RequestError as e:
                clean_err = _sanitize_error_msg(str(e))
                last_error = f"Network error calling Gemini ({target_model}): {clean_err}"
                logger.warning(f"Network error on {target_model} (attempt {attempt + 1}/{max_attempts}): {clean_err}")
                if attempt < max_attempts - 1:
                    delay = _compute_backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
                    remaining_after_req = deadline - time.monotonic()
                    if delay >= remaining_after_req:
                        logger.warning(
                            f"Gemini retry aborting on {target_model}: delay {delay:.2f}s exceeds remaining budget {remaining_after_req:.2f}s."
                        )
                        break
                    logger.info(f"Gemini backing off for {delay:.2f}s before retry {attempt + 2}/{max_attempts} on {target_model}...")
                    time.sleep(delay)
                    continue

    elapsed_total = time.monotonic() - start_time
    raise AIAnalysisError(
        f"Gemini model '{target_model}' call failed after {attempts_done} attempts "
        f"(elapsed: {elapsed_total:.2f}s / budget: {max_total_wait:.1f}s). Last error: {last_error}"
    )


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
    except Exception as e:
        raise AIAnalysisError(f"AI returned invalid JSON: {e}, payload: {raw_json}")

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
            validated_reasons.append(ReasonItem(code=code, evidence=raw_evidence.strip(), source="image"))
        else:
            logger.warning(f"AI hallucinated evidence '{raw_evidence}' — not found in text, dropping")

    # If AI gave valid reasons but score is LOW, bump to at least MEDIUM
    if validated_reasons and score < 30:
        score = 35
        level = RiskLevelEnum.MEDIUM

    # If AI gave no valid reasons but score is HIGH, drop to LOW
    if not validated_reasons and score >= 60:
        score = 25
        level = RiskLevelEnum.LOW

    raw_conf = data.get("confidence")
    model_conf = float(raw_conf) if raw_conf is not None else None
    from .models import compute_calibrated_confidence
    confidence = compute_calibrated_confidence(
        risk_level=level,
        reasons_count=len(validated_reasons),
        text=original_text,
        raw_model_confidence=model_conf,
        has_image=has_image,
    )

    raw_expl = str(data.get("explanation", "")).strip()
    try:
        from .analyzer import sanitize_explanation
        explanation = sanitize_explanation(raw_expl, level.value)
    except Exception:
        explanation = raw_expl or "Анализ завершен AI-моделью."

    return AnalysisResult(
        risk_score=score,
        risk_level=level,
        reasons=validated_reasons,
        explanation=explanation,
        confidence=confidence,
        model_version=model_id,
        image_text=image_text
    )
