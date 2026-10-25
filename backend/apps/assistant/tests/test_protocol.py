import base64
import hashlib
import urllib.parse
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.assistant.services import (
    AUTH_BASE,
    exchange_and_validate,
    new_authorization,
    parse_candidate_output,
    validate_request,
)


class AssistantProtocolTests(SimpleTestCase):
    def test_authorization_uses_pkce_state_nonce_and_exact_loopback(self):
        url, pending = new_authorization(
            "urn:uuid:host", "http://127.0.0.1:1455/auth/callback"
        )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(pending["verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        self.assertEqual(query["code_challenge"][0], expected)
        self.assertEqual(query["code_challenge_method"][0], "S256")
        self.assertEqual(query["ext_agent_host_id"][0], "urn:uuid:host")
        self.assertIn("chatgpt.tokens.use.direct", query["scope"][0])
        with self.assertRaises(ValidationError):
            new_authorization("urn:uuid:host", "http://localhost:1455/auth/callback")

    def test_reauthorization_can_explicitly_request_consent_again(self):
        url, _ = new_authorization(
            "urn:uuid:host",
            "http://127.0.0.1:1455/auth/callback",
            client_id="oaiapp_existing",
            prompt_consent=True,
        )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["prompt"], ["consent"])
        self.assertNotIn("agent_name_hint", query)

    def test_prompt_and_image_limits_reject_oversized_content(self):
        with self.assertRaises(ValidationError):
            validate_request("x" * 4001)
        with self.assertRaises(ValidationError):
            validate_request("label", "x" * (5 * 1024 * 1024))

    def test_candidate_output_must_be_validated_structured_data(self):
        data = parse_candidate_output(
            '{"name":"Milk","brand":"A","quantity":"1 L","unit":"L","price_minor":499}'
        )
        self.assertEqual(data["name"], "Milk")
        with self.assertRaises(ValidationError):
            parse_candidate_output('{"name":"Milk","price_minor":-1}')

    @patch("apps.assistant.services._post_form")
    @patch("apps.assistant.services.jwt.PyJWKClient")
    def test_id_token_signature_issuer_audience_expiry_nonce_and_scope_are_checked(
        self, jwks_client, post_form
    ):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks_client.return_value.get_signing_key_from_jwt.return_value.key = (
            key.public_key()
        )
        claims = {
            "iss": AUTH_BASE,
            "aud": "oaiapp_test",
            "sub": "account-sub",
            "exp": datetime.now(dt_timezone.utc) + timedelta(minutes=5),
            "nonce": "expected",
        }
        encoded = jwt.encode(claims, key, algorithm="RS256")
        post_form.return_value = {
            "id_token": encoded,
            "access_token": "token",
            "scope": "openid chatgpt.tokens.use.direct",
        }
        identity, token, scopes = exchange_and_validate(
            "code",
            "oaiapp_test",
            {
                "verifier": "pkce",
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
                "nonce": "expected",
            },
        )
        self.assertEqual(identity["sub"], "account-sub")
        self.assertIn("chatgpt.tokens.use.direct", scopes)
        post_form.return_value["id_token"] = jwt.encode(
            {**claims, "nonce": "wrong"}, key, algorithm="RS256"
        )
        with self.assertRaises(ValidationError):
            exchange_and_validate(
                "code",
                "oaiapp_test",
                {
                    "verifier": "pkce",
                    "redirect_uri": "http://127.0.0.1:1455/auth/callback",
                    "nonce": "expected",
                },
            )
