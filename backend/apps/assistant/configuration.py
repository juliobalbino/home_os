from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


def assistant_is_ready():
    """AI stays unavailable unless explicitly enabled with encryption configured."""
    if not getattr(settings, "ASSISTANT_ENABLED", False):
        return False
    key = getattr(settings, "ASSISTANT_ENCRYPTION_KEY", "")
    try:
        Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError, InvalidToken):
        return False
    return True


def assistant_configuration_status():
    if not getattr(settings, "ASSISTANT_ENABLED", False):
        return "disabled"
    if not assistant_is_ready():
        return "missing_or_invalid_encryption_key"
    return "ready"
