import logging
from typing import Optional, Union

from .models import MessageInput, AnalysisResult, Alert, StatusEnum, ReviewStatusEnum
from .config import GEMINI_API_KEY, OPENAI_API_KEY, AI_PROVIDER, MODEL_NAME
from .llm_client import call_gemini_api, call_openai_api, AIAnalysisError

logger = logging.getLogger(__name__)


def analyze_message(
    message: Union[MessageInput, str],
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    context_block: str = "",
    image_base64: Optional[str] = None
) -> AnalysisResult:
    """
    Main entrypoint for analyzing a message via AI (LLM API).
    
    Supports:
    - Text context
    - context_block: sender reputation and chat risk profile from DB
    - image_base64: multimodal analysis of payment screenshots, fake receipts, OCR
    
    Raises AIAnalysisError if the AI call fails or no API key is provided.
    """
    text = message.text if isinstance(message, MessageInput) else str(message)
    img = message.image_base64 if isinstance(message, MessageInput) else image_base64
    active_provider = (provider or AI_PROVIDER).lower()
    if api_key is not None:
        active_key = api_key
    else:
        active_key = GEMINI_API_KEY if active_provider == "gemini" else OPENAI_API_KEY

    if not active_key:
        raise AIAnalysisError(
            f"API-ключ для провайдера '{active_provider}' не найден. "
            "Укажите GEMINI_API_KEY или OPENAI_API_KEY в .env файле."
        )

    if active_provider == "gemini":
        return call_gemini_api(text, api_key=active_key, model=MODEL_NAME, context_block=context_block, image_base64=img)
    elif active_provider in ("openai", "groq", "openrouter", "deepseek"):
        return call_openai_api(text, api_key=active_key, model=MODEL_NAME, context_block=context_block)
    else:
        raise AIAnalysisError(f"Неизвестный AI-провайдер: '{active_provider}'")


def create_alert_from_analysis(message: MessageInput, analysis: AnalysisResult) -> Alert:
    """
    Constructs a full Alert model ready for the frontend /api/alerts endpoints.
    """
    iso_timestamp = message.timestamp.isoformat() if message.timestamp else ""
    return Alert(
        id=f"alert_{message.message_id}",
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
        model_version=analysis.model_version
    )
