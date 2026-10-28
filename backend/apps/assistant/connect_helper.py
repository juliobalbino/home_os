"""Small, stdlib-only Windows helper for completing Home OS assistant pairing."""

import getpass
import http.server
import json as json_module
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


class HelperError(ValueError):
    """A safe, non-sensitive error suitable for display to the user."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_server_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError
        port = parsed.port
        if port == 0:
            raise ValueError
        return urllib.parse.urlunsplit(("https", parsed.netloc, "", "", "")).rstrip("/")
    except (TypeError, ValueError):
        raise HelperError("Invalid Home OS server URL.") from None


def validate_authorization_url(url, redirect_uri):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "auth.openai.com"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/api/accounts/authorize"
            or parsed.fragment
        ):
            raise ValueError
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        params = {}
        for key, value in pairs:
            if key in params:
                raise ValueError
            params[key] = value
        if (
            "id_token_hint" in params
            or "login_hint" in params
            or params.get("client_id") != "dynamic_agent_client"
            or params.get("redirect_uri") != redirect_uri
            or params.get("resource") != "https://api.openai.com/v1"
            or params.get("response_type") != "code"
            or not params.get("state")
            or not params.get("nonce")
            or not params.get("code_challenge")
            or params.get("code_challenge_method") != "S256"
            or "chatgpt.tokens.use.direct" not in params.get("scope", "").split()
        ):
            raise ValueError
        return url
    except (TypeError, ValueError):
        raise HelperError(
            "The authorization service returned an invalid URL."
        ) from None


def _single(query, key):
    values = query.get(key, [])
    if len(values) > 1:
        raise HelperError("Invalid authorization callback.")
    return values[0] if values else None


def parse_callback(callback, expected_state):
    try:
        if not isinstance(callback, str):
            raise ValueError
        parsed = urllib.parse.urlsplit(callback)
        if parsed.scheme or parsed.netloc:
            if (
                parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or parsed.port is None
                or not 1 <= parsed.port <= 65535
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError
        elif parsed.path != "/auth/callback":
            raise ValueError
        if parsed.fragment or parsed.path != "/auth/callback":
            raise ValueError
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        state = _single(query, "state")
        if (
            not isinstance(state, str)
            or not isinstance(expected_state, str)
            or not secrets.compare_digest(state, expected_state)
        ):
            raise HelperError("Invalid authorization callback.")
        error = _single(query, "error")
        code, client_id = _single(query, "code"), _single(query, "client_id")
        _single(query, "error_description")
        if error is not None:
            if (
                code is not None
                or client_id is not None
                or not error
                or len(error) > 64
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", error, flags=re.ASCII)
                is None
            ):
                raise HelperError("Invalid authorization callback.")
            return {"state": state, "error": error}
        if not code or not client_id:
            raise HelperError("Invalid authorization callback.")
        return {"state": state, "code": code, "client_id": client_id}
    except (TypeError, ValueError):
        raise HelperError("Invalid authorization callback.") from None


class LocalCallbackServer:
    def __init__(self):
        self.result = None
        self._event = threading.Event()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                try:
                    if not owner.expected_state:
                        raise HelperError("Invalid authorization callback.")
                    owner.result = parse_callback(self.path, owner.expected_state)
                    body, status = (
                        b"Authorization complete. You may close this window.",
                        200,
                    )
                    owner._event.set()
                except HelperError:
                    body, status = b"Invalid authorization response.", 400
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.expected_state = None
        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 0.25
        self.redirect_uri = (
            "http://127.0.0.1:%d/auth/callback" % self._server.server_port
        )
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._event.is_set():
            self._server.handle_request()

    def wait(self, expected_state):
        self.expected_state = expected_state
        deadline = time.monotonic() + 300
        while not self._event.is_set() and time.monotonic() < deadline:
            self._event.wait(min(0.25, max(0, deadline - time.monotonic())))
        if not self._event.is_set():
            raise HelperError("Authorization timed out. Please try again.")
        return self.result

    def close(self):
        self._event.set()
        if self._thread.is_alive():
            self._thread.join()
        self._server.server_close()


def post_json(url, *, json=None, headers=None):
    try:
        data = json_module.dumps(json).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        opener = urllib.request.build_opener(NoRedirectHandler())
        with opener.open(request, timeout=30) as response:
            result = json_module.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except Exception:
        raise HelperError(
            "The Home OS request failed. Check the server and try again."
        ) from None


def run_connect(
    server_url,
    pairing_code,
    *,
    http_post=post_json,
    browser_open=None,
    callback_factory=LocalCallbackServer,
    output=None,
):
    output = output or sys.stdout
    server = validate_server_url(server_url)
    callback = callback_factory()
    try:
        redirect_uri = callback.redirect_uri
        claim = http_post(
            server + "/api/v1/assistant/connect/pairings/claim",
            json={"pairing_code": pairing_code, "redirect_uri": redirect_uri},
        )
        token, auth_url = claim.get("helper_token"), claim.get("authorization_url")
        if not isinstance(token, str) or not token:
            raise HelperError(
                "Unable to start assistant connection. Check the pairing code."
            )
        validate_authorization_url(auth_url, redirect_uri)
        parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(auth_url).query)
        expected_state = parsed["state"][0]
        if isinstance(callback, LocalCallbackServer):
            callback.expected_state = expected_state
        opener = browser_open or webbrowser.open
        opener(auth_url)
        result = callback.wait(expected_state)
        if result.get("state") != expected_state:
            raise HelperError("Invalid authorization callback.")
        if result.get("error"):
            payload = {"state": expected_state, "error": result["error"]}
        else:
            if not result.get("code") or not result.get("client_id"):
                raise HelperError("Invalid authorization callback.")
            payload = {
                "authorization_code": result["code"],
                "state": expected_state,
                "client_id": result["client_id"],
            }
        completion = http_post(
            server + "/api/v1/assistant/connect/pairings/complete",
            json=payload,
            headers={"Authorization": "Bearer " + token},
        )
        status = completion.get("status") if isinstance(completion, dict) else None
        messages = {
            "connected": "Home OS assistant connected.",
            "consent_required": "Additional consent is required to connect.",
            "pending_configuration": "Connection is pending configuration.",
            "cancelled": "Connection cancelled.",
        }
        if status not in messages:
            raise HelperError(
                "The Home OS request failed. Check the server and try again."
            )
        print(messages[status], file=output)
        return completion
    finally:
        callback.close()


def main():
    try:
        origin = input("Home OS HTTPS server URL: ")
        code = getpass.getpass("Pairing code: ")
        run_connect(origin, code)
    except HelperError as exc:
        print(str(exc), file=sys.stdout)
        return 1
    except (KeyboardInterrupt, EOFError):
        print(
            "Connection cancelled. Run the pairing flow again when ready.",
            file=sys.stdout,
        )
        return 1
    except Exception:
        print(
            "Unable to complete assistant connection. Please try again.",
            file=sys.stdout,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
