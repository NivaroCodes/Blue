"""PostgreSQL + API + worker contracts. S3/Gemini doubles are explicit, never seed results."""
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import boto3
from moto import mock_aws
from fastapi.testclient import TestClient

from ai_data.tests.test_db_helper import get_clean_test_session
from ai_data.db.seed import demo_messages, seed_demo, DEMO_CHAT_ID
from ai_data.db.models import MessageRecord
from ai_data.llm_client import AIAnalysisError
from ai_data.models import AnalysisResult, RiskLevelEnum
from ai_data.worker import process_pending_messages
from ai_data import media
import ai_data.api_server as api


class TestDemoPipeline(unittest.TestCase):
    def setUp(self):
        self.session = get_clean_test_session()
        self.client = TestClient(api.app)
        self.env = patch.dict(os.environ, {"INGEST_API_TOKEN": "", "MEDIA_STORAGE": "local"})
        self.env.start()
        self.inline = patch.object(api, "INLINE_ANALYSIS", False)
        self.inline.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = patch.object(media, "MEDIA_DIR", Path(self.tmp.name))
        self.directory.start()

    def tearDown(self):
        self.directory.stop()
        self.tmp.cleanup()
        self.inline.stop()
        self.env.stop()
        self.session.close()

    def test_seed_uses_ingestion_and_is_idempotent_without_fabricated_results(self):
        ids = seed_demo(self.client)
        self.assertEqual(seed_demo(self.client), ids)
        rows = self.session.query(MessageRecord).filter_by(chat_id=DEMO_CHAT_ID).all()
        self.assertEqual(len(rows), 36)
        self.assertEqual(len(set(ids)), 36)
        self.assertEqual(sum(bool(row.image_url) for row in rows), 3)
        self.assertTrue(all(row.status == "PENDING" and row.analysis is None for row in rows))
        self.assertTrue(all(row.text.startswith("[SYNTHETIC") for row in rows))

    @mock_aws
    def test_private_object_crosses_api_worker_and_dashboard_with_separate_disks(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="blue-test-private")
        payload = list(demo_messages())[-1]
        original = base64.b64decode(payload["image_base64"])
        result = AnalysisResult(risk_score=0, risk_level=RiskLevelEnum.LOW, reasons=[],
                                explanation="Synthetic transport test", confidence=0.8,
                                model_version="test-double", image_text="SYNTHETIC")
        with patch.dict(os.environ, {"MEDIA_STORAGE": "r2", "R2_BUCKET_NAME": "blue-test-private"}), \
                patch.object(media, "_r2_client", return_value=s3):
            response = self.client.post("/api/messages", json=payload)
            self.assertEqual(response.status_code, 200)
            alert_id = response.json()["id"]
            self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
            # Worker has another, empty filesystem. It must obtain the original object from S3.
            with tempfile.TemporaryDirectory() as worker_dir, \
                    patch.object(media, "MEDIA_DIR", Path(worker_dir)), \
                    patch("ai_data.analyzer.call_gemini_api", return_value=result) as model:
                self.assertEqual(process_pending_messages(self.session, api_key="test-key", throttle_seconds=0), 1)
                sent = model.call_args.kwargs["image_base64"]
                self.assertEqual(base64.b64decode(sent), original)
            alert = self.client.get(f"/api/alerts/{alert_id}").json()
            self.assertEqual(alert["status"], "PROCESSED")
            self.assertTrue(alert["image_analyzed"])
            self.assertEqual(self.client.get(alert["image_url"]).content, original)
            self.assertEqual(self.client.get("/api/stats").json()["total_messages"], 1)

    def test_failed_multimodal_analysis_never_sets_image_analyzed(self):
        response = self.client.post("/api/messages", json=list(demo_messages())[-1])
        self.assertEqual(response.status_code, 200)
        with patch("ai_data.analyzer.call_gemini_api", side_effect=AIAnalysisError("Model unavailable")):
            self.assertEqual(process_pending_messages(self.session, api_key="test-key", throttle_seconds=0), 0)
        alert = self.client.get(f"/api/alerts/{response.json()['id']}").json()
        self.assertEqual(alert["status"], "ERROR")
        self.assertFalse(alert["image_analyzed"])

    def test_r2_fails_closed_and_rejects_traversal(self):
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "test", "MEDIA_STORAGE": "local"}):
            with self.assertRaises(media.MediaError):
                media.storage_backend()
        with patch.dict(os.environ, {"MEDIA_STORAGE": "r2"}):
            with self.assertRaises(media.MediaError):
                media.read_stored_image("../private.png")
