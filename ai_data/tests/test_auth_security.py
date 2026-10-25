"""Access contract for the synthetic-only demo; analyst sessions were retired."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from ai_data.tests.test_db_helper import get_clean_test_session
import ai_data.api_server as api

class TestDemoAccess(unittest.TestCase):
    def setUp(self):
        self.session = get_clean_test_session()
        self.client = TestClient(api.app)
    def tearDown(self):
        self.session.close()
    def test_dashboard_endpoints_are_open(self):
        for path in ("/health", "/api/alerts", "/api/stats", "/api/network-graph", "/api/export"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
    def test_analyst_login_is_absent(self):
        self.assertEqual(self.client.post("/api/auth/login", json={}).status_code, 404)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 404)
    def test_image_ingestion_still_requires_server_token(self):
        with patch.dict("os.environ", {"INGEST_API_TOKEN": "test-server-token"}):
            response = self.client.post("/api/analyze-image", json={"image_base64": "invalid"})
        self.assertEqual(response.status_code, 401)
