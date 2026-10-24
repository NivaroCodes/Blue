import logging
from typing import Optional, Union, List, Dict, Set

from .models import MessageInput, AnalysisResult, ReasonItem, RiskLevelEnum, Alert, StatusEnum, ReviewStatusEnum
from .config import GEMINI_API_KEY, GEMINI_MODEL, LOW_RISK_THRESHOLD, HIGH_RISK_THRESHOLD, ANALYZER_VERSION
from .llm_client import call_gemini_api, AIAnalysisError
from .normalizer import detect_language, canonical_fold, find_exact_substring, normalize_text_for_search, detect_obfuscation
from .heuristics import analyze_with_heuristics, DISCLAIMERS
from .entity_extractor import extract_entities

logger = logging.getLogger(__name__)


def analyze_message(
    message: Union[MessageInput, str],
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    context_block: str = "",
    image_base64: Optional[str] = None,
    image_mime: str = "image/jpeg",
) -> AnalysisResult:
    """
    Unified proprietary risk engine pipeline:
    1. Input ingestion: preserves original text verbatim.
    2. Normalization: language detection, canonical folding (homoglyphs/leetspeak).
    3. Deterministic heuristics: rule-based pyramid indicator detection and disclaimer check.
    4. Entity extraction: cards, phones, crypto wallets, invite links.
    5. Context & graph enrichment: factual database signals from context_block.
    6. Google Gemini analysis: single configured model (default gemini-3.5-flash-lite).
    7. Hybrid Risk Engine: synthesizes signals, avoids double-counting, enforces thresholds.
    8. Anti-hallucination validation: strict exact substring match of all evidence fragments.
    """
    text = message.text if isinstance(message, MessageInput) else str(message)
    img = message.image_base64 if isinstance(message, MessageInput) else image_base64

    if provider is not None and provider.lower() != "gemini":
        raise AIAnalysisError(
            f"Неподдерживаемый AI-провайдер: '{provider}'. "
            "Google Gemini является единственным поддерживаемым LLM-провайдером проекта SafeNet KZ."
        )

    active_key = api_key if api_key is not None else GEMINI_API_KEY
    if not active_key:
        raise AIAnalysisError(
            "GEMINI_API_KEY is not configured. Set GEMINI_API_KEY in your local .env or environment. "
            "SafeNet KZ requires an authorized Google AI Studio Gemini API key."
        )

    # 1. Normalization & Pre-analysis
    lang = detect_language(text)
    is_obfuscated = detect_obfuscation(text)

    # 2. Deterministic checks (Heuristics & Disclaimers)
    heuristic_result = analyze_with_heuristics(text) if text else None

    # 3. Entity Extraction
    extracted_entities = extract_entities(text) if text else []

    # 4. Enriched Context Block for Gemini
    pre_signals = []
    if is_obfuscated:
        pre_signals.append("Обнаружена возможная обфускация символов (замена букв цифрами / гомоглифы).")
    if extracted_entities:
        ent_desc = ", ".join(f"{e['type']}: {e.get('display', e['value'])}" for e in extracted_entities[:5])
        pre_signals.append(f"Извлечённые сущности: {ent_desc}")
    if heuristic_result and heuristic_result.reasons:
        heur_codes = ", ".join(r.code for r in heuristic_result.reasons)
        pre_signals.append(f"Предварительные детерминированные сигналы: {heur_codes}")

    enriched_context_parts = []
    if pre_signals:
        enriched_context_parts.append("РЕЗУЛЬТАТЫ ПРЕДВАРИТЕЛЬНОГО АНАЛИЗА АЛГОРИТМА:\n" + "\n".join(f"• {s}" for s in pre_signals))
    if context_block:
        enriched_context_parts.append(context_block)
    full_context_block = "\n\n".join(enriched_context_parts)

    # 5. Gemini Analysis
    target_model = model or GEMINI_MODEL
    gemini_result = call_gemini_api(
        text=text,
        api_key=active_key,
        model=target_model,
        context_block=full_context_block,
        image_base64=img,
        image_mime=image_mime,
    )

    # 6. Risk Engine Synthesis: combine Gemini signals with proprietary rules
    final_result = synthesize_risk(
        original_text=text,
        gemini_result=gemini_result,
        heuristic_result=heuristic_result,
        lang=lang,
        is_obfuscated=is_obfuscated,
        target_model=target_model,
    )

    return final_result


