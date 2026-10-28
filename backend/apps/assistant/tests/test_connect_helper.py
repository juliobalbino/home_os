import urllib.parse
from io import StringIO
from unittest.mock import Mock
from urllib.request import Request

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.assistant.connect_helper import (
    NoRedirectHandler,
    parse_callback,
    run_connect,
    validate_authorization_url,
    validate_server_url,
)


def build_authorization_url(redirect_uri, state):
    params = {
        "response_type": "code",
        "client_id": "dynamic_agent_client",
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": "test-nonce",
        "code_challenge": "test-challenge",
        "code_challenge_method": "S256",
        "scope": "openid chatgpt.tokens.use.direct",
        "resource": "https://api.openai.com/v1",
    }
    return "https://auth.openai.com/api/accounts/authorize?" + urllib.parse.urlencode(
        params
    )


class ConnectHelperValidationTests(SimpleTestCase):
    def test_server_url_requires_https_origin_and_root_path(self):
        self.assertEqual(
            validate_server_url("https://home.example.test"),
            "https://home.example.test",
        )
        for url in (
            "http://home.example.test",
            "https://user:password@home.example.test",
            "https://home.example.test/?query=1",
            "https://home.example.test/#fragment",
            "https://home.example.test/api",
        ):
            with (
                self.subTest(url=url),
                self.assertRaises((ValueError, ValidationError)),
            ):
                validate_server_url(url)

    def test_authorization_url_requires_trusted_endpoint_and_oauth_parameters(self):
        redirect_uri = "http://127.0.0.1:1455/auth/callback"
        params = {
            "response_type": "code",
            "client_id": "dynamic_agent_client",
            "redirect_uri": redirect_uri,
            "state": "state-value",
            "nonce": "nonce-value",
            "code_challenge": "challenge-value",
            "code_challenge_method": "S256",
            "scope": "openid chatgpt.tokens.use.direct",
            "resource": "https://api.openai.com/v1",
        }
        url = (
            "https://auth.openai.com/api/accounts/authorize?"
            + urllib.parse.urlencode(params)
        )
        self.assertEqual(validate_authorization_url(url, redirect_uri), url)
        parsed_url = urllib.parse.urlsplit(url)
        query_params = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)

        def mutate_params(**updates):
            mutated = [(key, updates.get(key, value)) for key, value in query_params]
            return urllib.parse.urlunsplit(
                parsed_url._replace(query=urllib.parse.urlencode(mutated))
            )

        def append_params(**additions):
            appended = query_params + list(additions.items())
            return urllib.parse.urlunsplit(
                parsed_url._replace(query=urllib.parse.urlencode(appended))
            )

        trusted_origin_variants = (
            parsed_url._replace(netloc="evil.example"),
            parsed_url._replace(netloc="user@auth.openai.com"),
            parsed_url._replace(netloc="auth.openai.com:8443"),
        )
        bad_urls = [
            urllib.parse.urlunsplit(variant) for variant in trusted_origin_variants
        ] + [
            mutate_params(redirect_uri="http://127.0.0.1:1456/auth/callback"),
            mutate_params(client_id="other-client"),
            mutate_params(state=""),
            mutate_params(nonce=""),
            mutate_params(code_challenge_method="plain"),
            mutate_params(scope="profile"),
            mutate_params(resource="https://api.openai.com/v2"),
            append_params(id_token_hint="prior-id-token"),
            append_params(login_hint="prior@example.test"),
        ]
        self.assertTrue(all(bad_url != url for bad_url in bad_urls))
        for bad_url in bad_urls:
            with (
                self.subTest(url=bad_url),
                self.assertRaises((ValueError, ValidationError)),
            ):
                validate_authorization_url(bad_url, redirect_uri)


class CallbackParsingTests(SimpleTestCase):
    def test_parse_callback_validates_state_and_required_values(self):
        callback = "http://127.0.0.1:1455/auth/callback?state=expected&code=sample-code&client_id=sample-client"
        parsed = parse_callback(callback, "expected")
        self.assertEqual(parsed["code"], "sample-code")
        self.assertEqual(parsed["client_id"], "sample-client")

        invalid = (
            "http://127.0.0.1:1455/auth/callback?state=wrong&code=sample-code&client_id=sample-client",
            "http://127.0.0.1:1455/auth/callback?state=expected&client_id=sample-client",
            "http://127.0.0.1:1455/auth/callback?state=expected&code=sample-code",
        )
        for value in invalid:
            with (
                self.subTest(callback=value),
                self.assertRaises((ValueError, ValidationError)),
            ):
                parse_callback(value, "expected")

    def test_login_required_is_reported_as_provider_error(self):
        result = parse_callback(
            "http://127.0.0.1:1455/auth/callback?state=expected&error=login_required",
            "expected",
        )
        self.assertEqual(result["error"], "login_required")


