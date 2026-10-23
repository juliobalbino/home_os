from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User


class AccountFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

    def test_register_normalizes_email_and_login_requires_csrf(self):
        rejected = self.client.post(
            "/api/v1/auth/register",
            {
                "email": "no-csrf@example.com",
                "name": "Person",
                "password": "longPassword123",
            },
            format="json",
        )
        self.assertEqual(rejected.status_code, 403)
        token = self.client.get("/api/v1/auth/csrf").json()["csrfToken"]
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "email": " Person@Example.com ",
                "name": "Person",
                "password": "longPassword123",
            },
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get()
        self.assertEqual(user.email, "person@example.com")
        self.assertTrue(user.check_password("longPassword123"))
        self.assertIn("csrftoken", self.client.cookies)

    def test_login_rejects_missing_csrf_and_accepts_bootstrapped_token(self):
        User.objects.create_user(
            email="a@example.com", name="A", password="legacy-password!"
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login",
                {"email": "a@example.com", "password": "legacy-password!"},
                format="json",
            ).status_code,
            403,
        )
        token = self.client.get("/api/v1/auth/csrf").json()["csrfToken"]
        response = self.client.post(
            "/api/v1/auth/login",
            {"email": "a@example.com", "password": "legacy-password!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)

    def test_registration_requires_six_alphanumeric_characters_only(self):
        token = self.client.get("/api/v1/auth/csrf").json()["csrfToken"]
        for password in ("abc12", "abc123!"):
            response = self.client.post(
                "/api/v1/auth/register",
                {
                    "email": f"{password}@example.com",
                    "name": "Person",
                    "password": password,
                },
                format="json",
                HTTP_X_CSRFTOKEN=token,
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("letras e números", response.json()["detail"])
        response = self.client.post(
            "/api/v1/auth/register",
            {"email": "valid@example.com", "name": "Person", "password": "abc123"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 201)

    def test_session_logout_invalidates_private_endpoint(self):
        user = User.objects.create_user(
            email="a@example.com", name="A", password="safe-password-123"
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 200)
        blocked = self.client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(blocked.status_code, 403)
        csrf = self.client.get("/api/v1/auth/csrf")
        token = csrf.json()["csrfToken"]
        response = self.client.post(
            "/api/v1/auth/logout", {}, format="json", HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)