def synthesize_risk(
    original_text: str,
    gemini_result: AnalysisResult,
    heuristic_result: Optional[AnalysisResult],
    lang: str,
    is_obfuscated: bool,
    target_model: str,
) -> AnalysisResult:
    """
    Centralized risk engine that combines deterministic rule signals with Gemini output.
    - Prevents double-counting: deduplicates reason items by code.
    - Enforces exact substring matching for every evidence snippet.
    - Applies educational disclaimer suppression (protects against false positives).
    - Preserves high recall on classical pyramid patterns.
    """
    # Merge and deduplicate reasons by code
    reasons_by_code: Dict[str, ReasonItem] = {}

    # First add validated Gemini reasons
    for r in gemini_result.reasons:
        exact = find_exact_substring(original_text, r.evidence) if original_text else None
        if exact:
            reasons_by_code[r.code] = ReasonItem(code=r.code, evidence=exact, source=r.source)
        elif r.source == "image" and r.evidence:
            reasons_by_code[r.code] = r

    # Then integrate deterministic heuristic reasons without duplication
    if heuristic_result:
        for hr in heuristic_result.reasons:
            if hr.code not in reasons_by_code:
                exact = find_exact_substring(original_text, hr.evidence)
                if exact:
                    reasons_by_code[hr.code] = ReasonItem(code=hr.code, evidence=exact, source="text")

    final_reasons = list(reasons_by_code.values())
    codes = set(reasons_by_code.keys())

    # Base score from Gemini fused with verified deterministic heuristics
    gemini_score = gemini_result.risk_score
    heur_score = heuristic_result.risk_score if heuristic_result else 0
    score = max(gemini_score, heur_score if final_reasons else 0)

    # Check for educational / benign disclaimers in original text
    has_disclaimer = False
    if original_text:
        import re
        has_disclaimer = any(re.search(pat, original_text, re.IGNORECASE) for pat in DISCLAIMERS)

    # Contextual check for consumer promotions and courses
    is_consumer_promo = bool(original_text and re.search(r"\b(?:yandex\s*go|такси|киім\s+дүкен|поездк[а-я]|скидк[а-я]*\s+на|жеңілдік|kaspi\s*red)\b", original_text, re.IGNORECASE))
    is_course = bool(original_text and re.search(r"\b(?:обучени[ея]|курс[а-я]*|мамандық|оқу\s+мерзімі|выпускник[а-я]*)\b", original_text, re.IGNORECASE))

    # Critical pyramid / fraud indicators (overt scam)
    is_critical_pyramid = (
        ("UNREALISTIC_RETURN" in codes and bool(codes & {"MONEY_REQUEST", "PERSONAL_TRANSFER", "REFERRAL"}))
        or ("PERSONAL_TRANSFER" in codes and bool(codes & {"MONEY_REQUEST", "GUARANTEED_PROFIT"}))
        or (gemini_result.risk_level == RiskLevelEnum.HIGH and len(final_reasons) >= 1)
    )

    if is_consumer_promo and not is_critical_pyramid and "PERSONAL_TRANSFER" not in codes:
        # Benign retail / ride-sharing promos: suppress to LOW and clear non-scam reasons
        score = min(score, 15)
        final_reasons = []
    elif is_course and score >= 60 and "PERSONAL_TRANSFER" not in codes:
        # Training / skills courses with high income prospect: classify as MEDIUM, not HIGH
        score = 45
    elif has_disclaimer:
        if is_critical_pyramid:
            # Pro-forma / fake disclaimer on overt pyramid: scam cannot be sanitized, retain HIGH
            score = max(score, 75)
        elif final_reasons:
            # Ambiguous grey-zone signals with disclaimer: moderate to MEDIUM, retain reasons
            score = min(45, max(35, score))
        else:
            # Legitimate investment/educational discussion with disclaimers: suppress score
            score = min(score, 20)
            final_reasons = []
    else:
        if is_critical_pyramid:
            score = max(score, 75)

    # Bound score [0, 100]
    score = max(0, min(100, score))

    # Consistency mapping
    if score >= HIGH_RISK_THRESHOLD:
        level = RiskLevelEnum.HIGH
    elif score >= LOW_RISK_THRESHOLD:
        level = RiskLevelEnum.MEDIUM
    else:
        level = RiskLevelEnum.LOW

    # Build confidence
    confidence = gemini_result.confidence
    if final_reasons and len(final_reasons) >= 2:
        confidence = max(confidence, 0.90)

    explanation = gemini_result.explanation
    if not explanation or len(explanation.strip()) < 10:
        explanation = "Анализ сообщения завершен модулем выявления финансовых рисков SafeNet KZ."

    model_ver = gemini_result.model_version or (target_model if target_model.startswith("gemini-") else f"gemini-{target_model}")

    return AnalysisResult(
        risk_score=score,
        risk_level=level,
        reasons=final_reasons,
        explanation=explanation,
        confidence=confidence,
        model_version=model_ver,
        image_text=gemini_result.image_text,
    )


def create_alert_from_analysis(message: MessageInput, analysis: AnalysisResult) -> Alert:
    """
    Constructs a full Alert model ready for the frontend /api/alerts endpoints.
    """
    from .db.models import format_timestamp, make_message_pk, utc_now
    pk = make_message_pk(message.platform.value, message.chat_id, message.message_id)
    iso_timestamp = format_timestamp(message.timestamp) or format_timestamp(utc_now())
    return Alert(
        id=f"alert_{pk}",
        platform=message.platform,
        chat_id=message.chat_id,
        chat_name=message.chat_name,
        message_id=message.message_id,
        sender_hash=message.sender_hash,
        text=message.text,
        timestamp=iso_timestamp,
        status=StatusEnum.PROCESSED,
        risk_score=analysis.risk_score,
        risk_level=analysis.risk_level,
        reasons=analysis.reasons,
        explanation=analysis.explanation,
        confidence=analysis.confidence,
        review_status=ReviewStatusEnum.NEW,
        reviewer_note="",
        model_version=analysis.model_version,
    )
