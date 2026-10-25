import json
import os
import tempfile
import time
import webbrowser
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.assistant.configuration import assistant_is_ready
from apps.assistant.models import ChatGPTConnection, credential_cipher
from apps.assistant.services import AUTH_BASE, exchange_and_validate, new_authorization


class Command(BaseCommand):
    help = (
        "Complete Sign in with ChatGPT locally or import a protected credential bundle."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--host-id", help="Stable opaque host ID, e.g. urn:uuid:<UUID>"
        )
        parser.add_argument("--client-id", default="dynamic_agent_client")
        parser.add_argument(
            "--consent",
            action="store_true",
            help="Request consent again during reauthorization after an earlier decline.",
        )
        parser.add_argument("--output", default="chatgpt-credentials.enc")
        parser.add_argument("--import-file")
        parser.add_argument("--user-id", type=int)
        parser.add_argument("--revoke-client-id")

    def handle(self, *args, **options):
        if options["revoke_client_id"]:
            self.revoke(options["revoke_client_id"], options["user_id"])
        elif options["import_file"]:
            self.import_bundle(
                options["import_file"], options["user_id"], options["host_id"]
            )
        else:
            self.authorize(options)

    def authorize(self, options):
        try:
            credential_cipher()
            if options["user_id"]:
                get_user_model().objects.get(pk=options["user_id"])
        except Exception as exc:
            raise CommandError(
                "A valid ASSISTANT_ENCRYPTION_KEY and, when supplied, an existing Home OS user are required before OAuth."
            ) from exc
        if not options["host_id"]:
            raise CommandError(
                "--host-id is required; persist one stable opaque host ID per host."
            )
        redirect = "http://127.0.0.1:1455/auth/callback"
        authorize_url, pending = new_authorization(
            options["host_id"],
            redirect,
            options["client_id"],
            prompt_consent=options["consent"],
        )
        result = {}

        class Callback(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlparse(self.path).query)
                result.update(
                    {key: values[0] for key, values in params.items() if values}
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Authorization received. You may close this window.")

            def log_message(self, *_):
                return

        try:
            server = HTTPServer(("127.0.0.1", 1455), Callback)
        except OSError as exc:
            raise CommandError(
                "Could not bind exact loopback callback 127.0.0.1:1455."
            ) from exc
        self.stdout.write(
            "Opening browser for Sign in with ChatGPT; tokens will not be printed."
        )
        webbrowser.open(authorize_url)
        server.timeout = 300
        server.handle_request()
        server.server_close()
        if result.get("state") != pending["state"]:
            raise CommandError("OAuth state validation failed.")
        if result.get("error"):
            raise CommandError(
                "Authorization was not completed. Retry from the ChatGPT settings consent flow."
            )
        callback_client_id = result.get("client_id")
        if options["client_id"] == "dynamic_agent_client" and not callback_client_id:
            raise CommandError("Registration did not return an issued client_id.")
        if (
            options["client_id"] != "dynamic_agent_client"
            and callback_client_id
            and callback_client_id != options["client_id"]
        ):
            raise CommandError(
                "Callback client_id does not match the selected registration."
            )
        client_id = callback_client_id or options["client_id"]
        if client_id == "dynamic_agent_client":
            raise CommandError("Registration did not return an issued client_id.")
        try:
            claims, token, scopes = exchange_and_validate(
                result.get("code", ""), client_id, pending
            )
        except Exception as exc:
            raise CommandError(
                "OAuth exchange or identity validation failed; start a fresh sign-in."
            ) from exc
        token["expires_at"] = time.time() + int(token.get("expires_in", 0))
        if options["user_id"]:
            connection, _ = ChatGPTConnection.objects.get_or_create(
                user_id=options["user_id"],
                client_id=client_id,
                account_subject=claims["sub"],
            )
            connection.host_id = options["host_id"]
            connection.scopes = sorted(scopes)
            connection.status = (
                ("connected" if assistant_is_ready() else "pending_configuration")
                if "chatgpt.tokens.use.direct" in scopes
                else "consent_required"
            )
            connection.set_credentials(token)
            connection.save()
        bundle = {
            "client_id": client_id,
            "account_subject": claims["sub"],
            "scopes": sorted(scopes),
            "host_id": options["host_id"],
            "credentials": token,
        }
        output = Path(options["output"])
        fd, temporary = tempfile.mkstemp(prefix=".assistant-", dir=output.parent)
        try:
            with os.fdopen(fd, "wb") as protected_file:
                protected_file.write(
                    credential_cipher().encrypt(json.dumps(bundle).encode())
                )
                protected_file.flush()
                os.fsync(protected_file.fileno())
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.stdout.write(
            f"Credential bundle saved to {output}. Import on the target VM with assistant_oauth --import-file."
        )
        if "chatgpt.tokens.use.direct" not in scopes:
            self.stdout.write(
                self.style.WARNING(
                    "ChatGPT plan scope was not granted; inference is disabled."
                )
            )

    def import_bundle(self, filename, user_id, host_id):
        if not user_id or not host_id:
            raise CommandError(
                "--user-id and the VM's own stable --host-id are required for credential import."
            )
        if not host_id.startswith(
            ("urn:uuid:", "urn:ietf:params:oauth:jwk-thumbprint:", "did:key:")
        ):
            raise CommandError(
                "The VM host ID must use a supported opaque host-ID format."
            )
        try:
            bundle = json.loads(
                credential_cipher().decrypt(Path(filename).read_bytes())
            )
            user = get_user_model().objects.get(pk=user_id)
        except Exception as exc:
            raise CommandError(
                "Credential bundle could not be decrypted or user was not found."
            ) from exc
        connection, _ = ChatGPTConnection.objects.get_or_create(
            user=user,
            client_id=bundle["client_id"],
            account_subject=bundle["account_subject"],
        )
        connection.host_id = host_id
        connection.scopes = bundle["scopes"]
        connection.status = (
            ("connected" if assistant_is_ready() else "pending_configuration")
            if "chatgpt.tokens.use.direct" in connection.scopes
            else "consent_required"
        )
        connection.set_credentials(bundle["credentials"])
        connection.save()
        self.stdout.write(
            "Credential bundle imported; active status requires assistant enablement and the same encryption key."
        )

    def revoke(self, client_id, user_id):
        if not user_id:
            raise CommandError(
                "--user-id is required to revoke a Home OS user's connection."
            )
        try:
            connection = ChatGPTConnection.objects.get(
                user_id=user_id, client_id=client_id
            )
            credentials = connection.get_credentials()
        except Exception as exc:
            raise CommandError("The selected connection could not be loaded.") from exc
        confirmed = False
        try:
            discovery_request = urllib.request.Request(
                AUTH_BASE + "/.well-known/openid-configuration"
            )
            with urllib.request.urlopen(discovery_request, timeout=10) as response:
                revocation_endpoint = json.loads(response.read(65536))[
                    "revocation_endpoint"
                ]
            revoke_request = urllib.request.Request(
                revocation_endpoint,
                data=urlencode(
                    {
                        "token": credentials["refresh_token"],
                        "token_type_hint": "refresh_token",
                        "client_id": client_id,
                    }
                ).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            for attempt, delay in enumerate((0, 0.25, 0.75)):
                if delay:
                    time.sleep(delay)
                try:
                    with urllib.request.urlopen(revoke_request, timeout=15) as response:
                        confirmed = response.status == 200
                    if confirmed:
                        break
                except urllib.error.HTTPError as exc:
                    if not 500 <= exc.code < 600:
                        break
                except (urllib.error.URLError, TimeoutError, OSError):
                    if attempt == 2:
                        break
        except Exception:
            pass
        connection.credentials_ciphertext = ""
        connection.status = "revoked" if confirmed else "revocation_unconfirmed"
        connection.save(
            update_fields=["credentials_ciphertext", "status", "updated_at"]
        )
        if confirmed:
            self.stdout.write(
                "ChatGPT renewable session revoked and local tokens cleared."
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Local tokens cleared; remote revocation was not confirmed. Disconnect in ChatGPT Settings."
                )
            )
