from unittest.mock import patch

from django.db.utils import OperationalError
from rest_framework.test import APISimpleTestCase


class HealthEndpointTests(APISimpleTestCase):
    def test_returns_ok_when_database_connection_succeeds(self):
        with patch("apps.health.views.connections") as connections:
            response = self.client.get("/api/v1/health")

        connections["default"].ensure_connection.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "connected"})

    def test_returns_service_unavailable_when_database_connection_fails(self):
        with patch("apps.health.views.connections") as connections:
            connections["default"].ensure_connection.side_effect = OperationalError(
                "unavailable"
            )
            response = self.client.get("/api/v1/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"status": "unhealthy", "database": "unavailable"}
        )
