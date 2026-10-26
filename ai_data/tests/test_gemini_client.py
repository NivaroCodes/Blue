"""Synthetic contract tests for the selected Gemini model and worker limits."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pytest

from ai_data import config, worker
from ai_data.db.models import AnalysisRecord, MessageRecord
from ai_data.llm_client import AIAnalysisError, AIQuotaError, call_gemini_api
from ai_data.tests.test_db_helper import get_clean_test_session


MODEL = "gemini-3.5-flash-lite"
HTTPX_CLIENT = httpx.Client


def response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def mocked_client(monkeypatch, handler):
    client = HTTPX_CLIENT(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ai_data.llm_client.httpx.Client", lambda **_kwargs: client)


def test_configured_model_and_russian_risk_contract(monkeypatch):
    assert config.MODEL_NAME == MODEL
    requests = []

    def handler(request):
        requests.append(request)
        return response('{"risk_score": 82, "reasons": [{"code": "MONEY_REQUEST", "evidence": "Вложи 5000 тг"}], "explanation": "Подозрительный запрос денег.", "confidence": 0.91}')

    mocked_client(monkeypatch, handler)
    result = call_gemini_api("Вложи 5000 тг и получи прибыль", api_key="synthetic-test-key", model=MODEL)
    assert result.risk_score == 82 and result.risk_level.value == "HIGH"
    assert result.reasons[0].evidence == "Вложи 5000 тг"
    assert result.model_version == MODEL
    assert len(requests) == 1
    assert MODEL in str(requests[0].url) and not requests[0].url.query
    assert requests[0].headers["x-goog-api-key"] == "synthetic-test-key"


def test_harmless_kazakh_and_hallucinated_evidence(monkeypatch):
    mocked_client(monkeypatch, lambda _request: response('{"risk_score": 0, "reasons": [], "explanation": "Кәдімгі ауа райы туралы хабар.", "confidence": 0.8}'))
    safe = call_gemini_api("Бүгін ауа райы жақсы", api_key="synthetic-test-key", model=MODEL)
    assert safe.risk_level.value == "LOW" and safe.reasons == []

    mocked_client(monkeypatch, lambda _request: response('{"risk_score": 90, "reasons": [{"code": "MONEY_REQUEST", "evidence": "ойдан шығарылған төлем"}], "explanation": "Тексеру керек.", "confidence": 0.7}'))
    unsupported = call_gemini_api("Акша бересің бе?", api_key="synthetic-test-key", model=MODEL)
    assert unsupported.reasons == [] and unsupported.risk_level.value == "LOW"


def test_multimodal_payload_and_image_evidence(monkeypatch):
    def handler(request):
        parts = json.loads(request.content)["contents"][0]["parts"]
        assert parts[-1] == {"inlineData": {"mimeType": "image/png", "data": "c3ludGhldGlj"}}
        return response('{"risk_score": 88, "reasons": [{"code": "UNREALISTIC_RETURN", "evidence": "200% за день"}], "image_text": "200% за день", "explanation": "Реклама с нереалистичной доходностью.", "confidence": 0.9}')

    mocked_client(monkeypatch, handler)
    result = call_gemini_api("Скриншот", api_key="synthetic-test-key", model=MODEL, image_base64="c3ludGhldGlj", image_mime="image/png")
    assert result.reasons[0].source == "image" and result.image_text == "200% за день"


def test_quota_error_respects_retry_after_and_never_switches_model(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"error": {"message": "GenerateRequestsPerDay quota exhausted"}})

    mocked_client(monkeypatch, handler)
    with pytest.raises(AIQuotaError) as error:
        call_gemini_api("[SYNTHETIC] тексеру", api_key="synthetic-test-key", model=MODEL)
    assert error.value.daily and error.value.retry_after_seconds == 120
    assert len(calls) == 1 and MODEL in str(calls[0])


def test_transient_503_retries_once_on_same_model(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) == 1:
            return httpx.Response(503)
        return response('{"risk_score": 5, "reasons": [], "explanation": "Тест.", "confidence": 0.8}')

    mocked_client(monkeypatch, handler)
    with patch("ai_data.llm_client.time.sleep") as sleep:
        result = call_gemini_api("Сәлем", api_key="synthetic-test-key", model=MODEL)
    assert result.risk_score == 5 and len(calls) == 2
    assert all(MODEL in str(url) for url in calls)
    sleep.assert_called_once()
    assert 1.0 <= sleep.call_args.args[0] <= 1.5


def test_invalid_json_does_not_expose_model_payload(monkeypatch):
    mocked_client(monkeypatch, lambda _request: response("PRIVATE_SYNTHETIC_PAYLOAD"))
    with pytest.raises(AIAnalysisError) as error:
        call_gemini_api("[SYNTHETIC]", api_key="synthetic-test-key", model=MODEL)
    assert "PRIVATE_SYNTHETIC_PAYLOAD" not in str(error.value)


def pending(message_id: str) -> MessageRecord:
    return MessageRecord(
        id=message_id, platform="telegram", chat_id="synthetic", chat_name="Synthetic",
        message_id=message_id, sender_hash="synthetic_sender", text="[SYNTHETIC] Сәлем",
        timestamp=datetime.now(timezone.utc), status="PENDING",
    )


def test_quota_pauses_queue_without_firing_more_requests(monkeypatch):
    monkeypatch.setattr(worker, "_quota_block_until", 0.0)
    with get_clean_test_session() as session:
        session.add_all([pending("quota-1"), pending("quota-2")])
        session.commit()
        with patch("ai_data.worker._analyse_and_store", side_effect=AIQuotaError(MODEL, 120, False)) as analyze:
            assert worker.process_pending_messages(session, limit=2, api_key="synthetic-test-key", throttle_seconds=0) == 0
            assert analyze.call_count == 1
            assert worker.process_pending_messages(session, limit=2, api_key="synthetic-test-key", throttle_seconds=0) == 0
        assert session.query(MessageRecord).filter_by(status="ERROR").count() == 1
        assert session.query(MessageRecord).filter_by(status="PENDING").count() == 1


def test_valid_cached_analysis_skips_duplicate_model_call(monkeypatch):
    monkeypatch.setattr(worker, "_quota_block_until", 0.0)
    with get_clean_test_session() as session:
        session.add(pending("cached-1"))
        session.add(AnalysisRecord(
            id="analysis_cached-1", message_id="cached-1", risk_score=5, risk_level="LOW",
            reasons_json="[]", explanation="Synthetic cached result", confidence=0.8,
            model_version=MODEL,
        ))
        session.commit()
        with patch("ai_data.worker._analyse_and_store") as analyze:
            assert worker.process_pending_messages(session, limit=1, api_key="synthetic-test-key", throttle_seconds=0) == 1
            analyze.assert_not_called()
        assert session.get(MessageRecord, "cached-1").status == "PROCESSED"