class ConnectFlowTests(SimpleTestCase):
    def test_claim_open_callback_and_complete_flow_keeps_secrets_out_of_output(self):
        pairing_code = "pairing-secret"
        helper_token = "helper-secret"
        redirect_uri = "http://127.0.0.1:1455/auth/callback"
        auth_url = build_authorization_url(redirect_uri, "expected-state")
        claim_response = {"helper_token": helper_token, "authorization_url": auth_url}
        completion_response = {"status": "connected", "connected": True}
        requests = []

        def http_post(url, *, json=None, headers=None):
            requests.append((url, json, headers))
            return (claim_response, completion_response)[len(requests) - 1]

        callback = Mock()
        callback.redirect_uri = redirect_uri
        callback.wait.return_value = {
            "state": "expected-state",
            "code": "oauth-secret",
            "client_id": "issued-client",
        }
        output = StringIO()
        browser_open = Mock()
        run_connect(
            "https://home.example.test",
            pairing_code,
            http_post=http_post,
            browser_open=browser_open,
            callback_factory=lambda: callback,
            output=output,
        )
        self.assertEqual(len(requests), 2)
        parsed_auth_url = urllib.parse.urlparse(auth_url)
        parsed_params = urllib.parse.parse_qs(parsed_auth_url.query)
        self.assertEqual(parsed_auth_url.path, "/api/accounts/authorize")
        self.assertEqual(
            parsed_params["redirect_uri"], ["http://127.0.0.1:1455/auth/callback"]
        )
        self.assertEqual(parsed_params["response_type"], ["code"])
        self.assertEqual(parsed_params["client_id"], ["dynamic_agent_client"])
        self.assertEqual(parsed_params["state"], ["expected-state"])
        self.assertEqual(parsed_params["nonce"], ["test-nonce"])
        self.assertEqual(parsed_params["code_challenge"], ["test-challenge"])
        self.assertEqual(parsed_params["code_challenge_method"], ["S256"])
        self.assertIn("chatgpt.tokens.use.direct", parsed_params["scope"][0].split())
        browser_open.assert_called_once_with(auth_url)
        callback.wait.assert_called_once_with("expected-state")
        callback.close.assert_called_once_with()
        self.assertEqual(
            requests[0][1],
            {
                "pairing_code": pairing_code,
                "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            },
        )
        self.assertEqual(
            requests[1][1],
            {
                "authorization_code": "oauth-secret",
                "state": "expected-state",
                "client_id": "issued-client",
            },
        )
        self.assertEqual(requests[1][2], {"Authorization": f"Bearer {helper_token}"})
        self.assertNotIn(pairing_code, output.getvalue())
        self.assertNotIn(helper_token, output.getvalue())
        self.assertNotIn("oauth-secret", output.getvalue())

    def test_callback_state_must_match_before_complete(self):
        response = {
            "helper_token": "helper",
            "authorization_url": build_authorization_url(
                "http://127.0.0.1:1455/auth/callback", "expected"
            ),
        }
        post = Mock(return_value=response)
        callback = Mock()
        callback.redirect_uri = "http://127.0.0.1:1455/auth/callback"
        callback.wait.return_value = {
            "state": "wrong",
            "code": "code",
            "client_id": "client",
        }
        with self.assertRaises((ValueError, ValidationError)):
            run_connect(
                "https://home.example.test",
                "pair",
                http_post=post,
                browser_open=Mock(),
                callback_factory=lambda: callback,
                output=StringIO(),
            )
        self.assertEqual(post.call_count, 1)
        callback.wait.assert_called_once_with("expected")
        callback.close.assert_called_once_with()

    def test_provider_oauth_error_posts_only_state_and_error(self):
        claim_response = {
            "helper_token": "helper",
            "authorization_url": build_authorization_url(
                "http://127.0.0.1:1455/auth/callback", "expected"
            ),
        }
        cancellation_response = {"status": "cancelled", "connected": False}
        calls = []

        def post(url, *, json=None, headers=None):
            calls.append((json, headers))
            return (claim_response, cancellation_response)[len(calls) - 1]

        output = StringIO()
        callback = Mock()
        callback.redirect_uri = "http://127.0.0.1:1455/auth/callback"
        callback.wait.return_value = {"state": "expected", "error": "login_required"}
        run_connect(
            "https://home.example.test",
            "pair",
            http_post=post,
            browser_open=Mock(),
            callback_factory=lambda: callback,
            output=output,
        )
        callback.wait.assert_called_once_with("expected")
        callback.close.assert_called_once_with()
        self.assertEqual(calls[1][0], {"state": "expected", "error": "login_required"})


class NoRedirectTests(SimpleTestCase):
    def test_redirect_requests_are_refused(self):
        handler = NoRedirectHandler()
        request = Request("https://home.example.test")
        self.assertIsNone(
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://evil.example"
            )
        )
